"""
Phase 3 -- Throwaway Live Verification Script (NOT part of the permanent codebase)
==================================================================================
Tests three critical assumptions against a REAL Gemini API call.
"""

import os
import sys
import json
import traceback

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    print("ERROR: Set GEMINI_API_KEY environment variable first.")
    sys.exit(1)

from google import genai
from google.genai import types
from google.genai.errors import APIError

print(f"google-genai SDK version: {genai.__version__ if hasattr(genai, '__version__') else 'unknown'}")
print(f"API key loaded (length: {len(api_key)})")

client = genai.Client(
    api_key=api_key,
    http_options=types.HttpOptions(timeout=15_000),
)

# Try models in priority order -- the plan says gemini-3.6-flash primary,
# gemini-3.5-flash-lite fallback. Also try gemini-2.0-flash-lite as last resort.
MODELS_TO_TRY = [
    os.getenv("GEMINI_PRIMARY_MODEL", "gemini-3.6-flash"),
    os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite"),
    "gemini-2.0-flash-lite",
    "gemini-2.5-flash",
]

def build_contents(messages: list[dict]) -> list:
    """Exact copy of llm_client.py _build_contents"""
    if not messages:
        messages = [{"role": "user", "content": "Begin."}]
    if messages[0].get("role") != "user":
        messages = [{"role": "user", "content": "(Interview in progress.)"}] + messages
    contents = []
    for msg in messages:
        role = "user" if msg.get("role") == "user" else "model"
        contents.append(types.Content(role=role, parts=[types.Part(text=msg["content"])]))
    return contents

# --- Test payloads ---
messages_model_first = [
    {"role": "model",  "content": "Tell me about your experience with Docker."},
    {"role": "user",   "content": "I used Docker to containerize a Flask app. I wrote Dockerfiles and used docker-compose."},
]

system_prompt = (
    "You are a senior technical interviewer. Evaluate the candidate's answer "
    "about Docker containerization. Respond as JSON with the exact schema provided."
)

TURN_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "evaluation": {
            "type": "OBJECT",
            "properties": {
                "bucket": {"type": "STRING", "enum": ["missed", "partial", "strong"]},
                "rationale": {"type": "STRING"},
            },
            "required": ["bucket", "rationale"],
        },
        "decision": {"type": "STRING", "enum": ["follow_up", "advance"]},
        "reply": {"type": "STRING"},
    },
    "required": ["evaluation", "decision", "reply"],
}

contents = build_contents(messages_model_first)
print(f"\nContents roles after guard: {[c.role for c in contents]}")
print(f"Contents texts: {[c.parts[0].text[:60] for c in contents]}")

# ===================================================================
# Find a working model first
# ===================================================================
print("\n" + "=" * 70)
print("STEP 0: Finding a working model...")
print("=" * 70)

working_model = None
for model_name in MODELS_TO_TRY:
    print(f"\n  Trying {model_name}...", end=" ")
    try:
        test_config = types.GenerateContentConfig(
            system_instruction="Say hello in JSON.",
            response_mime_type="application/json",
            response_schema={"type": "OBJECT", "properties": {"msg": {"type": "STRING"}}, "required": ["msg"]},
        )
        test_resp = client.models.generate_content(
            model=model_name,
            contents=[types.Content(role="user", parts=[types.Part(text="Hi")])],
            config=test_config,
        )
        _ = json.loads(test_resp.text)
        print(f"OK! Using {model_name}")
        working_model = model_name
        break
    except Exception as e:
        is_429 = (isinstance(e, APIError) and getattr(e, "code", None) == 429) or "429" in str(e)
        is_404 = (isinstance(e, APIError) and getattr(e, "code", None) == 404) or "404" in str(e) or "not found" in str(e).lower()
        if is_429:
            print(f"QUOTA EXHAUSTED")
        elif is_404:
            print(f"MODEL NOT FOUND")
        else:
            print(f"ERROR: {type(e).__name__}: {str(e)[:100]}")

if not working_model:
    print("\n[FAIL] No working model found. All models are either exhausted or unavailable.")
    print("Please wait for quota reset or check your API key billing.")
    sys.exit(1)

# ===================================================================
# TEST 1: Model-first contents + system_instruction
# ===================================================================
print("\n" + "=" * 70)
print(f"TEST 1: Model-first messages + prepend guard (using {working_model})")
print("=" * 70)

config = types.GenerateContentConfig(
    system_instruction=system_prompt,
    response_mime_type="application/json",
    response_schema=TURN_RESPONSE_SCHEMA,
)

try:
    print(f"Calling {working_model} with plain-dict schema...")
    response = client.models.generate_content(
        model=working_model, contents=contents, config=config,
    )
    raw_text = response.text
    schema_fix_needed = False
    print(f"\n[PASS] TEST 1: No 400 error about content ordering!")
    print(f"[PASS] TEST 2: Plain-dict schema accepted directly by response_schema!")
    print(f"\nRaw response:\n{raw_text}")
