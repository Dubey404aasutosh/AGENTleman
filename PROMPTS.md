# PROMPTS.md — AI Interview Agent: Vibe-Coding Process Log

This file documents the prompt history used to design, build, audit, and polish the AI Interview Agent submission, across two AI assistant sessions and six build phases. It is provided as verification that this was genuinely developed through iterative AI-assisted engineering, not a single one-shot generation.

**Process summary:** Architecture and PRD were developed in an initial planning session. Implementation went through 4 full review rounds (v1 → v4 → FINAL) before any code was written, each round catching and fixing real bugs. The actual build then proceeded phase-by-phase (1–6), with every phase requiring real code + real test output + (from Phase 3 onward) real live-API evidence before being marked approved. A dedicated post-Phase-5 audit pass found and fixed 5 additional issues that had passed all automated tests but were wrong in ways only a live trace or hand-verification against real data could catch.

---

## Stage 0 — Problem Framing & Architecture (prior session)

- Initial PS discussion: reframing "build the interviewer, not the interview" into a concrete architecture (interview planner → session state → turn engine → feedback synthesizer).
- "o picking the LLM/framework?" — comparing FastAPI vs. agent frameworks (LangChain/CrewAI), justifying a plain-FastAPI, single-combined-LLM-call design.
- "use gemini free api key" — pivoting model choice from Groq/GPT-4o-mini to Gemini Flash for free-tier sustainability.
- "give me prd for hackathon project" — produced `PRD-AI-Interview-Agent.md`.

## Stage 1 — Continuity & PRD Review (this session)

- Re-established full context from a screenshot of the prior session's architecture discussion, plus the uploaded PRD, technical spec, `curriculum.json`, and `candidates.json`.
- *"How do you feel about the 3-tier candidate calibration matrix? Does the API contract match your vision completely?"* — surfaced the per-topic-vs-global calibration conflict and 3 spec ambiguities (start bundling, `done` authority, session reset) that shaped every later design decision.

## Stage 2 — Implementation Plan Review Rounds (v1 → FINAL)

Four full implementation-plan documents were submitted in sequence, each independently reviewed line-by-line before any code was written:

- **v1 review** → found: dead Gemini model names (`gemini-2.0-flash` already shut down), planner selecting too few topics to guarantee the 8-question floor.
- **v2 review** → found: uncapped skipped/failed bucket, double-JSON-encoded error responses, missing `system_instruction` usage causing consecutive `user`-role turns.
- **v3 review** → found: the turn engine could end mid-question when completion triggered during a `follow_up` decision; a second quota-exhaustion path could crash the session with an unhandled exception.
- **v4 review** → found: `contents` sent to Gemini could be empty or start with the wrong role, risking `400` errors on the SDK's actual interface.
- *"is this perfect?? / how is this? / v3 / now see"* — the recurring review prompts across all four rounds, each answered with a full trace-through rather than a surface read.

## Stage 3 — Consolidation

- *"draft an implementation plan covering all points instruction instance problem solution all implementation context each and everything for the prototype... use you max skill knowledge and power you have penalty of time"* — request to merge all four review rounds plus the PRD/spec into one authoritative, build-ready document.
- Before writing it: **verified every specific data claim (candidate IDs, ratios, distributions) directly against the actual uploaded `curriculum.json`/`candidates.json`** rather than trusting prior assumptions — found and corrected one numeric error (depth-tier distribution), confirmed the rest.
- Produced `AI-Interview-Agent-Implementation-Plan-FINAL.md` — 34 numbered design decisions, complete component code, full test suite spec, manual verification scenarios grounded in real candidates, residual risks section.

## Stage 4 — Phase-by-Phase Build (Phases 1–5)

Each phase followed the same required format: real source code + real `pytest` output, escalating to real live-API evidence from Phase 3 onward.

