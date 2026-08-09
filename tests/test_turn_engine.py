"""
Tests for Turn Engine (Component 5.5) and Feedback Synthesizer (Component 5.6).
Verifies all requirements in §7 of AI-Interview-Agent-Implementation-Plan-FINAL.md.
"""

import json
from unittest.mock import patch, MagicMock
import pytest
from google.genai.errors import APIError

from models import (
    CandidateProfile,
    SessionState,
    FeedbackResponse,
    InterviewResponse,
)
import planner
import turn_engine
import feedback_synthesizer
import llm_client


@pytest.fixture
def curriculum_data():
    with open("curriculum.json") as f:
        return json.load(f)


@pytest.fixture
def sample_candidate():
    with open("candidates.json") as f:
        raw = json.load(f)["candidates"]
    return CandidateProfile(**raw[0])  # CAND-001 Sarah Johnson


@pytest.fixture
def sample_session(sample_candidate, curriculum_data):
    plan, tone = planner.build_plan(sample_candidate, curriculum_data)
    return SessionState(
        session_id="test-session-123",
        candidate=sample_candidate,
        plan=plan,
        candidate_tone=tone,
    )


def test_follow_up_cap_enforced(sample_session):
    """
    Verifies that a 2nd follow_up decision from the LLM on the same topic
    gets overridden to 'advance' (Decision #18, #19).
    """
    mock_turn1 = {
        "evaluation": {"bucket": "partial", "rationale": "Okay answer."},
        "decision": "follow_up",
        "reply": "Can you elaborate on your observation logic?",
    }
    mock_turn2 = {
        "evaluation": {"bucket": "strong", "rationale": "Much clearer now."},
        "decision": "follow_up",  # LLM tries to ask a 2nd follow-up
        "reply": "What about edge cases?",
    }

    with patch("llm_client.generate", side_effect=[mock_turn1, mock_turn2]):
        # Turn 1
        res1 = turn_engine.process_turn(sample_session, "I used custom logs.")
        assert res1.done is False
        assert sample_session.current_topic_followups == 1
        assert sample_session.current_topic_index == 0

        # Turn 2: LLM returned 'follow_up', but cap (>=1) forces decision to 'advance'
        res2 = turn_engine.process_turn(sample_session, "Added metrics too.")
        assert res2.done is False
        assert sample_session.current_topic_followups == 0
        assert sample_session.current_topic_index == 1


def test_decision_override_advances_index(sample_session):
    """
    Explicitly verifies that current_topic_index advances when follow-up cap override occurs.
    Catches the silent infinite-loop bug from an earlier design draft.
    """
    sample_session.current_topic_followups = 1  # already had 1 follow-up
    initial_index = sample_session.current_topic_index

    mock_llm = {
        "evaluation": {"bucket": "strong", "rationale": "Good details."},
        "decision": "follow_up",  # LLM requests follow-up again
        "reply": "One more thing...",
    }

    with patch("llm_client.generate", return_value=mock_llm):
        turn_engine.process_turn(sample_session, "Answer after follow-up.")

        # Index MUST increment to initial_index + 1
        assert sample_session.current_topic_index == initial_index + 1
        assert sample_session.current_topic_followups == 0


def test_llm_failure_graceful_degrade(sample_session):
    """
    Verifies that a mock LLMCallError leads to deterministic reply + forced advance,
    without raising an unhandled exception.
    """
    current_topic_title = sample_session.plan[0].title
    next_topic_title = sample_session.plan[1].title

    with patch("llm_client.generate", side_effect=llm_client.LLMCallError("API Timeout")):
        res = turn_engine.process_turn(sample_session, "Here is my response.")

        assert res.done is False
        assert f"Thank you for your thoughts on {current_topic_title}." in res.reply
        assert f"Regarding {next_topic_title}" in res.reply
        assert sample_session.current_topic_index == 1
        assert len(sample_session.evaluations) == 1
        assert sample_session.evaluations[0].bucket == "partial"
        assert sample_session.evaluations[0].rationale == "Technical issue — moved to next topic."


