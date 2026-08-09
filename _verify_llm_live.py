"""
Phase 3 -- Throwaway Live Verification Script (NOT part of the permanent codebase)
==================================================================================
Tests critical assumptions against a REAL Gemini API call, plus mock-verifies
the sticky fallback path without burning quota.

All live tests go through the REAL llm_client.generate() -> _build_contents()
path, not hand-rolled reproductions.

Usage:
  $env:GEMINI_API_KEY = "your_key_here"
  python _verify_llm_live.py
"""

import os
import sys
import json
import traceback
from unittest.mock import MagicMock

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    print("ERROR: Set GEMINI_API_KEY environment variable first.")
    sys.exit(1)

# -- Initialize the REAL llm_client module (the code under test) --
import llm_client
from llm_client import LLMCallError
from google.genai.errors import APIError

llm_client.init_client(api_key=api_key)
print(f"llm_client initialized with real API key (length: {len(api_key)})")
print(f"PRIMARY_MODEL = {llm_client.PRIMARY_MODEL}")
print(f"FALLBACK_MODEL = {llm_client.FALLBACK_MODEL}")

results = {}   # track pass/fail per test


# -- Minimal session stub matching what llm_client.generate() reads --
class FakeSession:
    """Mimics the two fields llm_client.generate() touches on SessionState."""
    def __init__(self):
        self.using_fallback = False


# ===================================================================
# TEST 1: Model-first messages through REAL llm_client.generate()
# ===================================================================
print("\n" + "=" * 70)
print("TEST 1: Model-first messages through llm_client.generate()")
print("        (calls _build_contents internally -- not hand-rolled)")
print("=" * 70)

system_prompt = (
    "You are a senior technical interviewer. Evaluate the candidate's answer "
    "about Docker containerization. Respond as JSON with the exact schema provided."
)

# Simulate the sliding-window-after-Q1 case: conversation opens on model-role
messages_model_first = [
    {"role": "model",  "content": "Tell me about your experience with Docker."},
    {"role": "user",   "content": "I used Docker to containerize a Flask app. I wrote Dockerfiles and used docker-compose."},
]

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

session = FakeSession()

try:
    result = llm_client.generate(
        system_prompt=system_prompt,
        messages=messages_model_first,
        response_schema=TURN_RESPONSE_SCHEMA,
        session=session,
    )
    print(f"\n[PASS] TEST 1: Call through real llm_client.generate() succeeded.")
    print(f"  Content ordering guard ran inside _build_contents (not hand-rolled).")
    print(f"  No 400 about content ordering.")
    print(f"\n[PASS] TEST 2: Plain-dict schema accepted by response_schema.")
    print(f"  Schema had string 'type': 'OBJECT' -- no types.Schema conversion needed.")
    print(f"\nReturned dict: {json.dumps(result, indent=2)}")
    results["test1"] = True
    results["test2"] = True
except Exception as e:
    print(f"\n[FAIL] {type(e).__name__}: {e}")
    traceback.print_exc()
    results["test1"] = False
    results["test2"] = False
    sys.exit(1)

# ===================================================================
# TEST 3: JSON shape validation
# ===================================================================
print("\n" + "=" * 70)
print("TEST 3: Schema shape validation on returned dict")
print("=" * 70)

try:
    assert isinstance(result, dict), f"Expected dict, got {type(result)}"
    assert "evaluation" in result, "Missing 'evaluation'"
    assert "decision" in result, "Missing 'decision'"
    assert "reply" in result, "Missing 'reply'"

    ev = result["evaluation"]
    assert "bucket" in ev, "Missing evaluation.bucket"
    assert "rationale" in ev, "Missing evaluation.rationale"
    assert ev["bucket"] in ("missed", "partial", "strong"), f"Bad bucket: {ev['bucket']}"
    assert result["decision"] in ("follow_up", "advance"), f"Bad decision: {result['decision']}"
    assert isinstance(result["reply"], str) and len(result["reply"]) > 0

    print(f"[PASS] Schema shape matches perfectly.")
    print(f"  evaluation.bucket   = {ev['bucket']}")
    print(f"  evaluation.rationale = {ev['rationale'][:120]}")
    print(f"  decision            = {result['decision']}")
    print(f"  reply               = {result['reply'][:120]}")
    results["test3"] = True
except AssertionError as e:
    print(f"[FAIL] Shape mismatch: {e}")
    results["test3"] = False
    sys.exit(1)

# ===================================================================
# TEST 4: Empty messages through REAL llm_client.generate()
# ===================================================================
print("\n" + "=" * 70)
print("TEST 4: Empty messages (Q1 opener) through llm_client.generate()")
print("=" * 70)

FIRST_QUESTION_SCHEMA = {
    "type": "OBJECT",
    "properties": {"reply": {"type": "STRING"}},
    "required": ["reply"],
}

session2 = FakeSession()
try:
    result2 = llm_client.generate(
        system_prompt="You are a technical interviewer. Welcome the candidate and ask about Docker. JSON only.",
        messages=[],
        response_schema=FIRST_QUESTION_SCHEMA,
        session=session2,
    )
    assert "reply" in result2 and isinstance(result2["reply"], str)
    print(f"[PASS] Empty-messages works through real generate().")
    print(f"  reply = {result2['reply'][:120]}")
    results["test4"] = True
except Exception as e:
    print(f"[FAIL] {type(e).__name__}: {e}")
    results["test4"] = False

