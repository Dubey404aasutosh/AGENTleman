import re
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
        result = _fix_hallucinated_day_titles(result, session)
        return FeedbackResponse(**result)
    except llm_client.LLMCallError as exc:
        print(f"[LLM_FALLBACK_WARNING] Candidate={session.candidate.member.id} in feedback_synthesizer: {exc}")
        return _deterministic_fallback(session)


def _fix_hallucinated_day_titles(result: dict, session) -> dict:
    """Corrects any day titles in strengths/gaps/next to match official curriculum titles."""
    day_titles = {t.day: t.title for t in session.plan}
    for e in session.evaluations:
        day_titles[e.covered_day] = e.covered_title

    for field in ("strengths", "gaps", "next"):
        if field not in result or not isinstance(result[field], list):
            continue
        fixed_list = []
        for item in result[field]:
            if isinstance(item, str):
                match = re.search(r"Day\s+(\d+)\s*[\u2014\-:]\s*([^:]+)(:.*)?", item, re.IGNORECASE)
                if match:
                    day_num = int(match.group(1))
                    found_title = match.group(2).strip()
                    rest = match.group(3) or ""
                    if day_num in day_titles:
                        official_title = day_titles[day_num]
                        if found_title != official_title:
                            item = re.sub(
                                r"Day\s+" + str(day_num) + r"\s*[\u2014\-:]\s*" + re.escape(found_title),
                                f"Day {day_num} — {official_title}",
                                item,
                                flags=re.IGNORECASE
                            )
            fixed_list.append(item)
        result[field] = fixed_list
    return result


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

    final_strengths = strengths[:5] or ["Completed the full interview process."]
    final_gaps = gaps[:4] or partials[:4] or ["No critical gaps identified."]
    final_next = [f"Review Day {e.covered_day} — {e.covered_title} objectives"
                  for e in session.evaluations if e.bucket in ("missed", "partial")][:4] \
                 or ["Continue practicing with mock interviews."]

    num_strong = len(strengths[:5])
    num_gaps = len(gaps[:4]) if gaps else (len(partials[:4]) if partials else 0)

    total = len(session.evaluations)
    return FeedbackResponse(
        summary=(f"Interview covered {total} questions across "
                 f"{len(session.covered_days)} curriculum days. "
                 f"{num_strong} strong responses, {num_gaps} gaps identified."),
        strengths=final_strengths,
        gaps=final_gaps,
        next=final_next,
    )


