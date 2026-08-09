"""
Prompts module (Component 5.4, Phase 3).
Centralized prompt templates for interview turn processing and feedback synthesis.
"""

TONE_INSTRUCTIONS = {
    "peer": (
        "Address this candidate as a fellow practitioner. Use collaborative "
        "phrasing: 'Walk me through...', 'What trade-offs did you consider...'. "
        "They demonstrated strong first-try mastery across the program."
    ),
    "supportive": (
        "This candidate is early-career and/or found parts of the program "
        "challenging. Use encouraging, exploratory phrasing: 'Let's explore what "
        "you learned...', 'What stood out to you...'. Make them comfortable. If "
        "they are senior/experienced but simply struggled with THIS material, "
        "keep the tone supportive without implying they are junior."
    ),
    "professional": (
        "Use balanced, professional phrasing: 'Can you explain how you "
        "approached...', 'What was your experience with...'. Neutral and respectful."
    ),
}

DEPTH_INSTRUCTIONS = {
    "high": (
        "This candidate demonstrated first-try mastery on this topic. Ask about "
        "architectural trade-offs, edge cases, failure modes, or 'why X over Y' "
        "comparisons. Push for depth beyond surface recall."
    ),
    "medium": (
        "This candidate passed but needed multiple attempts. Ask about "
        "implementation mechanics -- how specific tools were configured, what "
        "errors they hit, and practical decisions they made."
    ),
    "low": (
        "This candidate struggled significantly with this topic (4+ attempts). "
        "Ask clear, direct questions about core concepts and basic tool usage. "
        "Keep it approachable -- avoid abstract trade-off framing."
    ),
    "diagnostic": (
        "This candidate skipped or did not pass this topic. Ask a single "
        "lightweight probing question to gauge awareness. Frame it as "
        "exploratory ('What's your understanding of...'), not evaluative. "
        "Accept any honest answer gracefully and move on."
    ),
}

_MISSION_STATUS_TEXT = {
    "first_try": "Passed on the first attempt.",
    "passed_multi": "Passed, but needed a few attempts.",
    "passed_hard": "Passed, but only after several attempts -- this was a struggle.",
    "failed": "Did not pass this mission.",
    "skipped": "Skipped this mission entirely.",
    "not_attempted": "Never attempted this mission (not in their recorded activity).",
}

def _objectives_bulleted(objectives: list[str]) -> str:
    return "\n".join(f"- {o}" for o in objectives)


def build_first_question_prompt(topic, candidate, tone: str) -> str:
    member = candidate.member
    return f"""You are a senior technical interviewer conducting a personalized interview
for {member.name}, a {member.jobRole} with {member.yearsExperience} years of
experience who completed an AI engineering cohort.

{TONE_INSTRUCTIONS[tone]}

You are starting the interview on:
TOPIC: Day {topic.day} -- "{topic.title}"
MODULE: {topic.module_title}
TOOLS: {", ".join(topic.tools)}
OBJECTIVES:
{_objectives_bulleted(topic.objectives)}

CANDIDATE PERFORMANCE ON THIS TOPIC: {_MISSION_STATUS_TEXT.get(topic.mission_status, "Unknown.")}
DEPTH: {DEPTH_INSTRUCTIONS[topic.depth.value]}

Generate a warm, personalized welcome using the candidate's name, then
immediately ask your first interview question grounded in the objectives and
tools above. Do NOT mention anything outside this topic.

Respond as JSON: {{"reply": "<welcome + first question>"}}"""


