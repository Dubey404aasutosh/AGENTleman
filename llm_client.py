"""
LLM Client module (Component 5.3, Phase 3).
Wrapper for Gemini API calls with fallback logic, system instruction configuration, and content guards.
"""

import os
import json
from google import genai
from google.genai import types
from google.genai.errors import APIError

PRIMARY_MODEL = os.getenv("GEMINI_PRIMARY_MODEL", "gemini-3.6-flash")
FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite")


class LLMCallError(Exception):
    """Every LLM failure path terminates here — quota exhaustion on both tiers,
    timeouts, parse failures, network errors. The turn engine and feedback
    synthesizer each catch this and degrade deterministically; no raw SDK
    exception should ever escape to become an unhandled 500 (Decision #21)."""


class LLMClient:
    def __init__(self, api_key: str):
        self.client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=15_000),  # ms, constructor-level (Decision #24)
        )

    def generate(self, system_prompt: str, messages: list[dict],
                 response_schema: dict, session) -> dict:
        model = FALLBACK_MODEL if session.using_fallback else PRIMARY_MODEL
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,          # kept OUT of contents (Decision #3)
            response_mime_type="application/json",
            response_schema=response_schema,
        )
        contents = self._build_contents(messages)

        try:
            response = self.client.models.generate_content(model=model, contents=contents, config=config)
            return json.loads(response.text)
        except Exception as e:
            is_quota = (isinstance(e, APIError) and getattr(e, "code", None) == 429) \
                       or "ResourceExhausted" in type(e).__name__ or "429" in str(e)

            if is_quota and not session.using_fallback:
                session.using_fallback = True                     # sticky (Decision #23)
                try:
                    return self.generate(system_prompt, messages, response_schema, session)
                except Exception as fallback_e:
                    raise LLMCallError(
                        f"Both models exhausted. Primary: {e}. Fallback: {fallback_e}"
                    ) from fallback_e

            # Non-quota error, or already on fallback → one retry, same model
            try:
                response = self.client.models.generate_content(model=model, contents=contents, config=config)
                return json.loads(response.text)
            except Exception as retry_e:
                raise LLMCallError(f"LLM failed after retry on {model}: {retry_e}") from retry_e

    def _build_contents(self, messages: list[dict]) -> list:
        """
        Two guarantees, neither of which ever discards a real conversation turn:

          1. `contents` is never empty (Gemini rejects empty contents) — seeded
             with one synthetic anchor turn if `messages` is empty. (Decision #4)

          2. `contents` always starts with a `user` turn (Gemini requires this).
             If the real first message is `model`-role (the sliding window
             legitimately opens on the question just asked, every single topic),
             a synthetic anchor `user` turn is PREPENDED — never stripped.
             Stripping was tried in an earlier draft and rejected: it silently
             deleted the model's actual question from what the evaluator sees
             on the very next call. (Decision #5 — the final fix)
        """
        if not messages:
            messages = [{"role": "user", "content": "Begin."}]
        if messages[0].get("role") != "user":
            messages = [{"role": "user", "content": "(Interview in progress.)"}] + messages

        contents = []
        for msg in messages:
            role = "user" if msg.get("role") == "user" else "model"
            contents.append(types.Content(role=role, parts=[types.Part(text=msg["content"])]))
        return contents


# Module-level singleton, constructed once at app startup with the real key
# (Decision #31 — resolves the class-vs-bare-function ambiguity from v1-v4).
_client: LLMClient | None = None

def init_client(api_key: str) -> None:
    global _client
    _client = LLMClient(api_key=api_key)

def generate(system_prompt: str, messages: list[dict], response_schema: dict, session) -> dict:
    if _client is None:
        raise RuntimeError("llm_client.init_client() must be called at app startup")
    return _client.generate(system_prompt, messages, response_schema, session)
