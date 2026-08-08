import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Text, Integer, Float, DateTime,
    ForeignKey, Enum as SAEnum, JSON
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base

# ---------------------------------------------------------------------------
# friends
# ---------------------------------------------------------------------------

class Friend(Base):
    __tablename__ = "friends"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    raw_description = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    personas = relationship("Persona", back_populates="friend", cascade="all, delete-orphan")
    participations = relationship("DebateParticipant", back_populates="friend")


# ---------------------------------------------------------------------------
# personas
# ---------------------------------------------------------------------------

class Persona(Base):
    __tablename__ = "personas"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    friend_id = Column(UUID(as_uuid=True), ForeignKey("friends.id", ondelete="CASCADE"), nullable=False)
    persona_json = Column(JSON, nullable=False)
    version = Column(Integer, default=1)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    friend = relationship("Friend", back_populates="personas")


# ---------------------------------------------------------------------------
# debates
# ---------------------------------------------------------------------------

class Debate(Base):
    __tablename__ = "debates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    topic = Column(Text, nullable=False)
    category = Column(String(50), nullable=True)
    model_provider = Column(String(50), nullable=False)
    model_name = Column(String(100), nullable=False)
    temperature = Column(Float, nullable=False, default=0.8)
    top_p = Column(Float, nullable=False, default=1.0)
    max_tokens = Column(Integer, nullable=False, default=500)
    round_count = Column(Integer, nullable=False, default=4)
    status = Column(
        String(20),
        nullable=False,
        default="CREATED",
    )
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    participants = relationship("DebateParticipant", back_populates="debate", cascade="all, delete-orphan")
    messages = relationship("DebateMessage", back_populates="debate", cascade="all, delete-orphan")
    evaluation = relationship("Evaluation", back_populates="debate", uselist=False, cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# debate_participants
# ---------------------------------------------------------------------------

class DebateParticipant(Base):
    __tablename__ = "debate_participants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    debate_id = Column(UUID(as_uuid=True), ForeignKey("debates.id", ondelete="CASCADE"), nullable=False)
    friend_id = Column(UUID(as_uuid=True), ForeignKey("friends.id", ondelete="CASCADE"), nullable=False)
    position = Column(String(20), nullable=True)  # FOR, AGAINST, NEUTRAL
    participant_label = Column(String(20), nullable=True)  # Participant A, B, C

    # Relationships
    debate = relationship("Debate", back_populates="participants")
    friend = relationship("Friend", back_populates="participations")
    messages = relationship("DebateMessage", back_populates="participant")


# ---------------------------------------------------------------------------
# debate_messages
# ---------------------------------------------------------------------------

class DebateMessage(Base):
    __tablename__ = "debate_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    debate_id = Column(UUID(as_uuid=True), ForeignKey("debates.id", ondelete="CASCADE"), nullable=False)
    participant_id = Column(UUID(as_uuid=True), ForeignKey("debate_participants.id", ondelete="CASCADE"), nullable=False)
    round_number = Column(Integer, nullable=False)
    phase = Column(String(20), nullable=False)  # OPENING, REBUTTAL, COUNTER, CLOSING
    content = Column(Text, nullable=False)
    structured_output = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    debate = relationship("Debate", back_populates="messages")
    participant = relationship("DebateParticipant", back_populates="messages")


# ---------------------------------------------------------------------------
# evaluations
# ---------------------------------------------------------------------------

class Evaluation(Base):
    __tablename__ = "evaluations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    debate_id = Column(UUID(as_uuid=True), ForeignKey("debates.id", ondelete="CASCADE"), nullable=False, unique=True)
    winner_participant_id = Column(UUID(as_uuid=True), ForeignKey("debate_participants.id"), nullable=True)
    scores_json = Column(JSON, nullable=False)
    summary = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    debate = relationship("Debate", back_populates="evaluation")
