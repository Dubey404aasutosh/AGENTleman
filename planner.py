"""
Interview Planner module (Component 5.2, Phase 2).
Topic selection, depth calibration per topic, and global tone assessment.
"""

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
