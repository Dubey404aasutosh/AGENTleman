import json
import pytest
from models import (
    CandidateProfile,
    CandidateMember,
    CandidateMission,
    CandidateSignals,
    PlannedTopic,
    TopicDepth,
)
from planner import build_plan, _sort_for_interview_flow


@pytest.fixture
def curriculum():
    with open("curriculum.json") as f:
        return json.load(f)


@pytest.fixture
def candidates_data():
    with open("candidates.json") as f:
        raw = json.load(f)["candidates"]
        return {c["member"]["id"]: CandidateProfile(**c) for c in raw}


def test_min_8_topics(candidates_data, curriculum):
    """Any candidate -> len(plan) >= 8."""
    for cand_id, cand in candidates_data.items():
        plan, _ = build_plan(cand, curriculum)
        assert len(plan) >= 8, f"Candidate {cand_id} plan has {len(plan)} topics, expected >= 8"


def test_max_10_topics(candidates_data, curriculum):
    """Any candidate -> len(plan) <= 10."""
    for cand_id, cand in candidates_data.items():
        plan, _ = build_plan(cand, curriculum)
        assert len(plan) <= 10, f"Candidate {cand_id} plan has {len(plan)} topics, expected <= 10"


def test_min_4_modules(candidates_data, curriculum):
    """Any candidate -> >=4 distinct modules."""
    for cand_id, cand in candidates_data.items():
        plan, _ = build_plan(cand, curriculum)
        modules_covered = {t.module_n for t in plan}
        assert len(modules_covered) >= 4, f"Candidate {cand_id} covers {len(modules_covered)} modules, expected >= 4"


def test_max_2_skipped_failed(candidates_data, curriculum):
    """CAND-016 has 3 failed + 2 skipped = 5 diagnostic-eligible days -> max 2 diagnostic topics in plan."""
    cand_016 = candidates_data["CAND-016"]
    plan, _ = build_plan(cand_016, curriculum)
    diagnostic_topics = [t for t in plan if t.mission_status in ("skipped", "failed")]
    assert len(diagnostic_topics) == 2, f"CAND-016 has {len(diagnostic_topics)} diagnostic topics, expected max 2"

    # Also verify across all candidates
    for cand_id, cand in candidates_data.items():
        p, _ = build_plan(cand, curriculum)
        diags = [t for t in p if t.mission_status in ("skipped", "failed")]
        assert len(diags) <= 2, f"Candidate {cand_id} has {len(diags)} diagnostic topics, expected <= 2"


def test_depth_first_try(candidates_data, curriculum):
    """1 attempt -> HIGH depth."""
    cand_003 = candidates_data["CAND-003"]
    plan, _ = build_plan(cand_003, curriculum)
    first_try_topics = [t for t in plan if t.mission_status == "first_try"]
    assert len(first_try_topics) > 0
    for topic in first_try_topics:
        assert topic.depth == TopicDepth.HIGH


def test_depth_low(candidates_data, curriculum):
    """>=4 attempts -> LOW depth."""
    cand_004 = candidates_data["CAND-004"]
    plan, _ = build_plan(cand_004, curriculum)
    passed_hard_topics = [t for t in plan if t.mission_status == "passed_hard"]
    assert len(passed_hard_topics) > 0
    for topic in passed_hard_topics:
        assert topic.depth == TopicDepth.LOW


def test_depth_skipped(candidates_data, curriculum):
    """Skipped mission -> DIAGNOSTIC depth."""
    cand_001 = candidates_data["CAND-001"]
    plan, _ = build_plan(cand_001, curriculum)
    skipped_topics = [t for t in plan if t.mission_status == "skipped"]
    assert len(skipped_topics) > 0
    for topic in skipped_topics:
        assert topic.depth == TopicDepth.DIAGNOSTIC
        assert topic.day == 29  # CAND-001 skipped Day 29


def test_sparse_candidate(candidates_data, curriculum):
    """CAND-011 (5 skips, 14 completed) -> still >= 8 topics and >= 4 modules."""
    cand_011 = candidates_data["CAND-011"]
    plan, tone = build_plan(cand_011, curriculum)
    assert len(plan) >= 8
    assert len(plan) <= 10
    assert len({t.module_n for t in plan}) >= 4


def test_module_concentrated_candidate(candidates_data, curriculum):
    """Candidate with missions in few modules -> plan still >= 4 modules."""
    cand_003 = candidates_data["CAND-003"]  # Missions span 4 modules
    plan, _ = build_plan(cand_003, curriculum)
    assert len({t.module_n for t in plan}) >= 4


def test_tone_peer(candidates_data, curriculum):
    """High ratio + senior (CAND-003: 0.968 ratio, 6 yrs) -> 'peer'."""
    cand_003 = candidates_data["CAND-003"]
    _, tone = build_plan(cand_003, curriculum)
    assert tone == "peer"


def test_tone_supportive(candidates_data, curriculum):
    """Low ratio (CAND-010: 0.043 ratio, 20 yrs) -> 'supportive'."""
    cand_010 = candidates_data["CAND-010"]
    _, tone = build_plan(cand_010, curriculum)
    assert tone == "supportive"


def test_all_first_try_candidate(candidates_data, curriculum):
    """CAND-018 (ratio 1.0, buckets B/C empty) -> planner still succeeds."""
    cand_018 = candidates_data["CAND-018"]
    plan, tone = build_plan(cand_018, curriculum)
    assert len(plan) >= 8
    assert len(plan) <= 10
    assert len({t.module_n for t in plan}) >= 4
    # All missions passed on first try: buckets B (passed_hard) and C (passed_multi) are empty
    assert tone == "professional"  # ratio=1.0 > 0.75 but yrsExperience=4 < 5