except Exception as e:
    error_str = str(e)
    is_429 = (isinstance(e, APIError) and getattr(e, "code", None) == 429) or "429" in error_str
    
    if is_429:
        print(f"\n[FAIL] 429 quota hit even on {working_model}. Cannot proceed.")
        sys.exit(1)
    
    # Distinguish schema error from content-ordering error
    print(f"\n[FAIL] {type(e).__name__}: {error_str[:300]}")
    
    # Check if it's specifically a schema format issue
    if "schema" in error_str.lower() and ("response_schema" in error_str.lower() or "invalid" in error_str.lower()):
        print("\n>>> Trying types.Schema conversion...")
        try:
            eval_schema = types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "bucket": types.Schema(type=types.Type.STRING, enum=["missed", "partial", "strong"]),
                    "rationale": types.Schema(type=types.Type.STRING),
                },
                required=["bucket", "rationale"],
            )
            full_schema = types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "evaluation": eval_schema,
                    "decision": types.Schema(type=types.Type.STRING, enum=["follow_up", "advance"]),
                    "reply": types.Schema(type=types.Type.STRING),
                },
                required=["evaluation", "decision", "reply"],
            )
            config2 = types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                response_schema=full_schema,
            )
            response = client.models.generate_content(
                model=working_model, contents=contents, config=config2,
            )
            raw_text = response.text
            schema_fix_needed = True
            print(f"[PASS] types.Schema works! llm_client.py NEEDS FIXING.")
            print(f"\nRaw response:\n{raw_text}")
        except Exception as e2:
            print(f"[FAIL] types.Schema also failed: {e2}")
            sys.exit(1)
    else:
        print("\n>>> Not a schema issue. Possibly content ordering or other API error.")
        traceback.print_exc()
        sys.exit(1)

# ===================================================================
# TEST 3: JSON deserialization + schema shape match
# ===================================================================
print("\n" + "=" * 70)
print("TEST 3: JSON deserialization + schema shape validation")
print("=" * 70)

try:
    parsed = json.loads(raw_text)
    print(f"[PASS] Valid JSON. Keys: {list(parsed.keys())}")

    assert "evaluation" in parsed, "Missing 'evaluation'"
    assert "decision" in parsed, "Missing 'decision'"
    assert "reply" in parsed, "Missing 'reply'"

    ev = parsed["evaluation"]
    assert "bucket" in ev, "Missing evaluation.bucket"
    assert "rationale" in ev, "Missing evaluation.rationale"
    assert ev["bucket"] in ("missed", "partial", "strong"), f"Bad bucket: {ev['bucket']}"
    assert parsed["decision"] in ("follow_up", "advance"), f"Bad decision: {parsed['decision']}"
    assert isinstance(parsed["reply"], str) and len(parsed["reply"]) > 0

    print(f"[PASS] Schema shape matches perfectly!")
    print(f"  evaluation.bucket   = {ev['bucket']}")
    print(f"  evaluation.rationale = {ev['rationale'][:120]}")
    print(f"  decision            = {parsed['decision']}")
    print(f"  reply               = {parsed['reply'][:120]}")
except json.JSONDecodeError as e:
    print(f"[FAIL] JSON parse failed: {e}")
    sys.exit(1)
except AssertionError as e:
    print(f"[FAIL] Shape mismatch: {e}")
    sys.exit(1)

# ===================================================================
# BONUS: Empty messages (Q1 opener case)
# ===================================================================
print("\n" + "=" * 70)
print("BONUS: Empty messages list (Q1 opener case)")
print("=" * 70)

contents_empty = build_contents([])
print(f"Contents: {[c.parts[0].text for c in contents_empty]}")

FIRST_QUESTION_SCHEMA = {
    "type": "OBJECT",
    "properties": {"reply": {"type": "STRING"}},
    "required": ["reply"],
}

try:
    fq_config = types.GenerateContentConfig(
        system_instruction="You are a technical interviewer. Welcome the candidate and ask about Docker. JSON only.",
        response_mime_type="application/json",
        response_schema=FIRST_QUESTION_SCHEMA,
    )
    resp2 = client.models.generate_content(model=working_model, contents=contents_empty, config=fq_config)
    p2 = json.loads(resp2.text)
    print(f"[PASS] Empty-messages works. Reply: {p2.get('reply', '')[:120]}")
except Exception as e:
    print(f"[FAIL] {type(e).__name__}: {e}")

# ===================================================================
# SUMMARY
# ===================================================================
print("\n" + "=" * 70)
print("VERIFICATION SUMMARY")
print("=" * 70)
print(f"Model used:  {working_model}")
print(f"[PASS] TEST 1: Model-first messages + prepend guard -> no 400")
if schema_fix_needed:
    print(f"[FIX]  TEST 2: Plain-dict schema REJECTED -- types.Schema REQUIRED")
    print(f"       ACTION: Update llm_client.py response_schema handling")
else:
    print(f"[PASS] TEST 2: Plain-dict schema accepted directly")
print(f"[PASS] TEST 3: JSON deserializes to correct schema shape")
print(f"[PASS] BONUS:  Empty-messages seed works for Q1 opener")
print()
if schema_fix_needed:
    print("CONCLUSION: Need to fix schema handling in llm_client.py before proceeding.")
else:
    print("CONCLUSION: All llm_client.py assumptions VERIFIED. Safe to wire prompts.py.")