- **Phase 1 (Foundation)** — `models.py`, `session_store.py` — approved after TTL eviction and round-trip state tests confirmed.
- **Phase 2 (Planner)** — `planner.py`, 15 tests — approved as a verbatim match to plan spec.
- **Phase 3 (LLM Integration)** — `llm_client.py`, `prompts.py` — required a live Gemini call before being marked closed (not just mocked tests). Surfaced and fixed a genuine 3-call quota-exhaustion path via hand-tracing the code (not assumed from the mock passing).
- **Phase 4 (Core Engine)** — `turn_engine.py`, `feedback_synthesizer.py`, 10 new tests — approved after 5 specific behaviors were traced by hand against source.
- **Phase 5 (API Surface)** — `main.py`, `test_api_contract.py`, `test_edge_cases.py` — went through **6 review rounds** within this single phase:
  1. Initial submission (44 tests) → found a live "Environment Setup" anomaly that didn't match the plan's own topic ordering.
  2. Root-cause trace → determined the fallback text couldn't produce that output; identified stale `uvicorn` process as the real cause; caught a tautological test assertion (`assert tool in valid_tools`) three separate times before it was properly removed rather than papered over.
  3. `RequestValidationError` contract gap found (422 default shape vs. the project's `{error, detail}` contract) and fixed.
  4. `requirements.txt` version-floor and missing-dependency issues (`google-genai>=0.1.0` too loose, `httpx` missing) — caught twice before fully resolved.
  5. Fresh clean-restart live smoke test requested and provided as final proof, not inferred.
  6. Final verification: real pytest output requested explicitly after a "walkthrough" was submitted without one — 44/44 confirmed.

## Stage 5 — Post-Phase-5 Audit

*"give me prompt for your verifying problem and error you see and to fix"* / *"do it will use api token?"* — an explicit, budget-aware decision to spend real Gemini API calls on live verification rather than relying solely on mocks.

Audit surfaced and fixed, in order:
1. Both-models-exhausted latency (3 calls → 2 calls, fail-fast fix).
2. A live tone-contrast comparison that was silently comparing one real reply against a hardcoded fallback template — caught by recognizing the fallback text verbatim, not by any test failing.
3. A misattributed plan-composition explanation for CAND-011 (depth values were claimed to come from "backfill" when 3 of 4 cited days were actually real mission history) — corrected only after raw mission data was printed and cross-checked.
4. A real hallucination: live output cited "Day 29 — Building Custom Query Routers & RAG Pipelines" (real title: "Monitoring, Logging & Observability") — fixed with prompt tightening **and** a deterministic post-hoc title-correction guard, not prompt-only.
5. A feedback-summary/array count mismatch in the deterministic fallback path, initially "fixed" in a way that only worked by coincidence (test used exactly 4 items, matching the array cap) — caught by hand-checking the capped-slice logic, not by the test passing.
6. A misattributed checklist citation (Item 7's "proof" cited opener-question depth, which is always MEDIUM by the sort algorithm regardless of candidate, not actual per-candidate calibration) — corrected by re-citing against full plan-depth composition instead.

Final closing prompt requested one **clean** (non-canned-input) reference transcript for CAND-001, since every prior CAND-001 run had involved either a stale process or scripted/mismatched test inputs.

## Stage 6 — Phase 6: Polish & Submission

- *"give me specialized prompt for phase 6"* → README, fresh-install sanity check from `requirements.txt` alone, one new cold-start candidate (CAND-004), Docker/Streamlit as explicit optional items.
- *"remove docker and streamlit ui it is boring use modern web design playful and claymorphism"* → replaced with a real claymorphism single-page frontend requirement (soft dual shadows, pastel palette, micro-interactions, candidate picker, multi-card feedback dashboard), served via FastAPI static routes.
- Review of the resulting frontend screenshot: caught inaccurate UI copy ("10-turn" vs. the actual 8–10 variable floor), asked for confirmation that the `feedback`-key-absence contract was handled correctly in the JS (not assumed), and requested the actual CAND-004 live transcript rather than a summary claim.
- *"create at least a landing page... claymorphism cards, course catalog preview, parallax glassmorphism framer svg scroll trigger"* → separate marketing landing page spec: dual claymorphism (resting content) / glassmorphism (floating overlays) design system, layered parallax, scroll-triggered SVG narrative section, reduced-motion fallback.

---

## What this process demonstrates

- No design decision, plan section, or piece of code in this submission was accepted on the first pass. Every phase required either real test output, real live-API evidence, or a hand-trace against the actual source before being marked approved.
- Multiple genuine bugs were caught specifically because outputs were checked against ground truth (the real `curriculum.json`/`candidates.json`, the real SDK behavior, the real capped-slice math) rather than because a test suite went green — several of these bugs *did* pass their own tests initially, and were only found by independent verification.
- The two most recent additions (claymorphism app UI, glassmorphism/parallax landing page) followed the same pattern: a design spec was requested, a build was returned, and the result was checked against the spec (UI copy accuracy, contract handling) before acceptance rather than taken at face value.