def test_completion_discards_llm_reply(sample_session):
    """
    Verifies that on done: true, the returned reply is the deterministic closing line,
    never the LLM's raw output (Decision #13).
    """
    sample_session.questions_asked = 7
    sample_session.covered_days = {1, 2, 3, 4}

    mock_turn = {
        "evaluation": {"bucket": "strong", "rationale": "Excellent answer."},
        "decision": "advance",
        "reply": "DISCARDED LLM REPLY: Now moving on to Day 99...",
    }

    mock_feedback = FeedbackResponse(
        summary="Solid performance overall.",
        strengths=["Day 1 — Env: Good tooling setup."],
        gaps=["Day 29 — Monitoring: Skipped mission."],
        next=["Review Day 29 objectives."],
    )

    with patch("llm_client.generate", return_value=mock_turn), \
         patch("feedback_synthesizer.generate", return_value=mock_feedback):

        res = turn_engine.process_turn(sample_session, "Final question answer.")

        assert res.done is True
        assert res.feedback == mock_feedback
        assert "DISCARDED LLM REPLY" not in res.reply
        expected_closing = (
            f"Thank you, {sample_session.candidate.member.name} — that wraps up your interview. "
            f"I appreciate you walking me through your experience with the AI cohort. Here's your feedback."
        )
        assert res.reply == expected_closing


def test_sliding_window_resets_on_advance(sample_session):
    """
    Verifies that current_topic_history is reset immediately after an advance,
    and then contains only the new question.
    """
    # Generate first question
    with patch("llm_client.generate", return_value={"reply": "Welcome! Question 1?"}):
        turn_engine.generate_first_question(sample_session)

    assert len(sample_session.current_topic_history) == 1

    # Now candidate answers and LLM advances
    mock_turn = {
        "evaluation": {"bucket": "strong", "rationale": "Good answer."},
        "decision": "advance",
        "reply": "Great. Question 2 for next topic?",
    }

    with patch("llm_client.generate", return_value=mock_turn):
        turn_engine.process_turn(sample_session, "Answer to Q1.")

        # After advance, topic history should reset and contain ONLY the assistant reply for Q2
        assert len(sample_session.current_topic_history) == 1
        assert sample_session.current_topic_history[0]["role"] == "assistant"
        assert sample_session.current_topic_history[0]["content"] == "Great. Question 2 for next topic?"


def test_fallback_sticky(sample_session):
    """
    Verifies that a simulated 429 once sets using_fallback=True,
    and stays True on subsequent calls without re-attempting primary.
    """
    client = llm_client.LLMClient(api_key="fake-key")

    mock_resp = MagicMock()
    mock_resp.text = '{"reply": "Fallback response"}'

    error_429 = APIError(429, {"error": {"code": 429, "message": "RESOURCE_EXHAUSTED"}})

    with patch("google.genai.models.Models.generate_content") as mock_gen:
        mock_gen.side_effect = [error_429, mock_resp]

        assert sample_session.using_fallback is False

        res = client.generate(
            system_prompt="sys",
            messages=[],
            response_schema={"type": "OBJECT"},
            session=sample_session,
        )

        assert res == {"reply": "Fallback response"}
        assert sample_session.using_fallback is True

        # Second call on same session directly uses fallback model
        mock_gen.reset_mock()
        mock_gen.side_effect = None
        mock_gen.return_value = mock_resp

        res2 = client.generate(
            system_prompt="sys",
            messages=[],
            response_schema={"type": "OBJECT"},
            session=sample_session,
        )
        assert res2 == {"reply": "Fallback response"}
        assert mock_gen.call_count == 1
        call_kwargs = mock_gen.call_args.kwargs
        assert call_kwargs["model"] == llm_client.FALLBACK_MODEL


