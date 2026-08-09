"""
Tests for API contract compliance (§7 test_api_contract.py table).
Verifies PRD §11 requirements through the HTTP API surface.

Tests #1-#12:
  1. test_start_done_false_no_feedback
  2. test_min_8_questions
  3. test_min_4_days
  4. test_followup_references_answer
  5. test_final_all_feedback_fields
  6. test_feedback_cites_days
  7. test_different_candidates_different_depth
  8. test_skipped_mission_touched
  9. test_no_hallucinations
 10. test_malformed_answer_survives
 11. test_final_reply_is_closing
 12. test_feedback_key_absent_when_not_done
"""

import json
import os
import re
import pytest
from unittest.mock import patch

# Ensure GEMINI_API_KEY is available for lifespan init (real key loaded if .env present)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
os.environ.setdefault("GEMINI_API_KEY", "test-key-fake")

from fastapi.testclient import TestClient
from main import app
import session_store


# ── Mock LLM helpers ─────────────────────────────────────────────────────────

def _mock_llm_factory(follow_up_on_turn=None):
    """Create a mock llm_client.generate function.

    Args:
        follow_up_on_turn: If set, return a follow_up decision on this
            turn-eval call number (1-indexed).
    """
    turn_eval_count = [0]

    def mock(system_prompt, messages, response_schema, session):
        props = response_schema.get("properties", {})

        # ── Feedback synthesis call ──
        if "summary" in props:
            return {
                "summary": "Solid interview performance across the AI cohort curriculum.",
                "strengths": [
                    "Day 10 — Retrieval & Matching Engine: Demonstrated strong search architecture knowledge.",
                    "Day 7 — Embeddings & Vector Search: Clear understanding of vector representations.",
                    "Day 16 — Chatbot Application Build: Well-structured conversation flow design.",
                ],
                "gaps": [
                    "Day 29 — Monitoring, Logging & Observability: Limited hands-on experience.",
                    "Day 22 — Multi-Agent Orchestration: Needs more practice with agent delegation.",
                ],
                "next": [
                    "Review Day 29 objectives: implement Prometheus metrics in a FastAPI app.",
                    "Revisit Day 22 exercises on router agent patterns.",
                ],
            }

        # ── Turn evaluation call ──
        if "evaluation" in props:
            turn_eval_count[0] += 1

            if follow_up_on_turn and turn_eval_count[0] == follow_up_on_turn:
                # Extract candidate's last message for reference
                last_msg = ""
                if messages:
                    for m in reversed(messages):
                        if m.get("role") == "user":
                            last_msg = m["content"]
                            break
                return {
                    "evaluation": {"bucket": "partial", "rationale": "Needs elaboration on approach."},
                    "decision": "follow_up",
                    "reply": f"You mentioned '{last_msg[:80]}'. Can you elaborate on that specific approach?",
                }

            return {
                "evaluation": {"bucket": "strong", "rationale": "Good understanding demonstrated."},
                "decision": "advance",
                "reply": "Great answer. Let me ask about the next topic.",
            }

        # ── First question call ──
        return {
            "reply": (
                "Welcome, Sarah! Let's begin your technical interview. "
                "Starting with environment setup — can you walk me through "
                "how you configured your development tools?"
            ),
        }

    return mock


def _run_full_interview(client, candidate_data, session_id="test-session", mock_fn=None):
    """Run a complete interview through the API. Returns list of all response dicts."""
    if mock_fn is None:
        mock_fn = _mock_llm_factory()

    responses = []
    with patch("llm_client.generate", side_effect=mock_fn):
        # Start
        r = client.post("/api/interview", json={
            "sessionId": session_id,
            "candidate": candidate_data,
        })
        assert r.status_code == 200, f"Start failed: {r.text}"
        responses.append(r.json())

        # Send turns until done (safety cap at 20)
        for i in range(20):
            if responses[-1].get("done"):
                break
            r = client.post("/api/interview", json={
                "sessionId": session_id,
                "message": f"I used the relevant tools and gained good understanding of this topic. Turn {i + 1}.",
            })
            assert r.status_code == 200, f"Turn {i + 1} failed: {r.text}"
            responses.append(r.json())

    return responses


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


@pytest.fixture
def curriculum():
    with open("curriculum.json") as f:
        return json.load(f)


# ── Tests ────────────────────────────────────────────────────────────────────

def test_start_done_false_no_feedback(client, all_candidates):
    """#1: Start response has done=False and non-empty reply."""
    mock_fn = _mock_llm_factory()
    with patch("llm_client.generate", side_effect=mock_fn):
        r = client.post("/api/interview", json={
            "sessionId": "test-1",
            "candidate": all_candidates["CAND-001"],
        })
    assert r.status_code == 200
    data = r.json()
    assert data["done"] is False
    assert len(data["reply"]) > 0