def test_module_concentrated_candidate_near_cap(curriculum):
    """
    Construct a synthetic candidate whose real missions concentrate in only 2-3 modules
    and whose bucket-only selection already fills 7 slots before module-coverage runs.
    Confirm the plan still ends up >= 4 modules and <= 10 topics (and >= 8 topics).
    """
    # 7 missions concentrating in Modules 1, 2, 3
    missions = [
        CandidateMission(day=1, title="Env 1", passed=True, attempts=1),
        CandidateMission(day=2, title="Env 2", passed=True, attempts=1),
        CandidateMission(day=3, title="Env 3", passed=True, attempts=1),
        CandidateMission(day=4, title="Data 1", passed=True, attempts=1),
        CandidateMission(day=5, title="Data 2", passed=True, attempts=1),
        CandidateMission(day=6, title="Data 3", passed=True, attempts=1),
        CandidateMission(day=7, title="Vector 1", passed=True, attempts=1),
    ]
    cand = CandidateProfile(
        member=CandidateMember(
            id="SYNTH-CONCENTRATED",
            name="Synthetic Candidate",
            jobRole="Software Engineer",
            yearsExperience=3,
            education="BS CS",
            status="COMPLETED",
        ),
        missions=missions,
        signals=CandidateSignals(
            commitDays=7, missionsCompleted=7, missionsFirstTry=7
        ),
    )

    plan, tone = build_plan(cand, curriculum)

    assert len(plan) >= 8
    assert len(plan) <= 10
    modules_covered = {t.module_n for t in plan}
    assert len(modules_covered) >= 4


def test_sort_for_interview_flow(candidates_data, curriculum):
    """
    Verify _sort_for_interview_flow behavior across all real candidate plans:
    1. Opener is MEDIUM depth if available, or first non-diagnostic topic.
    2. Opener and closer are never DIAGNOSTIC topics (unless all topics are diagnostic).
    3. Closer is HIGH depth if available, or non-diagnostic topic.
    """
    for cand_id, cand in candidates_data.items():
        plan, _ = build_plan(cand, curriculum)

        non_diags = [t for t in plan if t.depth != TopicDepth.DIAGNOSTIC]
        if non_diags:
            assert plan[0].depth != TopicDepth.DIAGNOSTIC, f"Candidate {cand_id} opened on DIAGNOSTIC"
            assert plan[-1].depth != TopicDepth.DIAGNOSTIC, f"Candidate {cand_id} closed on DIAGNOSTIC"


def test_sort_for_interview_flow_edge_cases():
    """
    Directly tests _sort_for_interview_flow on synthetic plans to verify:
    1. Easy case (>=3 non-diagnostic topics): opener is MEDIUM, closer is HIGH/non-diagnostic.
    2. Scarce case (1 non-diagnostic topic): opener is non-diagnostic, but closer falls back
       to remaining[-1] (which is DIAGNOSTIC) per the algorithm's fallback chain:
       HIGH -> any non-diagnostic -> remaining[-1].
    3. Degenerate case (0 non-diagnostic topics / all DIAGNOSTIC): returns plan as-is.
    """
    def make_topic(day, depth):
        return PlannedTopic(
            day=day, title=f"Day {day}", module_n=1, module_title="Mod",
            depth=depth, objectives=[], tools=[], mission_status="passed",
        )

    # 1. Easy case: 3 non-diagnostic (MEDIUM, HIGH, LOW) + 2 DIAGNOSTIC
    t_med = make_topic(1, TopicDepth.MEDIUM)
    t_high = make_topic(2, TopicDepth.HIGH)
    t_low = make_topic(3, TopicDepth.LOW)
    t_diag1 = make_topic(4, TopicDepth.DIAGNOSTIC)
    t_diag2 = make_topic(5, TopicDepth.DIAGNOSTIC)

    plan_easy = [t_diag1, t_med, t_high, t_diag2, t_low]
    sorted_easy = _sort_for_interview_flow(plan_easy)
    assert sorted_easy[0].depth == TopicDepth.MEDIUM
    assert sorted_easy[-1].depth == TopicDepth.HIGH

    # 2. Scarce case: only 1 non-diagnostic topic (MEDIUM) + 3 DIAGNOSTIC
    plan_scarce = [t_diag1, t_med, t_diag2, make_topic(6, TopicDepth.DIAGNOSTIC)]
    sorted_scarce = _sort_for_interview_flow(plan_scarce)
    assert sorted_scarce[0].depth == TopicDepth.MEDIUM
    # Opener consumed the only non-diagnostic topic (t_med), so remaining contains ONLY diagnostic topics.
    # The closer fallback chain (HIGH -> non-diagnostic -> remaining[-1]) lands on remaining[-1] (DIAGNOSTIC).
    assert sorted_scarce[-1].depth == TopicDepth.DIAGNOSTIC

    # 3. Degenerate case: all 4 topics are DIAGNOSTIC
    plan_all_diag = [t_diag1, t_diag2, make_topic(6, TopicDepth.DIAGNOSTIC), make_topic(7, TopicDepth.DIAGNOSTIC)]
    sorted_all_diag = _sort_for_interview_flow(plan_all_diag)
    assert len(sorted_all_diag) == 4
    assert all(t.depth == TopicDepth.DIAGNOSTIC for t in sorted_all_diag)
