"""DebateEngine — deterministic state machine for multi-round debates.

The backend controls all state transitions. LLMs only generate arguments.
Agents CANNOT alter the state machine (PRD Section 12).
"""

import json
import logging
from datetime import datetime, timezone
from typing import AsyncGenerator
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.base import LLMProvider
from app.llm.prompts import (
    build_debate_system_prompt,
    build_opening_prompt,
    build_rebuttal_prompt,
    build_counter_prompt,
    build_closing_prompt,
    format_transcript,
)
from app.models import Debate, DebateParticipant, DebateMessage, Friend, Persona
from app.schemas import AgentStructuredOutput, SSEDebateEvent

logger = logging.getLogger(__name__)

# Valid state transitions
VALID_TRANSITIONS = {
    "CREATED": "POSITIONING",
    "POSITIONING": "OPENING",
    "OPENING": "REBUTTAL",
    "REBUTTAL": "COUNTER",
    "COUNTER": "CLOSING",
    "CLOSING": "JUDGING",
    "JUDGING": "COMPLETED",
}

# Map phases to round numbers (for a standard 4-round debate)
PHASE_ORDER = ["POSITIONING", "OPENING", "REBUTTAL", "COUNTER", "CLOSING"]

# Positions
POSITIONS_2P = ["FOR", "AGAINST"]
POSITIONS_3P = ["FOR", "AGAINST", "NEUTRAL"]