# ===================================================================
# TEST 5: Sticky fallback (Decision #23) -- MOCKED, zero quota burn
# ===================================================================
print("\n" + "=" * 70)
print("TEST 5: Sticky fallback via mock (no real API call)")
print("        Verifies: 429 on primary -> using_fallback=True ->")
print("        next call uses FALLBACK_MODEL string, not PRIMARY_MODEL")
print("=" * 70)

# First, verify we can construct the error correctly
print("\n  Pre-check: APIError construction...")
test_err = APIError(429, {"error": {"code": 429, "message": "test"}})
print(f"    APIError(429, ...).code = {test_err.code}")
print(f"    isinstance(test_err, APIError) = {isinstance(test_err, APIError)}")
assert test_err.code == 429, f"Expected .code=429, got {test_err.code}"
assert isinstance(test_err, APIError)
print(f"    Pre-check passed.\n")

mock_response = MagicMock()
mock_response.text = json.dumps({
    "evaluation": {"bucket": "partial", "rationale": "Mock rationale"},
    "decision": "advance",
    "reply": "Mock reply from fallback model.",
})

call_log = []

def mock_generate_content(*, model, contents, config):
    """First call to PRIMARY raises 429. All other calls succeed."""
    call_log.append(model)
    if model == llm_client.PRIMARY_MODEL and len(call_log) == 1:
        # Simulate quota exhaustion on primary — uses correct constructor
        raise APIError(429, {
            "error": {
                "code": 429,
                "message": "RESOURCE_EXHAUSTED",
                "status": "RESOURCE_EXHAUSTED",
            }
        })
    return mock_response

session3 = FakeSession()
assert session3.using_fallback is False, "Precondition: starts as False"

# Patch the actual client instance's generate_content method
original_generate = llm_client._client.client.models.generate_content
llm_client._client.client.models.generate_content = mock_generate_content

try:
    result3 = llm_client.generate(
        system_prompt="test",
        messages=[{"role": "user", "content": "test"}],
        response_schema={"type": "OBJECT", "properties": {"reply": {"type": "STRING"}}, "required": ["reply"]},
        session=session3,
    )

    # Verify: using_fallback flipped to True
    assert session3.using_fallback is True, \
        f"using_fallback should be True after 429, got {session3.using_fallback}"

    # Verify: the fallback call actually used FALLBACK_MODEL
    assert llm_client.FALLBACK_MODEL in call_log, \
        f"Expected {llm_client.FALLBACK_MODEL} in call log, got {call_log}"

    # Verify: primary was tried first
    assert call_log[0] == llm_client.PRIMARY_MODEL, \
        f"First call should be primary ({llm_client.PRIMARY_MODEL}), got {call_log[0]}"

    # Verify: result came back successfully
    assert result3["reply"] == "Mock reply from fallback model."

    print(f"[PASS] Sticky fallback verified!")
    print(f"  Call log: {call_log}")
    print(f"  session.using_fallback = {session3.using_fallback}")
    print(f"  1st call: {call_log[0]} (PRIMARY -- raised 429)")
    print(f"  2nd call: {call_log[1]} (FALLBACK -- succeeded)")

    # BONUS: verify stickiness -- next call should go DIRECTLY to fallback
    call_log.clear()
    session3_b = FakeSession()
    session3_b.using_fallback = True   # already sticky from prior 429

    result3b = llm_client.generate(
        system_prompt="test",
        messages=[{"role": "user", "content": "test"}],
        response_schema={"type": "OBJECT", "properties": {"reply": {"type": "STRING"}}, "required": ["reply"]},
        session=session3_b,
    )
    assert call_log[0] == llm_client.FALLBACK_MODEL, \
        f"Sticky session should skip primary, got {call_log[0]}"
    print(f"\n  Stickiness confirmed: with using_fallback=True, went directly to")
    print(f"  {call_log[0]} without trying primary.")

    results["test5"] = True

except Exception as e:
    print(f"[FAIL] Fallback test failed: {type(e).__name__}: {e}")
    traceback.print_exc()
    results["test5"] = False
finally:
    llm_client._client.client.models.generate_content = original_generate

# ===================================================================
# SUMMARY
# ===================================================================
print("\n" + "=" * 70)
print("VERIFICATION SUMMARY")
print("=" * 70)

all_passed = True
for name, label in [
    ("test1", "TEST 1: Model-first messages through REAL llm_client.generate()"),
    ("test2", "TEST 2: Plain-dict schema accepted directly by response_schema"),
    ("test3", "TEST 3: Response deserializes to correct {evaluation, decision, reply} shape"),
    ("test4", "TEST 4: Empty messages through REAL llm_client.generate()"),
    ("test5", "TEST 5: Sticky fallback: 429 -> using_fallback=True -> FALLBACK_MODEL"),
]:
    status = "[PASS]" if results.get(name) else "[FAIL]"
    if not results.get(name):
        all_passed = False
    print(f"{status} {label}")

print()
if all_passed:
    print("CONCLUSION: All llm_client.py assumptions VERIFIED.")
    print("            Content guards, schema handling, and fallback logic all confirmed.")
else:
    failed = [k for k, v in results.items() if not v]
    print(f"CONCLUSION: {len(failed)} test(s) FAILED: {failed}")
    print("            DO NOT proceed until failures are resolved.")
    sys.exit(1)