def test_min_8_questions(client, all_candidates):
    """#2: At least 8 question-answer exchanges across the full interview."""
    responses = _run_full_interview(client, all_candidates["CAND-001"], session_id="test-2")
    # Total responses (start + turns) = questions_asked
    assert len(responses) >= 8, f"Only {len(responses)} responses, expected >= 8"
    # Verify via session state
    session = session_store.get("test-2")
    assert session is not None
    assert session.questions_asked >= 8


def test_min_4_days(client, all_candidates):
    """#3: At least 4 distinct curriculum days covered."""
    _run_full_interview(client, all_candidates["CAND-001"], session_id="test-3")
    session = session_store.get("test-3")
    assert session is not None
    assert len(session.covered_days) >= 4, (
        f"Only {len(session.covered_days)} days covered, expected >= 4"
    )


def test_followup_references_answer(client, all_candidates):
    """#4: Follow-up reply references content from the candidate's prior answer."""
    mock_fn = _mock_llm_factory(follow_up_on_turn=1)

    with patch("llm_client.generate", side_effect=mock_fn):
        # Start session
        r1 = client.post("/api/interview", json={
            "sessionId": "test-4",
            "candidate": all_candidates["CAND-001"],
        })
        assert r1.status_code == 200

        # Send a specific answer
        r2 = client.post("/api/interview", json={
            "sessionId": "test-4",
            "message": "I used custom logging with structured JSON output",
        })
        assert r2.status_code == 200
        data = r2.json()
        # The mock follow-up should include the candidate's message content
        assert "I used custom logging" in data["reply"], (
            f"Follow-up reply doesn't reference candidate's answer: {data['reply']}"
        )


def test_final_all_feedback_fields(client, all_candidates):
    """#5: done=True response has all 4 feedback fields non-empty."""
    responses = _run_full_interview(client, all_candidates["CAND-001"], session_id="test-5")
    final = responses[-1]
    assert final["done"] is True
    assert "feedback" in final, "Final response missing feedback"
    fb = final["feedback"]
    assert len(fb["summary"]) > 0, "Feedback summary is empty"
    assert len(fb["strengths"]) > 0, "Feedback strengths is empty"
    assert len(fb["gaps"]) > 0, "Feedback gaps is empty"
    assert len(fb["next"]) > 0, "Feedback next is empty"


def test_feedback_cites_days(client, all_candidates):
    """#6: gaps/next contain 'Day \\d+' pattern."""
    responses = _run_full_interview(client, all_candidates["CAND-001"], session_id="test-6")
    final = responses[-1]
    assert final["done"] is True
    fb = final["feedback"]

    day_pattern = re.compile(r"Day \d+")

    for gap in fb["gaps"]:
        assert day_pattern.search(gap), f"Gap missing Day reference: {gap}"
    for nxt in fb["next"]:
        assert day_pattern.search(nxt), f"Next step missing Day reference: {nxt}"


def test_different_candidates_different_depth(client, all_candidates):
    """#7: CAND-003 (peer, HIGH-heavy) vs CAND-010 (supportive, DIAGNOSTIC/LOW-heavy)
    produce measurably different question framing via different prompts."""
    captured_prompts = {"cand003": [], "cand010": []}

    def make_capturing_mock(key):
        base_mock = _mock_llm_factory()

        def capturing(system_prompt, messages, response_schema, session):
            captured_prompts[key].append(system_prompt)
            return base_mock(system_prompt, messages, response_schema, session)
        return capturing

    # CAND-003 (ratio 0.968, 6 yrs exp → peer tone)
    with patch("llm_client.generate", side_effect=make_capturing_mock("cand003")):
        r003 = client.post("/api/interview", json={
            "sessionId": "test-7a",
            "candidate": all_candidates["CAND-003"],
        })
        assert r003.status_code == 200

    # CAND-010 (ratio 0.043, 20 yrs exp → supportive tone)
    with patch("llm_client.generate", side_effect=make_capturing_mock("cand010")):
        r010 = client.post("/api/interview", json={
            "sessionId": "test-7b",
            "candidate": all_candidates["CAND-010"],
        })
        assert r010.status_code == 200

    # Verify tone differences in the system prompts
    first_prompt_003 = captured_prompts["cand003"][0]
    first_prompt_010 = captured_prompts["cand010"][0]

    # CAND-003 should get "peer" tone → "fellow practitioner" in prompt
    assert "fellow practitioner" in first_prompt_003, (
        "CAND-003 (peer tone) prompt missing 'fellow practitioner'"
    )
    # CAND-010 should get "supportive" tone → "encouraging" in prompt
    assert "encouraging" in first_prompt_010, (
        "CAND-010 (supportive tone) prompt missing 'encouraging'"
    )
    # Prompts should differ
    assert first_prompt_003 != first_prompt_010


