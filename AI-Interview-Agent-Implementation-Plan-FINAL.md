# AI Interview Agent — Implementation Plan (FINAL)

**Status:** Build-ready. Consolidates the PRD, the technical spec, and every decision, bug, and fix traced across four prior review rounds (v1 → v4), re-verified against the actual `curriculum.json` and `candidates.json` files rather than assumed data.

---

## 0. Executive Summary

Build an adaptive AI technical interviewer exposed as a single `POST /api/interview` endpoint. The agent reads a candidate's real mission history from the AI Cohort, plans 8–10 interview topics spanning at least 4 curriculum modules, calibrates question depth **per topic** (not globally), asks organic follow-ups grounded in what the candidate just said, and synthesizes structured `{summary, strengths, gaps, next}` feedback once the plan's minimums are satisfied.

**Stack:** Plain FastAPI (no agent framework) + Gemini API (`gemini-3.6-flash` primary, `gemini-3.5-flash-lite` fallback), one combined LLM call per conversation turn, forced JSON structured output, in-memory session state. Every design decision below was chosen specifically because it closes a failure mode that surfaced during review — not by default.

---

## 1. Verified Data Grounding

Everything in this section was checked directly against the uploaded `curriculum.json` (598 lines) and `candidates.json` (464 lines, 20 candidates) — not assumed.

### 1.1 Curriculum structure

31 days, 8 modules. Each day object has `day`, `title`, `type`, `tools[]`, `objectives[]`.

| Module | Days | Title |
|---|---|---|
| 1 | 1–3 | Environment & Tooling |
| 2 | 4–6 | Data Foundations |
| 3 | 7–10 | Embeddings & Vector Search |
| 4 | 11–15 | LLM Core, Prompting & Fine-Tuning |
| 5 | 16–20 | Chatbot Application Build |
| 6 | 21–24 | Agentic AI & MCP |
| 7 | 25–28 | Evaluation, Security & Deployment |
| 8 | 29–31 | Production & Capstone |

### 1.2 Candidate roster (real data, all 20)

Each candidate has `member{id,name,jobRole,yearsExperience,education,status}`, `missions[]` (9–11 entries per candidate, **not all 31 days** — most days are simply absent from a candidate's list, which is why the planner's `not_attempted` backfill path is exercised constantly, not just in edge cases), and `signals{commitDays,missionsCompleted,missionsFirstTry}`.

