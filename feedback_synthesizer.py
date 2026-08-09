"""
Feedback Synthesizer module (Component 5.6, Phase 4).
Synthesizes overall candidate interview feedback summary, strengths, gaps, and next steps.
"""

from models import FeedbackResponse
import prompts
import llm_client

FEEDBACK_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "summary": {"type": "STRING"},
        "strengths": {"type": "ARRAY", "items": {"type": "STRING"}},
        "gaps": {"type": "ARRAY", "items": {"type": "STRING"}},
        "next": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["summary", "strengths", "gaps", "next"],
}


def generate(session) -> FeedbackResponse:
    eval_text = "\n".join(
        f"Q{i} (Day {e.covered_day} — {e.covered_title}): {e.bucket.upper()} — {e.rationale}"
        for i, e in enumerate(session.evaluations, 1)
    )
    system_prompt = prompts.build_feedback_prompt(session.candidate, eval_text)

    try:
        result = llm_client.generate(
            system_prompt=system_prompt, messages=[],
            response_schema=FEEDBACK_SCHEMA, session=session,
        )
        return FeedbackResponse(**result)
    except llm_client.LLMCallError:
        return _deterministic_fallback(session)


def _deterministic_fallback(session) -> FeedbackResponse:
    """`done: true` must NEVER be returned without valid feedback. If Gemini
    fails on the final synthesis call, build feedback straight from the
    accumulated per-turn evaluations instead."""
    strengths = [f"Day {e.covered_day} — {e.covered_title}: {e.rationale}"
                 for e in session.evaluations if e.bucket == "strong"]
    gaps = [f"Day {e.covered_day} — {e.covered_title}: {e.rationale}"
            for e in session.evaluations if e.bucket == "missed"]
    partials = [f"Day {e.covered_day} — {e.covered_title}: {e.rationale}"
                for e in session.evaluations if e.bucket == "partial"]

    total = len(session.evaluations)
    return FeedbackResponse(
        summary=(f"Interview covered {total} questions across "
                 f"{len(session.covered_days)} curriculum days. "
                 f"{len(strengths)} strong responses, {len(gaps)} gaps identified."),
        strengths=strengths[:5] or ["Completed the full interview process."],
        gaps=gaps[:4] or partials[:4] or ["No critical gaps identified."],
        next=[f"Review Day {e.covered_day} — {e.covered_title} objectives"
              for e in session.evaluations if e.bucket in ("missed", "partial")][:4]
             or ["Continue practicing with mock interviews."],
    )