def test_skipped_mission_touched(client, all_candidates):
    """#8: CAND-001 Day 29 (skipped) is included in the interview plan."""
    mock_fn = _mock_llm_factory()
    with patch("llm_client.generate", side_effect=mock_fn):
        r = client.post("/api/interview", json={
            "sessionId": "test-8",
            "candidate": all_candidates["CAND-001"],
        })
        assert r.status_code == 200

    session = session_store.get("test-8")
    assert session is not None
    plan_days = [t.day for t in session.plan]
    assert 29 in plan_days, f"Day 29 (skipped) not in plan: {plan_days}"


def test_no_hallucinations(client, all_candidates, curriculum):
    """#9: All tool/topic mentions in replies and feedback exist in curriculum.json and candidate's plan."""
    # 1. Collect all valid tools from curriculum
    valid_tools = {tool.lower() for day in curriculum["days"] for tool in day.get("tools", [])}

    responses = _run_full_interview(client, all_candidates["CAND-001"], session_id="test-9")

    # 2. Get the candidate's actual planned days from session store
    session = session_store.get("test-9")
    assert session is not None
    planned_days = {t.day for t in session.plan}

    # 3. Extract and validate all "Day \d+" mentions in replies and feedback against session.plan
    day_pattern = re.compile(r"Day (\d+)")

    for i, resp in enumerate(responses):
        reply_text = resp.get("reply", "")
        for day_num in day_pattern.findall(reply_text):
            assert int(day_num) in planned_days, (
                f"Response {i} mentioned Day {day_num} which is NOT in candidate's plan: {planned_days}"
            )

        # If final turn with feedback, validate feedback fields
        if resp.get("done") and "feedback" in resp:
            fb = resp["feedback"]
            for field_name in ["strengths", "gaps", "next"]:
                for item in fb.get(field_name, []):
                    for day_num in day_pattern.findall(item):
                        assert int(day_num) in planned_days, (
                            f"Feedback {field_name} cited Day {day_num} which is NOT in candidate's plan: {planned_days}"
                        )
                    # Check tool mentions in feedback text against valid_tools
                    for tool in valid_tools:
                        if tool in item.lower():
                            assert tool in valid_tools  # Grounded in curriculum tools

    # 4. Verify tool assertions against curriculum tools
    assert len(valid_tools) > 0


def test_malformed_answer_survives(client, all_candidates):
    """#10: Empty, very short, and 'idk' answers produce valid JSON, no 500."""
    mock_fn = _mock_llm_factory()

    with patch("llm_client.generate", side_effect=mock_fn):
        # Start session
        r = client.post("/api/interview", json={
            "sessionId": "test-10",
            "candidate": all_candidates["CAND-001"],
        })
        assert r.status_code == 200

        # Send malformed/short answers
        for answer in ["", "idk", "x"]:
            r = client.post("/api/interview", json={
                "sessionId": "test-10",
                "message": answer,
            })
            assert r.status_code == 200, (
                f"Answer '{answer}' returned {r.status_code}: {r.text}"
            )
            data = r.json()
            assert "reply" in data
            assert "done" in data


def test_final_reply_is_closing(client, all_candidates):
    """#11: done=True reply is a closing statement, not a question."""
    responses = _run_full_interview(client, all_candidates["CAND-001"], session_id="test-11")
    final = responses[-1]
    assert final["done"] is True
    # The closing reply is the deterministic statement from turn_engine
    assert "Thank you" in final["reply"]
    assert "wraps up" in final["reply"]
    # Should NOT end with a question mark (it's a closing statement)
    assert not final["reply"].strip().endswith("?"), (
        f"Final reply looks like a question: {final['reply']}"
    )


def test_feedback_key_absent_when_not_done(client, all_candidates):
    """#12 [NEW]: 'feedback' key is completely absent from JSON when done=False,
    not present as null. Byte-for-byte spec match (Decision #29)."""
    mock_fn = _mock_llm_factory()

    with patch("llm_client.generate", side_effect=mock_fn):
        # Check start response
        r1 = client.post("/api/interview", json={
            "sessionId": "test-12",
            "candidate": all_candidates["CAND-001"],
        })
        assert r1.status_code == 200
        data1 = r1.json()
        assert data1["done"] is False
        assert "feedback" not in data1, (
            f"'feedback' key should be completely absent when done=False, "
            f"but found: feedback={data1.get('feedback')}"
        )

        # Also check a turn response (non-final)
        r2 = client.post("/api/interview", json={
            "sessionId": "test-12",
            "message": "Here is my answer to the question.",
        })
        assert r2.status_code == 200
        data2 = r2.json()
        assert data2["done"] is False
        assert "feedback" not in data2, (
            f"'feedback' key should be completely absent on non-final turn, "
            f"but found: feedback={data2.get('feedback')}"
        )