def build_turn_prompt(current_topic, next_topic, candidate, tone: str, topic_summaries: list[str]) -> str:
    member = candidate.member
    summaries_text = "\n".join(f"- {s}" for s in topic_summaries) if topic_summaries else "(none yet)"

    if next_topic is not None:
        next_block = f"""Day {next_topic.day} -- "{next_topic.title}"
Module: {next_topic.module_title}
Tools: {", ".join(next_topic.tools)}
Objectives:
{_objectives_bulleted(next_topic.objectives)}
Candidate performance: {_MISSION_STATUS_TEXT.get(next_topic.mission_status, "Unknown.")}
Depth: {DEPTH_INSTRUCTIONS[next_topic.depth.value]}"""
    else:
        next_block = ("None -- this is the final topic. If you decide to advance, "
                      "wrap up with a brief closing remark instead of asking a new question.")

    return f"""You are a senior technical interviewer mid-interview with {member.name}
({member.jobRole}, {member.yearsExperience} years experience).

{TONE_INSTRUCTIONS[tone]}

======================================================================
CURRENT TOPIC (evaluate the candidate's answer against THIS):
======================================================================
Day {current_topic.day} -- "{current_topic.title}"
Module: {current_topic.module_title}
Tools: {", ".join(current_topic.tools)}
Objectives:
{_objectives_bulleted(current_topic.objectives)}
Candidate performance: {_MISSION_STATUS_TEXT.get(current_topic.mission_status, "Unknown.")}
Depth: {DEPTH_INSTRUCTIONS[current_topic.depth.value]}

======================================================================
NEXT TOPIC (ask about THIS only if you decide to advance):
======================================================================
{next_block}

======================================================================

PRIOR TOPICS (summary only, for conversational continuity):
{summaries_text}

YOUR TASK -- respond as JSON with these exact fields:

1. "evaluation": Assess the candidate's LATEST answer against CURRENT TOPIC objectives.
   - "bucket": "missed" | "partial" | "strong"
   - "rationale": 1-2 sentences referencing what they said or missed

2. "decision": "follow_up" | "advance"
   - "follow_up": probe deeper on CURRENT TOPIC, referencing something specific
     from their answer
   - "advance": transition to NEXT TOPIC

3. "reply": Your natural response including the next question.
   - If "follow_up": ground your question ONLY in CURRENT TOPIC tools/objectives
   - If "advance": briefly acknowledge their answer, then ask a question
     grounded ONLY in NEXT TOPIC tools/objectives

STRICT RULES:
- Ground evaluation ONLY in CURRENT TOPIC objectives.
- Ground follow-up questions ONLY in CURRENT TOPIC tools/objectives.
- Ground advance questions ONLY in NEXT TOPIC tools/objectives.
- NEVER mention tools or concepts not listed in the relevant topic block above.
- NEVER reveal you are following a script or structured evaluation framework.
- If the candidate says "I don't know" or gives an answer of 5 words or fewer:
  rate "missed", decide "advance", and move on gracefully -- do not pressure them."""


def build_feedback_prompt(candidate, evaluations_formatted: str) -> str:
    member = candidate.member
    return f"""Summarize the completed technical interview for {member.name}
({member.jobRole}, {member.yearsExperience} years experience).

INTERVIEW EVALUATIONS:
{evaluations_formatted}

Generate a structured feedback object as JSON with these exact fields:

- "summary": 2-3 sentence overall assessment of interview performance.
- "strengths": array of 3-5 specific strengths. Each MUST cite a specific Day
  number and exact title as given in the evaluations above, e.g. "Day 22 — Multi-Agent Orchestration: clearly
  explained router agent delegation patterns."
- "gaps": array of 2-4 specific gaps. Each MUST cite a specific Day number
  and exact title as given in the evaluations above. Do NOT give generic advice -- cite what was actually missed.
- "next": array of 2-4 actionable next steps. Each MUST reference a specific
  Day number and exact title, suggesting a concrete exercise, e.g. "Revisit Day 29 — Monitoring, Logging & Observability
  objectives: implement Prometheus metrics collection in a FastAPI app."

CRITICAL TITLE RULE:
Whenever citing any Day N in "strengths", "gaps", or "next", you MUST format it as:
"Day <N> — <EXACT_OFFICIAL_TITLE>: <details>"
You MUST use the EXACT OFFICIAL TITLE provided in the INTERVIEW EVALUATIONS above for that Day number.
NEVER alter, paraphrase, or reconstruct a day title!

RULES:
- Every item in strengths/gaps/next MUST reference a specific Day number and exact title.
- Do NOT invent tools or topics that were not covered in the interview.
- Be encouraging but honest -- gaps are learning opportunities, not failures.
- "next" steps must be concrete exercises, not vague recommendations like "study more"."""
