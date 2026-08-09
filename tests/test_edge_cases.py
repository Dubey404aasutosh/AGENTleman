"""
Tests for edge cases (§7 test_edge_cases.py table).

Tests:
  - test_unknown_session_400
  - test_empty_body_400
  - test_resend_candidate_resets
  - test_turn_after_done_400
  - test_long_answer
  - test_error_response_is_dict
  - test_malformed_body_422_observation (flagged, not fixed — see docstring)
"""

import json
import os
import pytest
from unittest.mock import patch

# Ensure GEMINI_API_KEY is available for lifespan init
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
os.environ.setdefault("GEMINI_API_KEY", "test-key-fake")

from fastapi.testclient import TestClient
from main import app
import session_store


# ── Mock LLM helper ──────────────────────────────────────────────────────────

def _mock_llm_generate(system_prompt, messages, response_schema, session):
    """Standard mock for edge case tests — always advances, no follow-ups."""
    props = response_schema.get("properties", {})
    if "summary" in props:
        return {
            "summary": "Interview summary.",
            "strengths": ["Day 1 — Environment Setup: Good."],
            "gaps": ["Day 29 — Monitoring: Gap identified."],
            "next": ["Review Day 29 objectives."],
        }
    if "evaluation" in props:
        return {
            "evaluation": {"bucket": "strong", "rationale": "Good answer."},
            "decision": "advance",
            "reply": "Great. Moving to the next topic.",
        }
    return {"reply": "Welcome! Let's start your interview. First question here."}


def _run_to_completion(client, candidate_data, session_id):
    """Run a full interview to done=True. Returns the final response."""
    with patch("llm_client.generate", side_effect=_mock_llm_generate):
        r = client.post("/api/interview", json={
            "sessionId": session_id,
            "candidate": candidate_data,
        })
        assert r.status_code == 200

        for i in range(20):  # safety cap
            s = session_store.get(session_id)
            if s and s.is_done:
                return r.json()
            r = client.post("/api/interview", json={
                "sessionId": session_id,
                "message": f"Answer {i + 1}.",
            })
            assert r.status_code == 200

    return r.json()


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_sessions():
    """Reset session store between tests."""
    session_store._store._data.clear()
    yield
    session_store._store._data.clear()


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def all_candidates():
    with open("candidates.json") as f:
        raw = json.load(f)["candidates"]
    return {c["member"]["id"]: c for c in raw}


# ── Tests ────────────────────────────────────────────────────────────────────

def test_unknown_session_400(client):
    """Clean dict-based 400 for unknown session, not 500."""
    r = client.post("/api/interview", json={
        "sessionId": "nonexistent-session",
        "message": "Hello",
    })
    assert r.status_code == 400
    data = r.json()
    assert isinstance(data, dict)
    assert data["error"] == "INVALID_SESSION"
    assert "detail" in data


def test_empty_body_400(client):
    """Clean dict-based 400 for request with only sessionId (neither candidate nor message)."""
    r = client.post("/api/interview", json={
        "sessionId": "empty-body-test",
    })
    assert r.status_code == 400
    data = r.json()
    assert isinstance(data, dict)
    assert data["error"] == "BAD_REQUEST"
    assert "detail" in data


def test_resend_candidate_resets(client, all_candidates):
    """Same sessionId + new candidate -> session is fully replaced, not merged
    with stale state from the old session."""
    with patch("llm_client.generate", side_effect=_mock_llm_generate):
        # Start with CAND-001
        r1 = client.post("/api/interview", json={
            "sessionId": "reset-test",
            "candidate": all_candidates["CAND-001"],
        })
        assert r1.status_code == 200

        # Do a turn to advance state
        r2 = client.post("/api/interview", json={
            "sessionId": "reset-test",
            "message": "My answer for CAND-001.",
        })
        assert r2.status_code == 200

        # Verify session has CAND-001 and accumulated state
        session_before = session_store.get("reset-test")
        assert session_before is not None
        assert session_before.candidate.member.id == "CAND-001"
        assert session_before.questions_asked >= 2  # start (1) + turn (1)
        assert len(session_before.evaluations) >= 1

        # Now resend with CAND-003 on same sessionId → should reset
        r3 = client.post("/api/interview", json={
            "sessionId": "reset-test",
            "candidate": all_candidates["CAND-003"],
        })
        assert r3.status_code == 200

    # Verify session is fully replaced
    session_after = session_store.get("reset-test")
    assert session_after is not None
    assert session_after.candidate.member.id == "CAND-003", (
        f"Expected CAND-003, got {session_after.candidate.member.id}"
    )
    assert session_after.questions_asked == 1, (
        f"Expected fresh start (questions_asked=1), got {session_after.questions_asked}"
    )
    assert len(session_after.evaluations) == 0, (
        f"Expected 0 evaluations after reset, got {len(session_after.evaluations)}"
    )
    assert len(session_after.turn_history) == 1, (
        "Turn history should contain only the first question after reset"
    )


