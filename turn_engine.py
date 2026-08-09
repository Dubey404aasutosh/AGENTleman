"""
Turn Engine module (Component 5.5, Phase 4).
Executes individual interview turns, combined LLM evaluation + decision + reply generation.
"""

from models import SessionState, TurnEvaluation, InterviewResponse
import prompts
import llm_client
import feedback_synthesizer

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

FIRST_QUESTION_SCHEMA = {
    "type": "OBJECT",
    "properties": {"reply": {"type": "STRING"}},
    "required": ["reply"],
}


def process_turn(session: SessionState, candidate_message: str) -> InterviewResponse:
    # 1. Record candidate's answer
    session.turn_history.append({"role": "user", "content": candidate_message})
    session.current_topic_history.append({"role": "user", "content": candidate_message})

    # 2. Current + next topic (dual-topic grounding, Decision #7)
    current_topic = session.plan[session.current_topic_index]
    has_next = (session.current_topic_index + 1) < len(session.plan)
    next_topic = session.plan[session.current_topic_index + 1] if has_next else None

    # 3. Build prompt (dual-topic + tone in every prompt, Decision #9)
    system_prompt = prompts.build_turn_prompt(
        current_topic=current_topic, next_topic=next_topic,
        candidate=session.candidate, tone=session.candidate_tone,
        topic_summaries=session.topic_summaries,
    )
    messages = session.current_topic_history  # sliding window only (Decision #20)

    # 4. Call LLM with full resilience (Decision #21, #22)
    try:
        llm_response = llm_client.generate(
            system_prompt=system_prompt, messages=messages,
            response_schema=TURN_RESPONSE_SCHEMA, session=session,
        )
        evaluation = llm_response["evaluation"]
        decision = llm_response["decision"]
        reply = llm_response["reply"]
    except llm_client.LLMCallError as exc:
        print(f"[LLM_FALLBACK_WARNING] Candidate={session.candidate.member.id} in process_turn: {exc}")
        evaluation = {"bucket": "partial", "rationale": "Technical issue — moved to next topic."}
        decision = "advance"
        reply = f"Thank you for your thoughts on {current_topic.title}. "
        if next_topic:
            first_tool = next_topic.tools[0] if next_topic.tools else "this area"
            reply += f"Let's move on. Regarding {next_topic.title} — can you tell me about your experience with {first_tool}?"
        else:
            reply += "Let's wrap up."

    # 5. Record evaluation
    session.evaluations.append(TurnEvaluation(
        bucket=evaluation["bucket"], rationale=evaluation["rationale"],
        covered_day=current_topic.day, covered_title=current_topic.title,
    ))
    session.covered_days.add(current_topic.day)
    session.questions_asked += 1

    # 6. Apply decision — explicit mutation on override (Decision #19)
    if decision == "follow_up" and session.current_topic_followups >= 1:
        decision = "advance"   # code-enforced cap (Decision #18); never trust a 2nd follow-up

    if decision == "follow_up":
        session.current_topic_followups += 1
    elif decision == "advance":
        summary = f"Day {current_topic.day} ({current_topic.title}): {evaluation['bucket']} — {evaluation['rationale'][:100]}"
        session.topic_summaries.append(summary)
        session.current_topic_history = []
        session.current_topic_followups = 0
        session.current_topic_index += 1

    # 7. Deterministic completion check — NEVER LLM-decided (Decision #12)
    plan_exhausted = session.current_topic_index >= len(session.plan)
    minimums_met = session.questions_asked >= 8 and len(session.covered_days) >= 4

    if minimums_met or plan_exhausted:
        session.is_done = True
        # DISCARD the LLM's `reply` — it may contain a question the candidate
        # can never answer (Decision #13).
        name = session.candidate.member.name
        closing_reply = (
            f"Thank you, {name} — that wraps up your interview. I appreciate you "
            f"walking me through your experience with the AI cohort. Here's your feedback."
        )
        feedback = feedback_synthesizer.generate(session)
        return InterviewResponse(reply=closing_reply, done=True, feedback=feedback)

    # 8. Continue
    session.turn_history.append({"role": "assistant", "content": reply})
    session.current_topic_history.append({"role": "assistant", "content": reply})
    return InterviewResponse(reply=reply, done=False, feedback=None)


def generate_first_question(session: SessionState) -> str:
    first_topic = session.plan[0]
    system_prompt = prompts.build_first_question_prompt(
        topic=first_topic, candidate=session.candidate, tone=session.candidate_tone,
    )
    try:
        llm_response = llm_client.generate(
            system_prompt=system_prompt, messages=[],
            response_schema=FIRST_QUESTION_SCHEMA, session=session,
        )
        reply = llm_response["reply"]
    except llm_client.LLMCallError as exc:
        print(f"[LLM_FALLBACK_WARNING] Candidate={session.candidate.member.id} in generate_first_question: {exc}")
        name = session.candidate.member.name
        first_tool = first_topic.tools[0] if first_topic.tools else "this topic"
        reply = (f"Welcome {name}! Let's begin your technical interview. On Day "
                 f"{first_topic.day}, you worked on {first_topic.title}. Can you "
                 f"walk me through your experience with {first_tool}?")

    session.turn_history.append({"role": "assistant", "content": reply})
    session.current_topic_history.append({"role": "assistant", "content": reply})
    session.questions_asked = 1
    session.covered_days.add(first_topic.day)
    return reply