class DebateEngine:
    """Orchestrates the full debate lifecycle."""

    def __init__(self, db: AsyncSession, llm: LLMProvider):
        self.db = db
        self.llm = llm

    # ------------------------------------------------------------------ #
    # State machine
    # ------------------------------------------------------------------ #

    async def _transition(self, debate: Debate, target_status: str) -> None:
        """Advance the debate to the next state, or fail."""
        expected = VALID_TRANSITIONS.get(debate.status)
        if expected != target_status and target_status != "FAILED":
            raise ValueError(
                f"Invalid transition: {debate.status} → {target_status}. "
                f"Expected → {expected}"
            )
        debate.status = target_status
        if target_status == "COMPLETED":
            debate.completed_at = datetime.now(timezone.utc)
        await self.db.commit()
        logger.info("Debate %s transitioned to %s", debate.id, target_status)

    # ------------------------------------------------------------------ #
    # Create debate
    # ------------------------------------------------------------------ #

    async def create_debate(
        self,
        topic: str,
        category: str | None,
        participant_friend_ids: list[UUID],
        round_count: int,
        temperature: float,
        max_tokens: int,
        top_p: float,
        model_provider: str,
        model_name: str,
    ) -> Debate:
        """Create a new debate record with participants."""
        debate = Debate(
            topic=topic,
            category=category,
            model_provider=model_provider,
            model_name=model_name,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            round_count=round_count,
            status="CREATED",
        )
        self.db.add(debate)
        await self.db.flush()  # Get the debate ID

        # Create participants
        labels = [chr(65 + i) for i in range(len(participant_friend_ids))]  # A, B, C
        for i, friend_id in enumerate(participant_friend_ids):
            participant = DebateParticipant(
                debate_id=debate.id,
                friend_id=friend_id,
                participant_label=f"Participant {labels[i]}",
            )
            self.db.add(participant)

        await self.db.commit()
        await self.db.refresh(debate)
        logger.info("Debate %s created with %d participants", debate.id, len(participant_friend_ids))
        return debate

    # ------------------------------------------------------------------ #
    # Position assignment
    # ------------------------------------------------------------------ #

    async def assign_positions(self, debate: Debate) -> None:
        """Assign FOR/AGAINST/NEUTRAL positions to participants."""
        await self._transition(debate, "POSITIONING")

        result = await self.db.execute(
            select(DebateParticipant).where(DebateParticipant.debate_id == debate.id)
        )
        participants = list(result.scalars().all())

        positions = POSITIONS_2P if len(participants) == 2 else POSITIONS_3P
        for i, participant in enumerate(participants):
            participant.position = positions[i]

        await self.db.commit()
        logger.info("Positions assigned for debate %s", debate.id)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    async def _load_participant_data(self, participant: DebateParticipant) -> dict:
        """Load the friend name and latest persona for a participant."""
        friend_result = await self.db.execute(
            select(Friend).where(Friend.id == participant.friend_id)
        )
        friend = friend_result.scalar_one()

        persona_result = await self.db.execute(
            select(Persona)
            .where(Persona.friend_id == participant.friend_id)
            .order_by(Persona.version.desc())
            .limit(1)
        )
        persona = persona_result.scalar_one_or_none()
        persona_json = persona.persona_json if persona else {"name": friend.name}

        return {
            "friend": friend,
            "persona_json": persona_json,
            "system_prompt": build_debate_system_prompt(persona_json),
        }

    async def _get_transcript_so_far(self, debate_id: UUID) -> list[dict]:
        """Fetch all messages for a debate, formatted for context injection."""
        result = await self.db.execute(
            select(DebateMessage)
            .where(DebateMessage.debate_id == debate_id)
            .order_by(DebateMessage.created_at)
        )
        messages = result.scalars().all()

        transcript = []
        for msg in messages:
            # Look up participant's friend name
            p_result = await self.db.execute(
                select(DebateParticipant).where(DebateParticipant.id == msg.participant_id)
            )
            participant = p_result.scalar_one()
            f_result = await self.db.execute(
                select(Friend).where(Friend.id == participant.friend_id)
            )
            friend = f_result.scalar_one()

            transcript.append({
                "participant_name": friend.name,
                "phase": msg.phase,
                "content": msg.content,
            })
        return transcript

    async def _generate_and_store(
        self,
        debate: Debate,
        participant: DebateParticipant,
        participant_data: dict,
        user_prompt: str,
        phase: str,
        round_number: int,
    ) -> DebateMessage:
        """Call the LLM for a participant and store the result."""
        try:
            structured: AgentStructuredOutput = await self.llm.generate_structured(
                system_prompt=participant_data["system_prompt"],
                messages=[{"role": "user", "content": user_prompt}],
                response_model=AgentStructuredOutput,
                temperature=debate.temperature,
                max_tokens=debate.max_tokens,
                top_p=debate.top_p,
            )
            content = structured.argument
            structured_json = structured.model_dump()
        except Exception as e:
            logger.warning("Structured output failed for %s, falling back to text: %s", participant.id, e)
            # Fallback: plain text generation
            content = await self.llm.generate_text(
                system_prompt=participant_data["system_prompt"],
                messages=[{"role": "user", "content": user_prompt}],
                temperature=debate.temperature,
                max_tokens=debate.max_tokens,
                top_p=debate.top_p,
            )
            structured_json = {"argument": content, "key_claims": [], "confidence": 0.5}

        message = DebateMessage(
            debate_id=debate.id,
            participant_id=participant.id,
            round_number=round_number,
            phase=phase,
            content=content,
            structured_output=structured_json,
        )
        self.db.add(message)
        await self.db.commit()
        await self.db.refresh(message)
        return message

    # ------------------------------------------------------------------ #
    # Round generators
    # ------------------------------------------------------------------ #

    async def run_opening(self, debate: Debate) -> AsyncGenerator[SSEDebateEvent, None]:
        """Run the opening round for all participants."""
        await self._transition(debate, "OPENING")

        result = await self.db.execute(
            select(DebateParticipant).where(DebateParticipant.debate_id == debate.id)
        )
        participants = list(result.scalars().all())

        yield SSEDebateEvent(event_type="phase_start", phase="OPENING", round_number=1)

        for participant in participants:
            data = await self._load_participant_data(participant)
            user_prompt = build_opening_prompt(debate.topic, participant.position)

            message = await self._generate_and_store(
                debate, participant, data, user_prompt, "OPENING", 1
            )

            yield SSEDebateEvent(
                event_type="message",
                phase="OPENING",
                round_number=1,
                participant_name=data["friend"].name,
                content=message.content,
            )

        yield SSEDebateEvent(event_type="phase_end", phase="OPENING", round_number=1)

    async def run_rebuttal(self, debate: Debate) -> AsyncGenerator[SSEDebateEvent, None]:
        """Run the rebuttal round."""
        await self._transition(debate, "REBUTTAL")

        result = await self.db.execute(
            select(DebateParticipant).where(DebateParticipant.debate_id == debate.id)
        )
        participants = list(result.scalars().all())
        transcript_data = await self._get_transcript_so_far(debate.id)
        transcript_text = format_transcript(transcript_data)

        yield SSEDebateEvent(event_type="phase_start", phase="REBUTTAL", round_number=2)

        for participant in participants:
            data = await self._load_participant_data(participant)
            user_prompt = build_rebuttal_prompt(debate.topic, participant.position, transcript_text)

            message = await self._generate_and_store(
                debate, participant, data, user_prompt, "REBUTTAL", 2
            )

            yield SSEDebateEvent(
                event_type="message",
                phase="REBUTTAL",
                round_number=2,
                participant_name=data["friend"].name,
                content=message.content,
            )

        yield SSEDebateEvent(event_type="phase_end", phase="REBUTTAL", round_number=2)

    async def run_counter(self, debate: Debate) -> AsyncGenerator[SSEDebateEvent, None]:
        """Run the counter-argument round."""
        await self._transition(debate, "COUNTER")

        result = await self.db.execute(
            select(DebateParticipant).where(DebateParticipant.debate_id == debate.id)
        )
        participants = list(result.scalars().all())
        transcript_data = await self._get_transcript_so_far(debate.id)
        transcript_text = format_transcript(transcript_data)

        yield SSEDebateEvent(event_type="phase_start", phase="COUNTER", round_number=3)

        for participant in participants:
            data = await self._load_participant_data(participant)
            user_prompt = build_counter_prompt(debate.topic, participant.position, transcript_text)

            message = await self._generate_and_store(
                debate, participant, data, user_prompt, "COUNTER", 3
            )

            yield SSEDebateEvent(
                event_type="message",
                phase="COUNTER",
                round_number=3,
                participant_name=data["friend"].name,
                content=message.content,
            )

        yield SSEDebateEvent(event_type="phase_end", phase="COUNTER", round_number=3)

    async def run_closing(self, debate: Debate) -> AsyncGenerator[SSEDebateEvent, None]:
        """Run the closing round."""
        await self._transition(debate, "CLOSING")

        result = await self.db.execute(
            select(DebateParticipant).where(DebateParticipant.debate_id == debate.id)
        )
        participants = list(result.scalars().all())
        transcript_data = await self._get_transcript_so_far(debate.id)
        transcript_text = format_transcript(transcript_data)

        yield SSEDebateEvent(event_type="phase_start", phase="CLOSING", round_number=4)

        for participant in participants:
            data = await self._load_participant_data(participant)
            user_prompt = build_closing_prompt(debate.topic, participant.position, transcript_text)

            message = await self._generate_and_store(
                debate, participant, data, user_prompt, "CLOSING", 4
            )

            yield SSEDebateEvent(
                event_type="message",
                phase="CLOSING",
                round_number=4,
                participant_name=data["friend"].name,
                content=message.content,
            )

        yield SSEDebateEvent(event_type="phase_end", phase="CLOSING", round_number=4)

    # ------------------------------------------------------------------ #
    # Full debate orchestration
    # ------------------------------------------------------------------ #

    async def run_debate(self, debate: Debate) -> AsyncGenerator[SSEDebateEvent, None]:
        """Run the entire debate through all phases, yielding SSE events.

        This is the main entry point called by the API stream endpoint.
        """
        try:
            # Phase 1: Position assignment
            await self.assign_positions(debate)
            yield SSEDebateEvent(
                event_type="phase_start",
                phase="POSITIONING",
                data={"message": "Positions assigned"},
            )

            # Phase 2: Opening statements
            async for event in self.run_opening(debate):
                yield event

            # Phase 3: Rebuttal
            async for event in self.run_rebuttal(debate):
                yield event

            # Phase 4: Counter-arguments
            async for event in self.run_counter(debate):
                yield event

            # Phase 5: Closing statements
            async for event in self.run_closing(debate):
                yield event

            # Phase 6: Judging — run independent judge + persona consistency
            await self._transition(debate, "JUDGING")
            yield SSEDebateEvent(
                event_type="phase_start",
                phase="JUDGING",
                data={"message": "Debate rounds complete. Running judge evaluation..."},
            )

            from app.services.judge_engine import JudgeEngine
            judge = JudgeEngine(self.db, self.llm)
            evaluation_result = await judge.evaluate_debate(debate)

            yield SSEDebateEvent(
                event_type="message",
                phase="JUDGING",
                content=f"Winner: {evaluation_result.get('winner_name', 'Unknown')}",
                data=evaluation_result,
            )

            # Phase 7: Completed
            await self._transition(debate, "COMPLETED")
            yield SSEDebateEvent(
                event_type="debate_complete",
                phase="COMPLETED",
                data=evaluation_result,
            )

        except Exception as e:
            logger.error("Debate %s failed: %s", debate.id, e, exc_info=True)
            debate.status = "FAILED"
            await self.db.commit()
            yield SSEDebateEvent(
                event_type="error",
                content=f"Debate failed: {str(e)}",
            )

