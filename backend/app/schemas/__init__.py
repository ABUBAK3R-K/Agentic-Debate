"""Pydantic schemas for PersonaArena API request/response validation."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Persona structured JSON — the schema the compiler must produce
# ---------------------------------------------------------------------------

class ReasoningStyle(BaseModel):
    decision_making: str = ""
    risk_tolerance: str = ""
    evidence_preference: str = ""


class CommunicationStyle(BaseModel):
    tone: str = ""
    directness: str = ""
    humor: str = ""


class DebateStyle(BaseModel):
    aggressiveness: str = ""
    preferred_tactics: list[str] = Field(default_factory=list)


class PersonaProfile(BaseModel):
    """The structured persona JSON extracted by the persona compiler."""
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


class FriendResponse(BaseModel):
    id: UUID
    name: str
    raw_description: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


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
    """The user's edits to a compiled persona, saved as a new version."""
    persona: PersonaProfile


# ---------------------------------------------------------------------------
# Debate schemas
# ---------------------------------------------------------------------------

class DebateCreateRequest(BaseModel):
    """Exactly two participants. Model settings come from the environment,
    never from the client — see PRD "Critical model constraint"."""
    topic: str = Field(..., min_length=5)
    participant_ids: list[UUID] = Field(..., min_length=2, max_length=2)


class ParticipantResponse(BaseModel):
    id: UUID
    friend_id: UUID
    friend_name: str
    position: Optional[str] = None


class DebateResponse(BaseModel):
    id: UUID
    topic: str
    status: str
    model_provider: str
    model_name: str
    temperature: float
    top_p: float
    max_tokens: int
    created_at: datetime
    completed_at: Optional[datetime]
    participants: list[ParticipantResponse] = []

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Agent structured output — what each debater returns per turn
# ---------------------------------------------------------------------------

class AgentStructuredOutput(BaseModel):
    """Structured output expected from the LLM during each debate turn.

    The frontend only ever renders `argument`; the rest is stored for later
    evaluation work.
    """
    argument: str
    key_claims: list[str] = Field(default_factory=list)
    opponent_claim_addressed: Optional[str] = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# SSE event schema
# ---------------------------------------------------------------------------

class SSEDebateEvent(BaseModel):
    """A single Server-Sent Event emitted while a debate runs."""
    event_type: str  # phase_start, message, turn_failed, phase_end,
                     # debate_complete, error
    phase: Optional[str] = None
    round_number: Optional[int] = None
    participant_id: Optional[UUID] = None
    participant_name: Optional[str] = None
    position: Optional[str] = None
    content: Optional[str] = None
    data: Optional[dict] = None


# ---------------------------------------------------------------------------
# Judge schemas
# ---------------------------------------------------------------------------

class ParticipantScore(BaseModel):
    """The judge's scores for a single participant."""
    logic: int = Field(ge=0, le=10)
    evidence: int = Field(ge=0, le=10)
    rebuttal: int = Field(ge=0, le=10)
    persuasiveness: int = Field(ge=0, le=10)
    overall: float = Field(ge=0.0, le=10.0)


class JudgeResult(BaseModel):
    """Structured output from the judge LLM call, keyed by anonymized label."""
    winner: str
    scores: dict[str, ParticipantScore]
    winner_reason: str
    strongest_argument: str
    weakest_argument: str


class ParticipantResult(BaseModel):
    """One side of the verdict, mapped back to a real friend."""
    participant_id: UUID
    name: str
    position: str
    is_winner: bool
    scores: ParticipantScore


class DebateResultResponse(BaseModel):
    """The verdict, as the frontend consumes it."""
    debate_id: UUID
    topic: str
    status: str
    winner_name: Optional[str] = None
    winner_reason: Optional[str] = None
    strongest_argument: Optional[str] = None
    weakest_argument: Optional[str] = None
    participants: list[ParticipantResult] = []
