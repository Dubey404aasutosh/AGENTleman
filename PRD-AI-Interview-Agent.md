# PRD — AI Interview Agent

**PS:** The Interview Agent (build the interviewer, not the interview)
**Owner:** Shalom (solo build)

---

## 1. Problem

AI Cohort learners finish a 31-day program but struggle to *talk about* what they built. Need an agent that runs a realistic, personalized technical interview grounded in each candidate's actual learning path — not a static question bank.

## 2. Goals

- Meet every PS minimum requirement (see §5).
- Personalize question depth to the candidate's own mission history, not just their curriculum coverage.
- Feel like a real interviewer: follow-ups that reference what was just said, not a fixed script.

## 3. Non-goals (per spec)

Voice, auth, persistent accounts, long-term history across sessions, mobile app.

## 4. Inputs

| Source | Shape | Used for |
|---|---|---|
| `curriculum.json` | 31 days, 8 modules, each day → `title`, `type`, `tools`, `objectives` | Question grounding — never ask outside a covered objective |
| `candidates.json` | per candidate: `member` (role, experience, education) + `missions[]` (day, passed/failed/skipped, attempts) + `signals` (commitDays, missionsCompleted, missionsFirstTry) | Topic selection + difficulty calibration |

## 5. Functional requirements → design mapping

| PS requirement | Satisfied by |
|---|---|
| ≥8 questions across ≥4 curriculum days | Planner selects topics across ≥4 modules at session start |
| Follow-ups from prior responses | Turn engine's evaluate → follow-up/advance decision |
| Context maintained throughout | Session state keyed by `sessionId` |
| Structured feedback at end | Feedback synthesizer, built from accumulated per-turn evaluations |
| `POST /api/interview` contract | Turn engine request/response shape maps 1:1 to spec's start/turn/end |

## 6. Architecture (see prior diagram)

`curriculum.json` + `candidate profile` → **Interview planner** (picks days + difficulty tier) → **Session state** (keyed by `sessionId`) → **Turn engine** (evaluate → follow-up or next, loops per message) → **Feedback synthesizer** (fires once plan minimums are met) → structured `feedback` object.

## 7. Key design decisions

| Decision | Choice | Why |
|---|---|---|
| Orchestration | Plain FastAPI, no agent framework | One role looping under logic we control — LangChain/CrewAI add overhead without adding capability here |
| LLM calls per turn | One combined call (evaluate + reply), not two | Half the latency/cost, no drift between what was judged and what was said |
| LLM provider | Gemini free API — Flash for per-turn calls, Flash-Lite as fallback if quota gets tight | Free tier's RPM/RPD headroom fits many small calls; Flash-Lite as demo-day insurance |
| Output format | Forced JSON via `responseSchema` (Gemini structured output), never free-text parsing | Malformed output breaks the graded API contract — enforce at schema level, not with cleanup regex |
| Topic selection | Span ≥4 modules, deliberately include 1–2 weak/skipped-signal days | Reads as a real interview, not one deep-dive; surfaces gaps instead of only confirming strengths |
| Difficulty calibration | `missionsFirstTry / missionsCompleted` shifts framing (mechanism vs. trade-off questions) | Same question pool, different altitude — personalization without a second question bank |
| Per-answer evaluation | Qualitative 3-bucket (missed / partial / strong) per answer, not a numeric rubric | Fast to reason about under a strict prompt, still enough signal to populate strengths/gaps distinctly. *(Only real open decision left — see §10.)* |

## 8. Session flow

1. **Start** — planner builds topic plan from candidate + curriculum data → first question.
2. **Turn** — candidate answers → evaluate against that day's objectives → follow-up (same day) or advance (next planned day) → next question.
3. **End** — once ≥8 questions across ≥4 days are covered → synthesizer aggregates all per-turn evaluations into `{summary, strengths, gaps, next}`.

## 9. Risks

| Risk | Mitigation |
|---|---|
| Gemini free-tier quota hit mid-demo | Fallback to Flash-Lite; check current RPM/RPD on `ai.google.dev/pricing` day-of |
| LLM drifts outside curriculum scope | System prompt grounds every question strictly in that day's `objectives`/`tools` |
| Malformed JSON breaks grader | Enforced `responseSchema`, not text parsing |
| Interview feels scripted despite follow-up logic | Follow-up question generation reads the *actual* last answer, not just "same day, next question" |

## 10. Open decisions

- Per-answer evaluation granularity (3-bucket qualitative, as above, vs. numeric score) — leaning bucket for build speed; revisit only if feedback quality feels thin in testing.

## 11. Verification checklist (pre-submission)

- [ ] Fresh session → first response has `done: false`, no `feedback` field
- [ ] At least 8 total questions asked across a full run
- [ ] Those questions span ≥4 distinct curriculum days
- [ ] At least one visible follow-up that clearly references the candidate's prior answer (not a generic next-topic question)
- [ ] Final response has `done: true` + all four `feedback` fields populated (`summary`, `strengths`, `gaps`, `next`)
- [ ] `gaps`/`next` reference specific curriculum days, not generic advice
- [ ] Two different candidate profiles (e.g. high first-try vs. low first-try) produce visibly different question depth
- [ ] Run once against a candidate with a `skipped` mission — confirm it's touched lightly, not skipped entirely or over-penalized
- [ ] No hallucinated tools/topics outside `curriculum.json`
- [ ] Endpoint survives a malformed/short candidate answer without breaking the JSON contract
