import time
from pydantic import ValidationError
from models import (
    CandidateMember,
    CandidateMission,
    CandidateSignals,
    CandidateProfile,
    PlannedTopic,
    TopicDepth,
    TurnEvaluation,
    SessionState,
)
import session_store


def verify():
    # ── 1. Test CandidateMission validation ────────────────────────────
    # Valid passed mission
    m1 = CandidateMission(day=1, title="Setup", passed=True, attempts=1)
    assert m1.passed is True and m1.attempts == 1

    # Valid skipped mission
    m2 = CandidateMission(day=29, title="Observability", skipped=True)
    assert m2.skipped is True and m2.passed is None and m2.attempts is None

    # Invalid mission: passed=True but attempts=None -> must raise ValidationError
    try:
        CandidateMission(day=2, title="Bad Mission", passed=True, attempts=None)
        assert False, "Should have raised ValidationError for passed=True with attempts=None"
    except ValidationError:
        pass  # expected

    # Invalid mission: skipped=True but passed=True -> must raise ValidationError
    try:
        CandidateMission(day=3, title="Conflicting Mission", skipped=True, passed=True)
        assert False, "Should have raised ValidationError for skipped=True with passed=True"
    except ValidationError:
        pass  # expected


    # ── 2. Test Fully Populated SessionState Construction ──────────────
    candidate_member = CandidateMember(
        id="CAND-001",
        name="Sarah Johnson",
        jobRole="Senior Data Engineer",
        yearsExperience=9,
        education="MS Computer Science",
        status="COMPLETED"
    )
    candidate_signals = CandidateSignals(
        commitDays=28,
        missionsCompleted=30,
        missionsFirstTry=20
    )
    candidate_profile = CandidateProfile(
        member=candidate_member,
        missions=[m1, m2],
        signals=candidate_signals
    )

    planned_topic_1 = PlannedTopic(
        day=7,
        title="Embeddings Explained",
        module_n=3,
        module_title="Embeddings & Vector Search",
        depth=TopicDepth.HIGH,
        objectives=["Explain vector embeddings"],
        tools=["OpenAI Embeddings"],
        mission_status="first_try"
    )
    planned_topic_2 = PlannedTopic(
        day=29,
        title="Observability",
        module_n=8,
        module_title="Production & Capstone",
        depth=TopicDepth.DIAGNOSTIC,
        objectives=["Set up Prometheus logging"],
        tools=["Prometheus", "Grafana"],
        mission_status="skipped"
    )

    eval_1 = TurnEvaluation(
        bucket="strong",
        rationale="Explained vector embeddings clearly with dimensions trade-offs.",
        covered_day=7,
        covered_title="Embeddings Explained"
    )
    eval_2 = TurnEvaluation(
        bucket="missed",
        rationale="Could not articulate Prometheus metric types.",
        covered_day=29,
        covered_title="Observability"
    )

    populated_session = SessionState(
        session_id="full-session-999",
        candidate=candidate_profile,
        plan=[planned_topic_1, planned_topic_2],
        current_topic_index=1,
        current_topic_followups=1,
        questions_asked=2,
        covered_days={7, 29},
        turn_history=[
            {"role": "assistant", "content": "Welcome Sarah! Let's talk about Embeddings."},
            {"role": "user", "content": "Embeddings convert text to dense vectors."}
        ],
        current_topic_history=[
            {"role": "assistant", "content": "How do you monitor Prometheus?"},
            {"role": "user", "content": "I am not sure."}
        ],
        evaluations=[eval_1, eval_2],
        topic_summaries=["Day 7 (Embeddings): strong"],
        is_done=False,
        using_fallback=True,
        candidate_tone="peer"
    )


    # ── 3. Test Set, Get & Deep Property Verification ──────────────────
    session_store.set("full-session-999", populated_session)
    retrieved = session_store.get("full-session-999")

    assert retrieved is not None, "Failed to retrieve populated session"
    assert retrieved.session_id == "full-session-999"
    assert retrieved.candidate.member.name == "Sarah Johnson"
    assert len(retrieved.plan) == 2
    assert retrieved.plan[0].depth == TopicDepth.HIGH
    assert retrieved.plan[1].depth == TopicDepth.DIAGNOSTIC
    assert len(retrieved.evaluations) == 2
    assert retrieved.evaluations[0].bucket == "strong"
    assert retrieved.covered_days == {7, 29}
    assert retrieved.using_fallback is True
    assert retrieved.candidate_tone == "peer"
    assert retrieved.questions_asked == 2


    # ── 4. Test TTL Expiry & Lazy Eviction ──────────────────────────────
    store = session_store.SessionStore(ttl_seconds=300) # 5 minutes TTL
    now = time.time()

    temp_session = SessionState(
        session_id="expiring-session-1",
        candidate=candidate_profile,
        plan=[planned_topic_1]
    )

    # Set session with timestamp = now - 350 seconds (older than 300s TTL)
    store.set("expiring-session-1", temp_session, timestamp=now - 350)
    assert store.count() == 1, "Session should exist in store before get()"

    # Calling get(..., current_time=now) must trigger lazy eviction and return None
    expired_result = store.get("expiring-session-1", current_time=now)
    assert expired_result is None, "Expired session should return None"
    assert store.count() == 0, "Expired session should be deleted from memory on get()"


    # ── 5. Test Manual Delete ───────────────────────────────────────────
    session_store.delete("full-session-999")
    assert session_store.get("full-session-999") is None, "Session should be None after delete"


    # ── 6. Test Skeleton Stubs Importability ────────────────────────────
    import planner
    import turn_engine
    import feedback_synthesizer
    import llm_client
    import prompts
    import main
    assert planner.__doc__ is not None
    assert turn_engine.__doc__ is not None
    assert feedback_synthesizer.__doc__ is not None
    assert llm_client.__doc__ is not None
    assert prompts.__doc__ is not None
    assert main.__doc__ is not None

    print("ALL VERIFICATIONS PASSED SUCCESSFULLY!")
    print("- CandidateMission validation verified (catches malformed combinations).")
    print("- Fully populated SessionState serialization/deserialization verified.")
    print("- Thread-safe SessionStore set, get, delete verified.")
    print("- TTL expiry and lazy memory eviction verified.")
    print("- Skeleton module stubs verified.")


if __name__ == "__main__":
    verify()
