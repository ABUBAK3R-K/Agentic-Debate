"""Pydantic schemas for PersonaArena API request/response validation."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Persona structured JSON — matches PRD Section 7
# ---------------------------------------------------------------------------

class ReasoningStyle(BaseModel):
    decision_making: str = ""
    risk_tolerance: str = ""
    time_horizon: str = ""
    evidence_preference: str = ""


class CommunicationStyle(BaseModel):
    tone: str = ""
    verbosity: str = ""
    directness: str = ""
    humor: str = ""


class DebateStyle(BaseModel):
    aggressiveness: str = ""
    preferred_tactics: list[str] = Field(default_factory=list)
    common_patterns: list[str] = Field(default_factory=list)


class PersonaProfile(BaseModel):
    """The structured persona JSON extracted by the Persona Compiler."""
    name: str
    core_traits: list[str] = Field(default_factory=list)
    values: list[str] = Field(default_factory=list)
    reasoning_style: ReasoningStyle = Field(default_factory=ReasoningStyle)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    communication_style: CommunicationStyle = Field(default_factory=CommunicationStyle)
    debate_style: DebateStyle = Field(default_factory=DebateStyle)


# ---------------------------------------------------------------------------
# Friend schemas
# ---------------------------------------------------------------------------

class FriendCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    raw_description: str = Field(..., min_length=10)


class FriendUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    raw_description: Optional[str] = Field(None, min_length=10)


class FriendResponse(BaseModel):
    id: UUID
    name: str
    raw_description: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class FriendWithPersona(FriendResponse):
    persona: Optional[PersonaProfile] = None


# ---------------------------------------------------------------------------
# Persona schemas
# ---------------------------------------------------------------------------

class PersonaCompileRequest(BaseModel):
    """Input to the persona compiler endpoint."""
    friend_id: UUID


class PersonaCompileResponse(BaseModel):
    id: UUID
    friend_id: UUID
    persona: PersonaProfile
    version: int
    created_at: datetime

    model_config = {"from_attributes": True}


class PersonaUpdateRequest(BaseModel):
    """Allows the user to manually edit the generated persona."""
    persona: PersonaProfile


# ---------------------------------------------------------------------------
# Debate schemas
# ---------------------------------------------------------------------------

class DebateCreateRequest(BaseModel):
    topic: str = Field(..., min_length=5)
    category: Optional[str] = None
    participant_ids: list[UUID] = Field(..., min_length=2, max_length=3)
    round_count: int = Field(default=4, ge=2, le=6)
    temperature: float = Field(default=0.8, ge=0.2, le=1.2)
    max_tokens: int = Field(default=500, ge=100, le=2000)
    top_p: float = Field(default=1.0, ge=0.0, le=1.0)


class ParticipantResponse(BaseModel):
    id: UUID
    friend_id: UUID
    friend_name: str
    position: Optional[str] = None
    participant_label: Optional[str] = None


class DebateMessageResponse(BaseModel):
    id: UUID
    participant_id: UUID
    participant_name: str
    round_number: int
    phase: str
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


class DebateResponse(BaseModel):
    id: UUID
    topic: str
    category: Optional[str]
    status: str
    round_count: int
    model_provider: str
    model_name: str
    temperature: float
    created_at: datetime
    completed_at: Optional[datetime]

    model_config = {"from_attributes": True}


class DebateDetailResponse(DebateResponse):
    """Full debate with participants and messages."""
    participants: list[ParticipantResponse] = []
    messages: list[DebateMessageResponse] = []


# ---------------------------------------------------------------------------
# Agent structured output (PRD Section 16)
# ---------------------------------------------------------------------------

class AgentStructuredOutput(BaseModel):
    """Structured output expected from the LLM during each debate round."""
    argument: str
    key_claims: list[str] = Field(default_factory=list)
    opponent_claim_addressed: Optional[str] = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# SSE event schemas
# ---------------------------------------------------------------------------

class SSEDebateEvent(BaseModel):
    """Schema for Server-Sent Events during live debate streaming."""
    event_type: str  # phase_start, message, phase_end, debate_complete, error
    phase: Optional[str] = None
    round_number: Optional[int] = None
    participant_name: Optional[str] = None
    content: Optional[str] = None
    data: Optional[dict] = None


# ---------------------------------------------------------------------------
# Judge evaluation schemas (PRD Sections 17-20)
# ---------------------------------------------------------------------------

class ParticipantScore(BaseModel):
    """Scores for a single participant from the judge."""
    logic: int = Field(ge=0, le=10)
    evidence: int = Field(ge=0, le=10)
    rebuttal: int = Field(ge=0, le=10)
    persuasiveness: int = Field(ge=0, le=10)
    persona_consistency: int = Field(ge=0, le=10)
    originality: int = Field(ge=0, le=10)
    overall: float = Field(ge=0.0, le=10.0)


class JudgeResult(BaseModel):
    """Structured output from the judge LLM call."""
    winner: str
    scores: dict[str, ParticipantScore]
    winner_reason: str
    strongest_argument: str
    weakest_argument: str


class PersonaConsistencyScore(BaseModel):
    """Per-participant persona consistency evaluation (separate from judge)."""
    reasoning_consistency: int = Field(ge=0, le=10)
    communication_consistency: int = Field(ge=0, le=10)
    value_consistency: int = Field(ge=0, le=10)
    behavior_consistency: int = Field(ge=0, le=10)
    overall_score: float = Field(ge=0.0, le=10.0)
    explanation: str = ""


class EvaluationResponse(BaseModel):
    """Full evaluation result returned by the API."""
    debate_id: UUID
    status: str
    winner_name: Optional[str] = None
    winner_reason: Optional[str] = None
    strongest_argument: Optional[str] = None
    weakest_argument: Optional[str] = None
    scores: Optional[dict[str, ParticipantScore]] = None
    persona_consistency: Optional[dict[str, PersonaConsistencyScore]] = None