| ID | Name | Yrs Exp | Missions listed (pass/fail/skip) | completed/firstTry | Ratio |
|---|---|---|---|---|---|
| CAND-001 | Sarah Johnson | 9 | 10 (9/0/1) | 30/20 | 0.667 |
| CAND-002 | Alex Turner | 5 | 10 (10/0/0) | 29/10 | 0.345 |
| CAND-003 | Emily Chen | 6 | 10 (10/0/0) | 31/30 | **0.968** |
| CAND-004 | David Miller | 8 | 10 (9/0/1) | 28/6 | 0.214 |
| CAND-005 | Michael Brown | 10 | 10 (10/0/0) | 31/22 | 0.710 |
| CAND-006 | Wendy Foster | 12 | 10 (8/0/2) | 24/2 | 0.083 |
| CAND-007 | Ethan Brooks | 0 | 10 (8/0/2) | 27/22 | 0.815 |
| CAND-008 | Harold Whitfield | 28 | 11 (9/0/2) | 27/15 | 0.556 |
| CAND-009 | Zara Ahmadi | 1 | 10 (10/0/0) | 31/29 | 0.935 |
| CAND-010 | Gerald Combs | 20 | 10 (5/3/2) | 23/1 | **0.043** |
| CAND-011 | Mia Alvarez | 6 | 10 (5/0/**5**) | 14/5 | 0.357 |
| CAND-012 | Chen Wei | 7 | 10 (10/0/0) | 30/14 | 0.467 |
| CAND-013 | Ravi Patel | 15 | 10 (10/0/0) | 30/13 | 0.433 |
| CAND-014 | Bethany Cole | 10 | 10 (6/0/4) | 20/1 | 0.050 |
| CAND-015 | Noah Kim | 20 | 10 (8/0/2) | 29/27 | 0.931 |
| CAND-016 | Isabella Rossi | 5 | 9 (**4/3/2**) | 21/2 | 0.095 |
| CAND-017 | Tyler Brooks | 0 | 10 (10/0/0) | 31/1 | 0.032 |
| CAND-018 | Diane Foster | 4 | 10 (10/0/0) | 31/31 | **1.000** |
| CAND-019 | Frank DeLuca | 25 | 10 (10/0/0) | 29/11 | 0.379 |
| CAND-020 | Priyanka Sharma | 5 | 10 (7/1/2) | 27/19 | 0.704 |

### 1.3 Specific claims verified

Every candidate reference used across the four prior review rounds turned out to be accurate, not fabricated:

- **CAND-001 Sarah Johnson** really does have Day 29 ("Monitoring, Logging & Observability", Module 8) marked `skipped: true` — the golden-path test target is real.
- **CAND-003 Emily Chen**: 30/31 first-try = 96.8% ✓ (cited as "96.7%")
- **CAND-010 Gerald Combs**: 1/23 first-try = 4.3% ✓, and independently has 3 failed + 2 skipped missions
- **CAND-011 Mia Alvarez**: exactly 5 skipped missions ✓
- **CAND-016 Isabella Rossi**: exactly 3 failed + 2 skipped = 5 diagnostic-eligible days ✓ — this is the concrete case that proves the "max 2 skipped/failed" cap (§3, row 15) is a necessary rule, not defensive over-engineering.

### 1.4 Correction: depth-tier distribution

The design-decision table circulated in v2–v4 stated *"79 HIGH / 50 MEDIUM / 46 LOW across 175 missions."* Recomputing directly from the file:

- Total mission entries across all 20 candidates: **200**
- Passed, 1 attempt (**HIGH**): **79** ✓ (this one was exactly right)
- Passed, 2–3 attempts (**MEDIUM**): **47** (not 50)
- Passed, ≥4 attempts (**LOW**): **42** (not 46)
- Failed: 7 · Skipped: 25 (both → `DIAGNOSTIC`, regardless of any `attempts` value they carry)

The conclusion is unchanged — all three depth buckets are well-populated — but the final plan below uses the correct numbers.

---

## 2. API Contract

### 2.1 Endpoint

```
POST /api/interview
```
No authentication. State is maintained purely via the client-supplied `sessionId` (no DB — in-memory, per PRD non-goals).

### 2.2 Start (candidate present)

```json
// Request
{ "sessionId": "abc-123", "candidate": { ...CandidateProfile } }

// Response
{ "reply": "Welcome, Sarah! ... <first question, bundled in> ...", "done": false }
```

### 2.3 Turn (message present)

```json
// Request
{ "sessionId": "abc-123", "message": "..." }

// Response
{ "reply": "...", "done": false }
```

### 2.4 End (deterministic, code-decided — see §3 row 10)

```json
{
  "reply": "Thank you, Sarah — that wraps up your interview. ...",
  "done": true,
  "feedback": { "summary": "...", "strengths": [...], "gaps": [...], "next": [...] }
}
```

### 2.5 Three ambiguities in the raw spec, resolved

The spec differentiates Start vs. Turn purely by which optional field is present, and its own example (`"Welcome. Let's begin your interview."`) implies no defined mechanism for the client to request question 1 separately. Three resolutions, carried through unchanged from the original review:

1. **Start bundles the welcome greeting *and* question 1** into a single `reply` — no dead turn, no undefined "empty message" required from the client.
2. **`done` is deterministic code logic** (`questions_asked >= 8 AND len(covered_days) >= 4`), never an LLM output — prevents prompt-drift-induced early termination or infinite loops.
3. **Re-sending `candidate` on an existing `sessionId` resets the session** (idempotent restart) — prevents a stuck automated grader/test-runner from being unable to recover.

---

## 3. Master Design Decisions

Every decision below closes a specific failure mode found during review. `[NEW]` marks fixes introduced in this final consolidation that were not present in any of v1–v4.

| # | Decision | Resolution | Problem it solves |
|---|---|---|---|
| 1 | Stack | Plain FastAPI, no LangChain/CrewAI/agent framework | One evaluator/generator role looping under logic we already control — a framework adds abstraction and debugging overhead without adding capability |
| 2 | LLM models | Primary `gemini-3.6-flash`, fallback `gemini-3.5-flash-lite`, read from env vars | `gemini-2.0-flash`/`-lite` (the original choice) were already shut down June 1, 2026; `gemini-2.5-*` is slated to shut down Oct 2026 — verified current GA models used instead |
| 3 | System prompt delivery | `GenerateContentConfig(system_instruction=...)`, kept entirely out of `contents` | Putting the system prompt in `contents` as a `user`-role turn created two consecutive `user` turns on every call (candidate's answer is also `user`), violating Gemini's required `user`/`model` alternation |
| 4 | `contents` construction — non-empty guard | If `messages` is empty (Q1 opener, feedback call), seed `[{"role":"user","content":"Begin."}]` | Gemini rejects an empty `contents` list (`400: contents is not specified`) — hit on literally the first call of every interview and every feedback synthesis |
| 5 | `contents` construction — leading-turn guard | **`[FINAL FIX]`** If the first real message isn't `user`-role, **prepend** a synthetic anchor `user` turn (`"(Interview in progress.)"`). Do **not** strip leading turns. | An earlier draft of this fix stripped leading `model`-role turns to satisfy "must start with user" — but `current_topic_history` legitimately opens with the assistant's own question on *every single topic* (both the very first topic and every topic reached via `advance`). Stripping silently deleted the actual question being evaluated against, out of the context the evaluator LLM could see, on every turn in the interview. Prepending satisfies the same constraint with zero data loss. |
| 6 | LLM calls per turn | One combined call: evaluate + decide + reply | Halves latency/cost vs. two separate calls; avoids state drift between "what was judged" and "what was said" |
| 7 | Dual-topic injection | Every turn prompt includes **both** the current topic (to evaluate against) and the next topic (to ask about if advancing) | Without this, the single combined call had no grounding for the *next* question when the model decided to advance — it either hallucinated a question outside the curriculum, produced a vague transition, or violated its own "don't mention anything outside this topic" rule |
| 8 | Calibration | Per-topic depth (that specific mission's attempts/pass/skip), never overridden by a global tier | A candidate's overall ratio says nothing about whether they've ever touched *this specific* topic — a global "High" tier asking design-level questions on a topic the candidate actually skipped would be a worse interview, not a better one |
| 9 | Global ratio usage | Sets conversational **tone only** (`peer`/`supportive`/`professional`), injected into every prompt, never overrides per-topic depth | Keeps the personalization signal (global performance) without letting it contaminate the more accurate per-topic signal |
| 10 | Depth thresholds | `1 attempt→HIGH`, `2–3→MEDIUM`, `≥4→LOW`, `skipped/failed→DIAGNOSTIC` | Validated against real data: 79/47/42 split (corrected, see §1.4) — all three buckets well-populated, thresholds don't need adjusting |
| 11 | Evaluation granularity | 3-bucket qualitative (`missed`/`partial`/`strong`) + `rationale` string | Fast, reliable under a strict JSON schema; sufficient signal to populate distinct `strengths`/`gaps` at synthesis time without the complexity of a numeric rubric |
| 12 | `done` authority | Deterministic code logic, never an LLM output field | Prevents the model from ending early or looping forever due to prompt drift |
| 13 | Final response `reply` | Deterministic closing statement; the LLM's own `reply` is **discarded** the instant `is_done` becomes true | The instant the question/day counters cross the threshold can land mid-`follow_up` — the LLM may have generated a brand-new question in that same call, which the candidate can never answer. The spec's own example shows a closing statement, not a question. |
| 14 | Start response | Bundles welcome + Q1 in one `reply` | Eliminates a dead turn; no undefined empty-message step |
| 15 | Skipped/failed cap | Max **2** diagnostic-signal topics per plan | Without a cap, CAND-016 (3 failed + 2 skipped) or CAND-011 (5 skipped) would get an interview that's mostly gap-probing, which doesn't read as a real interview and contradicts the PRD's own "1–2 weak/skipped days" intent |
| 16 | Topic count | Planner selects **8–10 topics**; follow-ups are bonus, never required to reach the floor | An earlier draft selected only 5–7 topics, meaning zero follow-ups could produce as few as 5 questions — under the spec's hard ≥8 minimum |
| 17 | Planner slot reservation | Bucket selection caps at **7** slots; module-coverage additions use slots 8–10; final `[:10]` trim runs *after* coverage is added | If coverage topics were appended after a full 10-slot bucket fill, a naive trim could slice them back off — silently dropping back under 4 modules and firing the invariant `ValueError` |
| 18 | Follow-up cap | Max 1 follow-up per topic, enforced in **code**, not trusted to the LLM | Prevents an infinite loop if the model returns `"follow_up"` repeatedly on the same topic |
| 19 | Decision override | The override explicitly **mutates** `decision = "advance"` (not just branches around it) | Without the explicit mutation, `current_topic_index` never increments on the forced-advance path → silent infinite loop on one topic |
| 20 | Conversation history | Sliding window: only the **current topic's** exchange goes to the LLM; prior topics compress to 1-line summaries; the full transcript is kept separately for feedback synthesis only | By question 8, a full transcript includes 4+ unrelated topics — bloats context, dilutes the model's focus on what it's actually supposed to be grading right now, raises cost |
| 21 | LLM error handling | Every exception path — quota, timeout, parse failure, fallback-also-exhausted — terminates in `LLMCallError` | An earlier draft's bare `raise` on "fallback also exhausted" re-raised the raw SDK exception, which nothing in `process_turn` caught — an unhandled 500 in exactly the scenario (both tiers rate-limited) most likely during a live demo |
| 22 | Turn-engine resilience | `process_turn` catches `LLMCallError` and degrades deterministically: force-advance, `bucket="partial"`, a templated transition reply | Never crash the session on a transient LLM failure mid-interview |
| 23 | Fallback model | Sticky per-session (`using_fallback: bool`); once `True`, never re-attempts primary | Without this, every turn re-discovers the 429 before falling back — wasted call + latency on every remaining turn |
| 24 | Timeout | 15s via `Client(http_options=HttpOptions(timeout=15_000))` (constructor, milliseconds) | The `google-genai` SDK reads timeout from the `Client` constructor, not from per-call `generate_content` config, where it would be silently ignored |
| 25 | Error responses | `HTTPException(detail={...})` as a real dict; custom exception handler returns it directly | `detail=json.dumps({...})` double-encodes the error: `{"detail":"{\"error\":...}"}` — a grader parsing `response.json()["detail"]` gets a string, not a dict |
| 26 | Plan validation | `raise ValueError(...)`, never a bare `assert` | `assert` is stripped entirely under `python -O`; even when active, an uncaught `AssertionError` is an ugly unhandled 500. `ValueError` is caught by a custom handler and returned as clean diagnostic JSON. |
| 27 | Lifespan | `@asynccontextmanager` lifespan, not the deprecated `@app.on_event("startup")` | Current FastAPI-recommended pattern; startup loads `curriculum.json` once and initializes the Gemini client once |
| 28 | Quota detection | Check `APIError.code == 429` first; string-match on exception name/message as fallback | More robust than pure string-matching alone, which is fragile across SDK versions |
| 29 | `[NEW]` Response shape fidelity | `@app.post(..., response_model_exclude_none=True)` | The spec's own example shows `{"reply":..., "done": false}` with **no `feedback` key at all** on non-final turns. Pydantic's default serialization would instead emit `"feedback": null` — an extra key not shown in the spec. `exclude_none=True` makes the JSON byte-for-byte match the spec's example. Not caught in any of the four prior review rounds. |
| 30 | `[NEW]` Mutable Pydantic defaults | `covered_days`, `turn_history`, etc. use `Field(default_factory=...)`, not bare `set()`/`[]` | Pydantic v2 does handle this safely on its own, but `default_factory` is the explicit, version-proof idiom and removes any ambiguity if the model is ever constructed via `model_construct()` (which bypasses normal default handling) |
| 31 | `[NEW]` Module/function calling convention | `llm_client.py` and `session_store.py` each expose bare module-level functions (`llm_client.generate(...)`, `session_store.get(...)`) backed by a module-level singleton instance | All four prior drafts called these as if they were module functions while defining them as classes — never resolved concretely. Fixed here so `turn_engine.py`/`main.py` code is actually consistent with what it imports. |
| 32 | `[NEW]` Interview-flow ordering | `_sort_for_interview_flow` fully implemented (open on MEDIUM, protect first/last slot from DIAGNOSTIC, close on HIGH/MEDIUM) | Every prior draft left this as an unexpanded one-line comment — never actually specified |
| 33 | Deployment | Local `uvicorn`. Optional `Dockerfile` in Phase 6. | Hackathon build; local is sufficient for grading |
| 34 | Frontend | Backend API only for submission; optional Streamlit UI in Phase 6 | Spec explicitly allows any/no frontend; backend alone satisfies the contract |

---

## 4. Data Models — `models.py`

```python
from enum import Enum
from pydantic import BaseModel, Field


# ── API-facing models (must match technical-spec.md + candidates.json exactly) ──

class CandidateMember(BaseModel):
    id: str
    name: str
    jobRole: str
    yearsExperience: int
    education: str
    status: str

class CandidateMission(BaseModel):
    day: int
    title: str
    passed: bool | None = None     # absent/None when skipped
    skipped: bool | None = None    # True when skipped
    attempts: int | None = None    # present whenever `passed` is set (True OR False)

class CandidateSignals(BaseModel):
    commitDays: int
    missionsCompleted: int
    missionsFirstTry: int

class CandidateProfile(BaseModel):
    member: CandidateMember
    missions: list[CandidateMission]
    signals: CandidateSignals

class InterviewRequest(BaseModel):
    sessionId: str
    candidate: CandidateProfile | None = None   # present = START (or session reset)
    message: str | None = None                  # present = TURN

class FeedbackResponse(BaseModel):
    summary: str
    strengths: list[str]
    gaps: list[str]
    next: list[str]

class InterviewResponse(BaseModel):
    reply: str
    done: bool
    feedback: FeedbackResponse | None = None
    # NOTE: omitted from the JSON entirely unless done=True — see main.py's
    # response_model_exclude_none=True (Design Decision #29).


# ── Internal state (never serialized to the API) ──

class TopicDepth(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    DIAGNOSTIC = "diagnostic"

class PlannedTopic(BaseModel):
    day: int
    title: str
    module_n: int
    module_title: str
    depth: TopicDepth
    objectives: list[str]
    tools: list[str]
    mission_status: str   # first_try | passed_multi | passed_hard | failed | skipped | not_attempted

class TurnEvaluation(BaseModel):
    bucket: str            # missed | partial | strong
    rationale: str
    covered_day: int
    covered_title: str

class SessionState(BaseModel):
    session_id: str
    candidate: CandidateProfile
    plan: list[PlannedTopic]
    current_topic_index: int = 0
    current_topic_followups: int = 0      # max 1 follow-up per topic
    questions_asked: int = 0              # must reach >= 8
    covered_days: set[int] = Field(default_factory=set)          # must reach >= 4 distinct
    turn_history: list[dict] = Field(default_factory=list)       # full transcript — feedback synthesizer only
    current_topic_history: list[dict] = Field(default_factory=list)  # sliding window — sent to the LLM each turn
    evaluations: list[TurnEvaluation] = Field(default_factory=list)
    topic_summaries: list[str] = Field(default_factory=list)     # 1-line per completed topic
    is_done: bool = False
    using_fallback: bool = False          # sticky — once True, never re-attempts primary
    candidate_tone: str = "professional"  # peer | supportive | professional
```

---

## 5. Component Architecture

### 5.0 Project structure

```
AGENTlemen/
├── PRD-AI-Interview-Agent.md
├── technical-spec.md
├── candidates.json
├── curriculum.json
│
├── requirements.txt
├── .env.example
├── main.py                    # FastAPI app + single route + lifespan
├── models.py                  # All Pydantic schemas
├── session_store.py           # Thread-safe in-memory session manager
├── planner.py                 # Topic selection + depth/tone calibration
├── turn_engine.py             # Per-turn LLM call + eval + decision loop
├── feedback_synthesizer.py    # Final feedback generation
├── llm_client.py              # Gemini wrapper: system_instruction, fallback, contents guards
├── prompts.py                 # All prompt templates as functions
│
├── Dockerfile                 # [Phase 6, optional]
├── ui.py                      # [Phase 6, optional — Streamlit chat UI]
│
└── tests/
    ├── test_api_contract.py
    ├── test_planner.py
    ├── test_turn_engine.py
    └── test_edge_cases.py
```

### 5.1 Session Store — `session_store.py`

```python
import threading
import time
from models import SessionState

_TTL_SECONDS = 30 * 60  # 30 minutes — lazy eviction, no persistence (per PRD non-goals)


class SessionStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._data: dict[str, tuple[SessionState, float]] = {}

    def get(self, session_id: str) -> SessionState | None:
        with self._lock:
            entry = self._data.get(session_id)
            if entry is None:
                return None
            state, ts = entry
            if time.time() - ts > _TTL_SECONDS:
                del self._data[session_id]
                return None
            return state

    def set(self, session_id: str, state: SessionState) -> None:
        with self._lock:
            self._data[session_id] = (state, time.time())   # overwrite = idempotent reset

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._data.pop(session_id, None)


_store = SessionStore()

def get(session_id: str) -> SessionState | None: return _store.get(session_id)
def set(session_id: str, state: SessionState) -> None: _store.set(session_id, state)
def delete(session_id: str) -> None: _store.delete(session_id)
```

### 5.2 Interview Planner — `planner.py`

```python
from models import CandidateProfile, PlannedTopic, TopicDepth


def build_plan(candidate: CandidateProfile, curriculum: dict) -> tuple[list[PlannedTopic], str]:
    curriculum_by_day = {d["day"]: d for d in curriculum["days"]}

    def lookup_module(day: int) -> dict:
        for mod in curriculum["modules"]:
            lo, hi = mod["days"]
            if lo <= day <= hi:
                return mod
        raise ValueError(f"Day {day} not in any module range")

    # ── STEP 1 — per-mission readiness map ──────────────────────────
    readiness: dict[int, tuple[str, TopicDepth]] = {}
    for m in candidate.missions:
        if m.skipped:
            readiness[m.day] = ("skipped", TopicDepth.DIAGNOSTIC)
        elif m.passed is False:
            readiness[m.day] = ("failed", TopicDepth.DIAGNOSTIC)
        elif m.passed is True:
            if m.attempts == 1:
                readiness[m.day] = ("first_try", TopicDepth.HIGH)
            elif m.attempts is not None and m.attempts <= 3:
                readiness[m.day] = ("passed_multi", TopicDepth.MEDIUM)
            else:
                readiness[m.day] = ("passed_hard", TopicDepth.LOW)

    # ── STEP 2 — select up to 7 slots from buckets ──────────────────
    # (slots 8-10 are reserved for Step 3's module-coverage additions so the
    #  final [:10] trim can never cut a coverage topic — Design Decision #17)
    selected: list[int] = []

    bucket_a = [d for d, (s, _) in readiness.items() if s in ("skipped", "failed")]
    selected.extend(bucket_a[:2])                      # cap: max 2 diagnostic topics (#15)

    bucket_b = [d for d, (s, _) in readiness.items() if s == "passed_hard"]
    selected.extend(bucket_b[:2])

    bucket_c = [d for d, (s, _) in readiness.items() if s == "passed_multi"]
    selected.extend(bucket_c[:2])

    bucket_d = [d for d, (s, _) in readiness.items() if s == "first_try"]
    selected.extend(bucket_d[: max(0, 7 - len(selected))])

    selected = list(dict.fromkeys(selected))            # de-dupe, preserve order

    if len(selected) < 7:
        for overflow in (bucket_d, bucket_b, bucket_c):
            extras = [d for d in overflow if d not in selected]
            selected.extend(extras[: 7 - len(selected)])
            if len(selected) >= 7:
                break

    if len(selected) < 7:                                # sparse candidate — pull untouched days
        all_days = {d["day"] for d in curriculum["days"]}
        attempted = {m.day for m in candidate.missions}
        for day in sorted(all_days - attempted):
            if len(selected) >= 7:
                break
            readiness[day] = ("not_attempted", TopicDepth.DIAGNOSTIC)
            selected.append(day)

    # ── STEP 3 — guarantee >= 4 modules, using the reserved slots ───
    modules_covered = {lookup_module(d)["n"] for d in selected}
    if len(modules_covered) < 4:
        for mod in curriculum["modules"]:
            if mod["n"] in modules_covered or len(modules_covered) >= 4:
                continue
            lo, hi = mod["days"]
            added = False
            for d in range(lo, hi + 1):
                if d in readiness and d not in selected:
                    selected.append(d)
                    modules_covered.add(mod["n"])
                    added = True
                    break
            if not added:
                first_day = lo
                readiness[first_day] = ("not_attempted", TopicDepth.DIAGNOSTIC)
                selected.append(first_day)
                modules_covered.add(mod["n"])

    selected = list(dict.fromkeys(selected))[:10]        # de-dupe again, clamp to 10

    # ── STEP 4 — backfill to the 8-question floor if still short ────
    if len(selected) < 8:
        remaining_d = [d for d in bucket_d if d not in selected]
        selected.extend(remaining_d[: 8 - len(selected)])

    if len(selected) < 8:
        all_days = {d["day"] for d in curriculum["days"]}
        for day in sorted(all_days - set(selected)):
            if len(selected) >= 8:
                break
            readiness.setdefault(day, ("not_attempted", TopicDepth.DIAGNOSTIC))
            selected.append(day)

    selected = list(dict.fromkeys(selected))[:10]

    # ── STEP 5 — enrich with curriculum metadata ─────────────────────
    plan: list[PlannedTopic] = []
    for day in selected:
        cur_day = curriculum_by_day[day]
        module = lookup_module(day)
        status, depth = readiness.get(day, ("not_attempted", TopicDepth.DIAGNOSTIC))
        plan.append(PlannedTopic(
            day=day, title=cur_day["title"],
            module_n=module["n"], module_title=module["title"],
            depth=depth, objectives=cur_day["objectives"], tools=cur_day["tools"],
            mission_status=status,
        ))

    # ── STEP 6 — order for a natural interview flow ──────────────────
    plan = _sort_for_interview_flow(plan)

    # ── STEP 7 — candidate tone (global signal, phrasing only) ───────
    sig = candidate.signals
    ratio = sig.missionsFirstTry / sig.missionsCompleted if sig.missionsCompleted > 0 else 0.5
    if ratio > 0.75 and candidate.member.yearsExperience >= 5:
        tone = "peer"
    elif ratio < 0.30 or candidate.member.yearsExperience <= 1:
        tone = "supportive"
    else:
        tone = "professional"

    # ── STEP 8 — invariant validation (should never fire; fails loudly) ──
    if len(plan) < 8:
        raise ValueError(f"Planner produced {len(plan)} topics, need >=8. Candidate: {candidate.member.id}")
    if len({t.module_n for t in plan}) < 4:
        raise ValueError(f"Planner covers {len({t.module_n for t in plan})} modules, need >=4. Candidate: {candidate.member.id}")

    return plan, tone


def _sort_for_interview_flow(plan: list[PlannedTopic]) -> list[PlannedTopic]:
    """Open on a MEDIUM-depth topic (comfortable, not too hard/easy). Never open
    or close on a DIAGNOSTIC topic — a rough patch shouldn't be the first or last
    impression. Close on a HIGH/MEDIUM topic for a positive finish."""
    if not plan:
        return plan

    non_diagnostic = [t for t in plan if t.depth != TopicDepth.DIAGNOSTIC]
    if not non_diagnostic:
        return plan   # degenerate case: every topic is diagnostic — nothing to protect

    opener = next((t for t in non_diagnostic if t.depth == TopicDepth.MEDIUM), non_diagnostic[0])
    remaining = [t for t in plan if t is not opener]
    closer = next((t for t in reversed(remaining) if t.depth == TopicDepth.HIGH),
                  next((t for t in reversed(remaining) if t.depth != TopicDepth.DIAGNOSTIC), remaining[-1]))
    middle = [t for t in remaining if t is not closer]
    return [opener] + middle + [closer]
```

### 5.3 LLM Client — `llm_client.py`

```python
import os
import json
from google import genai
from google.genai import types
from google.genai.errors import APIError

PRIMARY_MODEL = os.getenv("GEMINI_PRIMARY_MODEL", "gemini-3.6-flash")
FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite")


class LLMCallError(Exception):
    """Every LLM failure path terminates here — quota exhaustion on both tiers,
    timeouts, parse failures, network errors. The turn engine and feedback
    synthesizer each catch this and degrade deterministically; no raw SDK
    exception should ever escape to become an unhandled 500 (Decision #21)."""


class LLMClient:
    def __init__(self, api_key: str):
        self.client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=15_000),  # ms, constructor-level (Decision #24)
        )

    def generate(self, system_prompt: str, messages: list[dict],
                 response_schema: dict, session) -> dict:
        model = FALLBACK_MODEL if session.using_fallback else PRIMARY_MODEL
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,          # kept OUT of contents (Decision #3)
            response_mime_type="application/json",
            response_schema=response_schema,
        )
        contents = self._build_contents(messages)

        try:
            response = self.client.models.generate_content(model=model, contents=contents, config=config)
            return json.loads(response.text)
        except Exception as e:
            is_quota = (isinstance(e, APIError) and getattr(e, "code", None) == 429) \
                       or "ResourceExhausted" in type(e).__name__ or "429" in str(e)

            if is_quota and not session.using_fallback:
                session.using_fallback = True                     # sticky (Decision #23)
                try:
                    return self.generate(system_prompt, messages, response_schema, session)
                except Exception as fallback_e:
                    raise LLMCallError(
                        f"Both models exhausted. Primary: {e}. Fallback: {fallback_e}"
                    ) from fallback_e

            # Non-quota error, or already on fallback → one retry, same model
            try:
                response = self.client.models.generate_content(model=model, contents=contents, config=config)
                return json.loads(response.text)
            except Exception as retry_e:
                raise LLMCallError(f"LLM failed after retry on {model}: {retry_e}") from retry_e

    def _build_contents(self, messages: list[dict]) -> list:
        """
        Two guarantees, neither of which ever discards a real conversation turn:

          1. `contents` is never empty (Gemini rejects empty contents) — seeded
             with one synthetic anchor turn if `messages` is empty. (Decision #4)

          2. `contents` always starts with a `user` turn (Gemini requires this).
             If the real first message is `model`-role (the sliding window
             legitimately opens on the question just asked, every single topic),
             a synthetic anchor `user` turn is PREPENDED — never stripped.
             Stripping was tried in an earlier draft and rejected: it silently
             deleted the model's actual question from what the evaluator sees
             on the very next call. (Decision #5 — the final fix)
        """
        if not messages:
            messages = [{"role": "user", "content": "Begin."}]
        if messages[0].get("role") != "user":
            messages = [{"role": "user", "content": "(Interview in progress.)"}] + messages

        contents = []
        for msg in messages:
            role = "user" if msg.get("role") == "user" else "model"
            contents.append(types.Content(role=role, parts=[types.Part(text=msg["content"])]))
        return contents


# Module-level singleton, constructed once at app startup with the real key
# (Decision #31 — resolves the class-vs-bare-function ambiguity from v1-v4).
_client: LLMClient | None = None

def init_client(api_key: str) -> None:
    global _client
    _client = LLMClient(api_key=api_key)

def generate(system_prompt: str, messages: list[dict], response_schema: dict, session) -> dict:
    if _client is None:
        raise RuntimeError("llm_client.init_client() must be called at app startup")
    return _client.generate(system_prompt, messages, response_schema, session)
```

> **Unverified assumption — test this first, live, in Phase 3:** the `system_instruction` field and the two `contents` guards above are the technically-correct way to use this SDK per its documented interface, but none of it has been exercised against a real Gemini response yet. Fire one real call with a `messages` list that opens on `model`-role before building anything on top of this file. See §10.

### 5.4 Prompt Templates — `prompts.py`

```python
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
        "implementation mechanics — how specific tools were configured, what "
        "errors they hit, and practical decisions they made."
    ),
    "low": (
        "This candidate struggled significantly with this topic (4+ attempts). "
        "Ask clear, direct questions about core concepts and basic tool usage. "
        "Keep it approachable — avoid abstract trade-off framing."
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
    "passed_hard": "Passed, but only after several attempts — this was a struggle.",
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
TOPIC: Day {topic.day} — "{topic.title}"
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
        next_block = f"""Day {next_topic.day} — "{next_topic.title}"
Module: {next_topic.module_title}
Tools: {", ".join(next_topic.tools)}
Objectives:
{_objectives_bulleted(next_topic.objectives)}
Candidate performance: {_MISSION_STATUS_TEXT.get(next_topic.mission_status, "Unknown.")}
Depth: {DEPTH_INSTRUCTIONS[next_topic.depth.value]}"""
    else:
        next_block = ("None — this is the final topic. If you decide to advance, "
                      "wrap up with a brief closing remark instead of asking a new question.")

    return f"""You are a senior technical interviewer mid-interview with {member.name}
({member.jobRole}, {member.yearsExperience} years experience).

{TONE_INSTRUCTIONS[tone]}

══════════════════════════════════════════════════════════════
CURRENT TOPIC (evaluate the candidate's answer against THIS):
══════════════════════════════════════════════════════════════
Day {current_topic.day} — "{current_topic.title}"
Module: {current_topic.module_title}
Tools: {", ".join(current_topic.tools)}
Objectives:
{_objectives_bulleted(current_topic.objectives)}
Candidate performance: {_MISSION_STATUS_TEXT.get(current_topic.mission_status, "Unknown.")}
Depth: {DEPTH_INSTRUCTIONS[current_topic.depth.value]}

══════════════════════════════════════════════════════════════
NEXT TOPIC (ask about THIS only if you decide to advance):
══════════════════════════════════════════════════════════════
{next_block}

══════════════════════════════════════════════════════════════

PRIOR TOPICS (summary only, for conversational continuity):
{summaries_text}

YOUR TASK — respond as JSON with these exact fields:

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
  rate "missed", decide "advance", and move on gracefully — do not pressure them."""


def build_feedback_prompt(candidate, evaluations_formatted: str) -> str:
    member = candidate.member
    return f"""Summarize the completed technical interview for {member.name}
({member.jobRole}, {member.yearsExperience} years experience).

INTERVIEW EVALUATIONS:
{evaluations_formatted}

Generate a structured feedback object as JSON with these exact fields:

- "summary": 2-3 sentence overall assessment of interview performance.
- "strengths": array of 3-5 specific strengths. Each MUST cite a specific Day
  number and title, e.g. "Day 22 — Multi-Agent Orchestration: clearly
  explained router agent delegation patterns."
- "gaps": array of 2-4 specific gaps. Each MUST cite a specific Day number
  and title. Do NOT give generic advice — cite what was actually missed.
- "next": array of 2-4 actionable next steps. Each MUST reference a specific
  Day number and suggest a concrete exercise, e.g. "Revisit Day 29
  objectives: implement Prometheus metrics collection in a FastAPI app."

RULES:
- Every item in strengths/gaps/next MUST reference a specific Day number and title.
- Do NOT invent tools or topics that were not covered in the interview.
- Be encouraging but honest — gaps are learning opportunities, not failures.
- "next" steps must be concrete exercises, not vague recommendations like "study more"."""
```

### 5.5 Turn Engine — `turn_engine.py`

```python
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
    except llm_client.LLMCallError:
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
    except llm_client.LLMCallError:
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
```

### 5.6 Feedback Synthesizer — `feedback_synthesizer.py`

```python
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
```

### 5.7 FastAPI Application — `main.py`

```python
import json
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from models import InterviewRequest, InterviewResponse, SessionState
import planner
import turn_engine
import session_store
import llm_client

curriculum_data: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global curriculum_data
    with open("curriculum.json") as f:
        curriculum_data = json.load(f)
    llm_client.init_client(api_key=os.environ["GEMINI_API_KEY"])
    yield


app = FastAPI(title="AI Interview Agent", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(HTTPException)
async def http_exc_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.detail if isinstance(exc.detail, dict) else {"error": "ERROR", "detail": str(exc.detail)},
    )

@app.exception_handler(ValueError)
async def value_error_handler(request, exc):
    return JSONResponse(status_code=500, content={"error": "INTERNAL_ERROR", "detail": str(exc)})


@app.post("/api/interview", response_model=InterviewResponse, response_model_exclude_none=True)
async def interview(request: InterviewRequest):
    # CASE 1 — START (candidate present)
    if request.candidate is not None:
        plan, tone = planner.build_plan(request.candidate, curriculum_data)
        session = SessionState(
            session_id=request.sessionId, candidate=request.candidate,
            plan=plan, candidate_tone=tone,
        )
        session_store.set(request.sessionId, session)      # overwrite = idempotent reset (Decision #14 sibling)
        reply = turn_engine.generate_first_question(session)
        return InterviewResponse(reply=reply, done=False)

    # CASE 2 — TURN (message present)
    if request.message is not None:
        session = session_store.get(request.sessionId)
        if session is None:
            raise HTTPException(status_code=400, detail={
                "error": "INVALID_SESSION",
                "detail": "Session not found. Send candidate data to start a new interview.",
            })
        if session.is_done:
            raise HTTPException(status_code=400, detail={
                "error": "SESSION_COMPLETE",
                "detail": "Interview already completed for this session.",
            })
        return turn_engine.process_turn(session, request.message)

    # CASE 3 — MALFORMED (neither candidate nor message)
    raise HTTPException(status_code=400, detail={
        "error": "BAD_REQUEST",
        "detail": "Include 'candidate' to start or 'message' to continue.",
    })
```

---

## 6. Dependencies & Environment

**`requirements.txt`**
```
fastapi>=0.115.0
uvicorn[standard]>=0.34.0
pydantic>=2.0.0
google-genai>=1.14.0
python-dotenv>=1.0.0
pytest>=8.0.0
pytest-asyncio>=0.24.0
httpx>=0.28.0
```
Zero agent frameworks. Minimal footprint.

**`.env.example`**
```
GEMINI_API_KEY=your_google_ai_studio_key_here
GEMINI_PRIMARY_MODEL=gemini-3.6-flash
GEMINI_FALLBACK_MODEL=gemini-3.5-flash-lite
```

---

## 7. Test Suite

```bash
pytest tests/ -v --tb=short
```

### `test_api_contract.py` — PRD §11 compliance

| # | Test | Verifies |
|---|---|---|
| 1 | `test_start_done_false_no_feedback` | `done==False`, non-empty `reply` |
| 2 | `test_min_8_questions` | ≥8 turn responses before `done:true` |
| 3 | `test_min_4_days` | ≥4 distinct curriculum days covered |
| 4 | `test_followup_references_answer` | Reply references content from the candidate's prior answer |
| 5 | `test_final_all_feedback_fields` | `done:true` + all 4 feedback fields non-empty |
| 6 | `test_feedback_cites_days` | `gaps`/`next` contain a `Day \d+` pattern |
| 7 | `test_different_candidates_different_depth` | CAND-003 (peer, HIGH-heavy) vs CAND-010 (supportive, DIAGNOSTIC/LOW-heavy) → measurably different question framing |
| 8 | `test_skipped_mission_touched` | CAND-001, Day 29 skipped → interview touches it lightly |
| 9 | `test_no_hallucinations` | All tool/topic mentions in replies exist in `curriculum.json` |
| 10 | `test_malformed_answer_survives` | `""`, `"idk"`, `"x"` → valid JSON, no 500 |
| 11 | `test_final_reply_is_closing` | `done:true` reply is a closing statement, not a question |
| 12 | `[NEW]` `test_feedback_key_absent_when_not_done` | `"feedback" not in response.json()` when `done==False` (byte-for-byte spec match, not just `null`) |

### `test_edge_cases.py`

| Test | Verifies |
|---|---|
| `test_unknown_session_400` | Clean dict-based 400, not 500 |
| `test_empty_body_400` | Clean dict-based 400 |
| `test_resend_candidate_resets` | Same `sessionId` + new `candidate` → fresh session |
| `test_turn_after_done_400` | Clean 400 |
| `test_long_answer` | 2000-char answer → valid response |
| `test_error_response_is_dict` | Error body is `{error, detail}`, not double-encoded |

### `test_planner.py`

| Test | Verifies |
|---|---|
| `test_min_8_topics` | Any candidate → `len(plan) >= 8` |
| `test_max_10_topics` | Any candidate → `len(plan) <= 10` |
| `test_min_4_modules` | Any candidate → ≥4 distinct modules |
| `test_max_2_skipped_failed` | Max 2 topics with `mission_status in ("skipped","failed")` |
| `test_depth_first_try` | 1 attempt → `HIGH` |
| `test_depth_low` | ≥4 attempts → `LOW` |
| `test_depth_skipped` | Skipped → `DIAGNOSTIC` |
| `test_sparse_candidate` | CAND-011 (5 skips, 14 completed) → still ≥8 topics |
| `test_module_concentrated_candidate` | Candidate in only 2 modules → plan still ≥4 modules |
| `test_tone_peer` | High ratio + senior (CAND-003) → `"peer"` |
| `test_tone_supportive` | Low ratio (CAND-010) → `"supportive"`, even at 20 yrs experience |
| `[NEW]` `test_all_first_try_candidate` | CAND-018 (ratio 1.0, buckets B/C empty) → planner still succeeds |

### `test_turn_engine.py` — `[NEW: never actually enumerated in v1-v4, filled in here]`

| Test | Verifies |
|---|---|
| `test_follow_up_cap_enforced` | 2nd `follow_up` from the LLM on the same topic gets overridden to `advance` |
| `test_decision_override_advances_index` | `current_topic_index` actually increments after the override (catches the exact silent-infinite-loop bug found in review) |
| `test_llm_failure_graceful_degrade` | Mock `LLMCallError` → deterministic reply + forced advance, no crash |
| `test_completion_discards_llm_reply` | On `done:true`, the returned `reply` is the deterministic closing line, never the LLM's raw output |
| `test_sliding_window_resets_on_advance` | `current_topic_history` is empty immediately after an `advance`, then contains only the new question |
| `test_fallback_sticky` | Simulated 429 once → `using_fallback` stays `True` on the next call without re-attempting primary |

---

## 8. Manual Verification Scenarios (real candidates)

| # | Scenario | Candidate | What it proves |
|---|---|---|---|
| 1 | **Golden path** | CAND-001 Sarah Johnson | Day 29 (skipped) surfaces diagnostically in the plan and in final `gaps` |
| 2 | **Calibration contrast** | CAND-003 (ratio 0.968, exp 6 → `peer`, HIGH-heavy) vs CAND-010 (ratio 0.043, exp 20, 3 failed + 2 skipped → `supportive`, DIAGNOSTIC/LOW-heavy) | Depth AND tone both visibly diverge — and confirms `supportive` correctly applies even to a 20-year veteran when the per-topic signal is weak |
| 3 | **Cap stress test** | CAND-016 Isabella Rossi (3 failed + 2 skipped = 5 diagnostic-eligible days) | Plan contains exactly the capped **2**, not all 5 |
| 4 | **Sparse candidate** | CAND-011 Mia Alvarez (5 skips, only 14 `missionsCompleted`) | Plan still reaches 8–10 topics via `not_attempted` backfill; still ≥4 modules |
| 5 | **Saturated mastery** | CAND-018 Diane Foster (31/31 first-try, ratio 1.0, exp 4) | Buckets B (`passed_hard`) and C (`passed_multi`) are completely empty — planner must not error. Also: exp=4 < 5 means she does **not** qualify for `peer` tone despite a perfect ratio — resolves to `professional`, confirming the tone rule is a genuine AND, not just ratio-driven. |
| 6 | **Junior but strong** | CAND-007 Ethan Brooks (exp 0, ratio 0.815) | `exp <= 1` forces `supportive` even though the ratio alone would suggest `peer` — confirms inexperience overrides raw performance in the tone rule |
| 7 | **Resilience** | Any candidate, 5× `"I don't know"` | Interview still completes with valid feedback, no loop |
| 8 | **Error path** | Bad `sessionId`, empty body | Clean JSON errors, no 500 |

---

## 9. Execution Order

```
Phase 1 — Foundation (no LLM)                              ≈ 45 min
  ├── models.py
  ├── session_store.py
  └── curriculum.json loader (via lifespan)

Phase 2 — Planning Engine (no LLM)                          ≈ 60 min
  ├── planner.py
  └── tests/test_planner.py

Phase 3 — LLM Integration                                   ≈ 60 min
  ├── llm_client.py
  ├── FIRST: fire one live test call to confirm the system_instruction /
  │   contents-ordering assumptions (§10) before building further on top
  ├── prompts.py
  └── .env.example

Phase 4 — Core Engine                                       ≈ 90 min
  ├── turn_engine.py
  ├── feedback_synthesizer.py
  └── tests/test_turn_engine.py

Phase 5 — API Surface + Contract Tests                      ≈ 60 min
  ├── main.py
  ├── requirements.txt
  ├── tests/test_api_contract.py
  └── tests/test_edge_cases.py

Phase 6 — Polish (optional)                                 ≈ 45 min
  ├── Prompt tuning from live outputs
  ├── README.md
  └── Optional: ui.py (Streamlit), Dockerfile

Total: ≈ 6 hours (padded 30-60 min over the earlier 5-6h estimate to cover
the Phase 3 live-verification step this document adds).
```

---

## 10. Residual Risks & Day-Of Action Items

1. **Unverified Gemini turn-structure assumptions.** `system_instruction`, the non-empty-`contents` guard, and the prepend-not-strip leading-turn guard are all the technically-correct reading of the SDK's documented interface — but none have been exercised against a live response. **Action: fire one real call in Phase 3 before writing Phase 4.**
2. **Free-tier quota numbers move.** Check `ai.google.dev/pricing` the morning of the hackathon.
3. **Model availability.** `gemini-3.6-flash` / `gemini-3.5-flash-lite` are confirmed current as of this writing — but Google's 2026 deprecation cadence has been aggressive (2.0 and 2.5 both retired within the same year). Reconfirm day-of.
4. **Module-coverage fallback (Step 3) doesn't re-check the skip/fail cap.** In a rare case, the module-coverage backfill could theoretically add a 3rd diagnostic-status day if that's the only day the candidate touched in an uncovered module. Low probability given the real data (most candidates cover 6-9 of the 8 modules already through their normal missions), documented rather than fixed to avoid an unreviewed algorithm change this late.
5. **Tone granularity.** The `supportive` bucket still can't fully distinguish "gentle because new" from "gentle because this specific material was hard for an expert" — the instruction text was softened to reduce the risk, but the underlying 3-bucket system is a hackathon-appropriate simplification, not a fully solved UX problem.
6. **Per-call token cost grows with topic count.** Each turn re-states the full current+next topic blocks plus the running `topic_summaries` list. Fine at 8-10 topics; would need actual trimming if this were ever extended well beyond that.
7. **No load/concurrency testing.** In-memory `dict` + `threading.Lock` is correct for a hackathon demo's traffic pattern, not validated under concurrent load.

---

## 11. Pre-Submission Checklist (PRD §11)

- [ ] Fresh session → first response has `done: false`, **no `feedback` key present at all** (not just `null` — confirms `response_model_exclude_none=True` is working)
- [ ] At least 8 total questions asked across a full run
- [ ] Those questions span ≥4 distinct curriculum days (and ≥4 distinct modules)
- [ ] At least one visible follow-up that clearly references the candidate's prior answer
- [ ] Final response has `done: true` + all four `feedback` fields populated, and `reply` is a closing statement, not a question
- [ ] `gaps`/`next` reference specific curriculum days, not generic advice
- [ ] CAND-003 vs. CAND-010 produce visibly different question depth AND tone
- [ ] Run against CAND-001 — confirm Day 29 (skipped) is touched lightly, not skipped entirely or over-penalized
- [ ] Run against CAND-016 — confirm only 2 of her 5 diagnostic-eligible days appear
- [ ] No hallucinated tools/topics outside `curriculum.json`
- [ ] Endpoint survives a malformed/short candidate answer without breaking the JSON contract
- [ ] Endpoint survives a simulated 429 on the primary model (fallback engages and stays sticky)
- [ ] Re-sending `candidate` on an existing `sessionId` cleanly resets the session
