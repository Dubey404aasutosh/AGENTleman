from enum import Enum
from pydantic import BaseModel, Field, model_validator


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

    @model_validator(mode='after')
    def validate_mission_status(self):
        if self.skipped:
            if self.passed is not None:
                raise ValueError("Skipped mission cannot have 'passed' status set.")
        elif self.passed is not None:
            if self.attempts is None or self.attempts < 1:
                raise ValueError(f"Mission with passed={self.passed} must have attempts >= 1.")
        return self


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