def test_turn_after_done_400(client, all_candidates):
    """Message sent after done:true -> clean 400, not a 500 or silently continued."""
    # Run interview to completion
    _run_to_completion(client, all_candidates["CAND-001"], session_id="done-test")

    # Confirm the session IS done
    session = session_store.get("done-test")
    assert session is not None
    assert session.is_done is True

    # Now send another message → should get clean 400
    r = client.post("/api/interview", json={
        "sessionId": "done-test",
        "message": "One more thing...",
    })
    assert r.status_code == 400, (
        f"Expected 400 after done, got {r.status_code}: {r.text}"
    )
    data = r.json()
    assert data["error"] == "SESSION_COMPLETE"
    assert "detail" in data


def test_long_answer(client, all_candidates):
    """2000-char answer → valid response, no crash."""
    with patch("llm_client.generate", side_effect=_mock_llm_generate):
        r = client.post("/api/interview", json={
            "sessionId": "long-answer-test",
            "candidate": all_candidates["CAND-001"],
        })
        assert r.status_code == 200

        long_message = "I have extensive experience with this topic. " * 50  # ~2350 chars
        assert len(long_message) >= 2000

        r = client.post("/api/interview", json={
            "sessionId": "long-answer-test",
            "message": long_message,
        })
        assert r.status_code == 200
        data = r.json()
        assert "reply" in data
        assert "done" in data


def test_error_response_is_dict(client):
    """Error body is {error, detail} dict, not double-encoded JSON string.
    Verifies Decision #25: HTTPException(detail={...}) as a real dict;
    custom exception handler returns it directly."""
    # Trigger an error (unknown session)
    r = client.post("/api/interview", json={
        "sessionId": "no-such-session",
        "message": "Hello",
    })
    assert r.status_code == 400
    data = r.json()

    # Must be a real dict with the expected keys
    assert isinstance(data, dict), f"Response body is not a dict: {type(data)}"
    assert "error" in data, f"Missing 'error' key in response: {data}"
    assert "detail" in data, f"Missing 'detail' key in response: {data}"

    # The 'detail' value must be a plain string, NOT a JSON-encoded string
    assert isinstance(data["detail"], str), (
        f"'detail' should be a string, got {type(data['detail'])}"
    )
    # Double-encoding check: if detail parses as JSON dict, that's wrong
    try:
        parsed = json.loads(data["detail"])
        if isinstance(parsed, dict):
            pytest.fail(
                f"'detail' is double-encoded JSON (string containing a JSON dict): "
                f"{data['detail']}"
            )
    except (json.JSONDecodeError, TypeError):
        pass  # Good — it's a plain string, not JSON


def test_malformed_body_validation_handler(client):
    """Verifies that missing required schema fields trigger our custom RequestValidationError
    handler, returning clean 400 {error, detail} dicts rather than default FastAPI error lists.
    """
    # Case 1: Missing required sessionId field
    r = client.post("/api/interview", json={"message": "hello"})
    assert r.status_code == 400, f"Expected 400, got {r.status_code}"
    data = r.json()

    assert isinstance(data, dict)
    assert data["error"] == "BAD_REQUEST"
    assert "detail" in data
    assert isinstance(data["detail"], str)

    # Case 2: Completely invalid JSON body
    r2 = client.post(
        "/api/interview",
        content="this is not json",
        headers={"Content-Type": "application/json"},
    )
    assert r2.status_code == 400
    data2 = r2.json()
    assert isinstance(data2, dict)
    assert data2["error"] == "BAD_REQUEST"


def test_value_error_500_handler(client, all_candidates):
    """Verifies that an unhandled ValueError raised in route handler
    (e.g., from planner invariant check) is caught by value_error_handler
    and returns a clean 500 {error: 'INTERNAL_ERROR', detail: ...} dict."""
    with patch("planner.build_plan", side_effect=ValueError("Planner invariant failed: insufficient topics")):
        r = client.post("/api/interview", json={
            "sessionId": "value-error-test",
            "candidate": all_candidates["CAND-001"],
        })
        assert r.status_code == 500, f"Expected 500, got {r.status_code}: {r.text}"
        data = r.json()
        assert isinstance(data, dict)
        assert data["error"] == "INTERNAL_ERROR"
        assert "insufficient topics" in data["detail"]