def test_both_models_exhausted_raises_llm_call_error(sample_session):
    """
    Verifies that when primary raises 429 AND fallback raises 429,
    llm_client.generate cleanly raises LLMCallError('Both models exhausted...').
    Traces exact 2-call sequence: Primary (429) -> Fallback (429) fail-fast.
    """
    client = llm_client.LLMClient(api_key="fake-key")

    primary_error = APIError(429, {"error": {"code": 429, "message": "Primary 429"}})
    fallback_error = APIError(429, {"error": {"code": 429, "message": "Fallback 429"}})

    with patch("google.genai.models.Models.generate_content") as mock_gen:
        # Requires 2 side effects: Primary call + Fallback call (fails fast)
        mock_gen.side_effect = [primary_error, fallback_error]

        with pytest.raises(llm_client.LLMCallError) as exc_info:
            client.generate(
                system_prompt="sys",
                messages=[],
                response_schema={"type": "OBJECT"},
                session=sample_session,
            )

        assert "Both models exhausted" in str(exc_info.value)
        assert sample_session.using_fallback is True
        assert mock_gen.call_count == 2

        # Confirm call model sequence: Primary -> Fallback (fails fast, 2 calls)
        models_called = [call.kwargs["model"] for call in mock_gen.call_args_list]
        assert models_called == [
            llm_client.PRIMARY_MODEL,
            llm_client.FALLBACK_MODEL,
        ]


def test_generate_first_question_fallback(sample_session):
    """
    Verifies generate_first_question fallback when LLMCallError occurs.
    """
    with patch("llm_client.generate", side_effect=llm_client.LLMCallError("Quota error")):
        reply = turn_engine.generate_first_question(sample_session)
        name = sample_session.candidate.member.name
        first_topic = sample_session.plan[0]
        assert f"Welcome {name}!" in reply
        assert f"Day {first_topic.day}" in reply
        assert sample_session.questions_asked == 1
        assert first_topic.day in sample_session.covered_days


def test_feedback_synthesizer_fallback(sample_session):
    """
    Verifies deterministic feedback fallback when LLM synthesis fails.
    """
    sample_session.evaluations = [
        turn_engine.TurnEvaluation(
            bucket="strong", rationale="Great job", covered_day=1, covered_title="Env Setup"
        ),
        turn_engine.TurnEvaluation(
            bucket="missed", rationale="Skipped concept", covered_day=29, covered_title="Logging"
        ),
        turn_engine.TurnEvaluation(
            bucket="partial", rationale="Needed hint", covered_day=10, covered_title="Prompting"
        ),
    ]
    sample_session.covered_days = {1, 29, 10}

    with patch("llm_client.generate", side_effect=llm_client.LLMCallError("Synthesis error")):
        fb = feedback_synthesizer.generate(sample_session)
        assert isinstance(fb, FeedbackResponse)
        assert "Interview covered 3 questions" in fb.summary
        assert "Day 1 — Env Setup: Great job" in fb.strengths[0]
        assert "Day 29 — Logging: Skipped concept" in fb.gaps[0]
        assert "Review Day 29 — Logging objectives" in fb.next[0]


def test_feedback_synthesizer_fallback_empty_buckets(sample_session):
    """
    Verifies that _deterministic_fallback returns non-empty strengths, gaps, and next
    even when strong or missed/partial buckets are completely empty.
    """
    # Case 1: All strong evaluations (0 missed, 0 partial)
    sample_session.evaluations = [
        turn_engine.TurnEvaluation(
            bucket="strong", rationale="Perfect", covered_day=1, covered_title="Topic 1"
        )
    ]
    sample_session.covered_days = {1}

    with patch("llm_client.generate", side_effect=llm_client.LLMCallError("Error")):
        fb_perfect = feedback_synthesizer.generate(sample_session)
        assert len(fb_perfect.strengths) == 1
        assert "Day 1 — Topic 1: Perfect" in fb_perfect.strengths[0]
        assert fb_perfect.gaps == ["No critical gaps identified."]
        assert fb_perfect.next == ["Continue practicing with mock interviews."]

    # Case 2: All missed evaluations (0 strong, 0 partial)
    sample_session.evaluations = [
        turn_engine.TurnEvaluation(
            bucket="missed", rationale="Struggled", covered_day=2, covered_title="Topic 2"
        )
    ]
    sample_session.covered_days = {2}

    with patch("llm_client.generate", side_effect=llm_client.LLMCallError("Error")):
        fb_struggling = feedback_synthesizer.generate(sample_session)
        assert fb_struggling.strengths == ["Completed the full interview process."]
        assert len(fb_struggling.gaps) == 1
        assert "Day 2 — Topic 2: Struggled" in fb_struggling.gaps[0]
        assert len(fb_struggling.next) == 1
        assert "Review Day 2 — Topic 2 objectives" in fb_struggling.next[0]

