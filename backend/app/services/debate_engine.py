"""DebateEngine — the deterministic state machine that runs a debate.

The backend owns every state transition. The LLMs only produce content when
asked; they never decide what happens next, who speaks, or which side they
are on.
"""

import logging
import random
from datetime import datetime, timezone
from typing import AsyncGenerator
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.base import LLMProvider
from app.llm.prompts import (
    build_debate_system_prompt,
    build_turn_prompt,
    format_transcript,
)
from app.llm.errors import LLMTransportError, redact
from app.llm.structured import (
    JsonStringFieldExtractor,
    StructuredOutputError,
    generate_structured_resilient,
    lenient_parse,
)
from app.models import Debate, DebateMessage, DebateParticipant, Friend, Persona
from app.schemas import AgentStructuredOutput, SSEDebateEvent

logger = logging.getLogger(__name__)

# The only legal path through a debate.
VALID_TRANSITIONS = {
    "CREATED": "POSITIONING",
    "POSITIONING": "OPENING",
    "OPENING": "REBUTTAL",
    "REBUTTAL": "COUNTER",
    "COUNTER": "CLOSING",
    "CLOSING": "JUDGING",
    "JUDGING": "COMPLETED",
}

# The four speaking rounds, in order, with their round numbers.
DEBATE_ROUNDS = [
    ("OPENING", 1),
    ("REBUTTAL", 2),
    ("COUNTER", 3),
    ("CLOSING", 4),
]

POSITIONS = ["FOR", "AGAINST"]
PARTICIPANT_LABELS = ["Participant A", "Participant B"]


class DebateEngine:
    """Orchestrates one debate from creation through to a stored verdict."""

    def __init__(
        self,
        db: AsyncSession,
        llm: LLMProvider,
        judge_llm: LLMProvider | None = None,
    ):
        self.db = db
        self.llm = llm
        # The judge may run on its own provider instance so it can be given a
        # different model, and with it a separate rate-limit budget. Falling
        # back to `llm` keeps the single-argument construction that every
        # caller and test already uses.
        self.judge_llm = judge_llm or llm
        # Set when the provider refuses on quota. Every later turn would fail
        # the same way, so the debate stops rather than filling the remaining
        # rounds with empty ones.
        self.blocked_reason: str | None = None

    # ------------------------------------------------------------------ #
    # State machine
    # ------------------------------------------------------------------ #

    async def _transition(self, debate: Debate, target_status: str) -> None:
        """Advance the debate one step, or refuse."""
        expected = VALID_TRANSITIONS.get(debate.status)
        if expected != target_status:
            raise ValueError(
                f"Invalid transition: {debate.status} → {target_status}. "
                f"Expected → {expected}"
            )
        debate.status = target_status
        if target_status == "COMPLETED":
            debate.completed_at = datetime.now(timezone.utc)
        await self.db.commit()
        logger.info("Debate %s → %s", debate.id, target_status)

    # ------------------------------------------------------------------ #
    # Creation
    # ------------------------------------------------------------------ #

    async def create_debate(
        self,
        *,
        topic: str,
        participant_friend_ids: list[UUID],
        model_provider: str,
        model_name: str,
        temperature: float,
        top_p: float,
        max_tokens: int,
    ) -> Debate:
        """Create a debate and its two participants.

        Anonymized judge labels are assigned here, in randomized order, so the
        judge's "Participant A" is as likely to be the second friend as the
        first. This is the debate's only source of judge-facing ordering.
        """
        if len(participant_friend_ids) != 2:
            raise ValueError("A debate needs exactly two participants")

        debate = Debate(
            topic=topic,
            model_provider=model_provider,
            model_name=model_name,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            status="CREATED",
        )
        self.db.add(debate)
        await self.db.flush()

        labels = list(PARTICIPANT_LABELS)
        random.shuffle(labels)
        for slot, (friend_id, label) in enumerate(zip(participant_friend_ids, labels)):
            self.db.add(DebateParticipant(
                debate_id=debate.id,
                friend_id=friend_id,
                slot=slot,
                participant_label=label,
            ))

        await self.db.commit()
        await self.db.refresh(debate)
        logger.info("Debate %s created", debate.id)
        return debate

    # ------------------------------------------------------------------ #
    # Participants
    # ------------------------------------------------------------------ #

    async def _get_participants(self, debate_id: UUID) -> list[DebateParticipant]:
        """Participants in slot order — the speaking and column order."""
        result = await self.db.execute(
            select(DebateParticipant)
            .where(DebateParticipant.debate_id == debate_id)
            .order_by(DebateParticipant.slot)
        )
        return list(result.scalars().all())

    async def assign_positions(self, debate: Debate) -> None:
        """Assign FOR / AGAINST. The backend decides, never the agents —
        left to themselves, both agents pick whichever side reads as safer."""
        await self._transition(debate, "POSITIONING")

        participants = await self._get_participants(debate.id)
        if len(participants) != 2:
            raise ValueError(
                f"Debate {debate.id} has {len(participants)} participants, expected 2"
            )

        for participant, position in zip(participants, POSITIONS):
            participant.position = position

        await self.db.commit()
        logger.info("Positions assigned for debate %s", debate.id)

    async def _load_participant_context(self, participant: DebateParticipant) -> dict:
        """Load the friend and their latest persona, compiled into a prompt."""
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

    # ------------------------------------------------------------------ #
    # Transcript
    # ------------------------------------------------------------------ #

    async def _transcript_so_far(self, debate_id: UUID) -> str:
        """The debate so far, formatted for injection into a turn prompt."""
        result = await self.db.execute(
            select(DebateMessage, Friend)
            .join(
                DebateParticipant,
                DebateMessage.participant_id == DebateParticipant.id,
            )
            .join(Friend, DebateParticipant.friend_id == Friend.id)
            .where(DebateMessage.debate_id == debate_id)
            .order_by(DebateMessage.created_at)
        )
        return format_transcript([
            {
                "participant_name": friend.name,
                "phase": message.phase,
                "content": message.content,
            }
            for message, friend in result.all()
        ])

    # ------------------------------------------------------------------ #
    # One turn
    # ------------------------------------------------------------------ #

    async def _run_turn(
        self,
        debate: Debate,
        participant: DebateParticipant,
        context: dict,
        phase: str,
        round_number: int,
        transcript: str,
    ) -> AsyncGenerator[SSEDebateEvent, None]:
        """Generate one participant's turn, streaming it as it is written.

        Every participant is called with the debate's identical model settings.
        The only things that differ are the persona system prompt, the assigned
        position, and the transcript.

        A turn emits `turn_start`, then `token` events as text arrives, then
        exactly one of `message` (the authoritative final text) or
        `turn_failed`. Tokens are a live preview; `message` is the truth, so a
        turn that has to be regenerated simply replaces what was previewed.
        """
        user_prompt = build_turn_prompt(
            phase, debate.topic, participant.position, transcript
        )
        messages = [{"role": "user", "content": user_prompt}]
        turn_context = f"{phase} turn for participant {participant.id}"

        def event(event_type: str, **fields) -> SSEDebateEvent:
            return SSEDebateEvent(
                event_type=event_type,
                phase=phase,
                round_number=round_number,
                participant_id=participant.id,
                participant_name=context["friend"].name,
                position=participant.position,
                **fields,
            )

        yield event("turn_start")

        output: AgentStructuredOutput | None = None
        extractor = JsonStringFieldExtractor("argument")

        try:
            async for chunk in self.llm.generate_stream(
                system_prompt=context["system_prompt"],
                messages=messages,
                temperature=debate.temperature,
                max_tokens=debate.max_tokens,
                top_p=debate.top_p,
                json_output=True,
            ):
                delta = extractor.feed(chunk)
                if delta:
                    yield event("token", content=delta)

            output = lenient_parse(extractor.raw, AgentStructuredOutput)
        except Exception as exc:
            # The stream is a nicety; correctness comes from the recovery
            # chain, so fall back to it rather than losing the turn.
            # A rate limit here is not fatal: the recovery chain below retries
            # with backoff. Only a turn that fails outright blocks the debate.
            logger.warning(
                "Streaming failed for %s: %s", turn_context, redact(str(exc))
            )

        if output is None:
            try:
                output = await generate_structured_resilient(
                    self.llm,
                    system_prompt=context["system_prompt"],
                    messages=messages,
                    response_model=AgentStructuredOutput,
                    temperature=debate.temperature,
                    max_tokens=debate.max_tokens,
                    top_p=debate.top_p,
                    context=turn_context,
                )
            except StructuredOutputError as exc:
                # Record the turn as failed rather than storing invented
                # content. A one-off bad answer leaves a visible gap and the
                # debate carries on; a provider that will not answer at all
                # stops it (see run_debate).
                logger.error(
                    "Turn failed: debate=%s participant=%s phase=%s: %s",
                    debate.id, participant.id, phase, exc,
                )
                self.db.add(DebateMessage(
                    debate_id=debate.id,
                    participant_id=participant.id,
                    round_number=round_number,
                    phase=phase,
                    content="",
                    structured_output={"failed": True, "error": str(exc)},
                ))
                await self.db.commit()

                # If the provider never answered, later turns will fail the
                # same way; let run_debate stop the debate instead.
                if isinstance(exc.__cause__, LLMTransportError):
                    self.blocked_reason = str(exc)

                yield event("turn_failed", content=str(exc))
                return

        self.db.add(DebateMessage(
            debate_id=debate.id,
            participant_id=participant.id,
            round_number=round_number,
            phase=phase,
            content=output.argument,
            structured_output=output.model_dump(),
        ))
        await self.db.commit()

        yield event("message", content=output.argument)

    # ------------------------------------------------------------------ #
    # Full debate
    # ------------------------------------------------------------------ #

    async def run_debate(self, debate: Debate) -> AsyncGenerator[SSEDebateEvent, None]:
        """Run the debate end to end, yielding an event per state change.

        This is the generator behind the SSE stream.
        """
        try:
            await self.assign_positions(debate)
            participants = await self._get_participants(debate.id)
            contexts = {
                p.id: await self._load_participant_context(p) for p in participants
            }

            yield SSEDebateEvent(
                event_type="phase_start",
                phase="POSITIONING",
                data={
                    "topic": debate.topic,
                    "participants": [
                        {
                            "participant_id": str(p.id),
                            "name": contexts[p.id]["friend"].name,
                            "position": p.position,
                        }
                        for p in participants
                    ],
                },
            )

            for phase, round_number in DEBATE_ROUNDS:
                await self._transition(debate, phase)
                yield SSEDebateEvent(
                    event_type="phase_start",
                    phase=phase,
                    round_number=round_number,
                )

                # Each turn sees everything said before it, so turns within a
                # round run in sequence rather than concurrently.
                for participant in participants:
                    transcript = await self._transcript_so_far(debate.id)
                    async for turn_event in self._run_turn(
                        debate,
                        participant,
                        contexts[participant.id],
                        phase,
                        round_number,
                        transcript,
                    ):
                        yield turn_event

                    if self.blocked_reason:
                        raise RuntimeError(self.blocked_reason)

                yield SSEDebateEvent(
                    event_type="phase_end",
                    phase=phase,
                    round_number=round_number,
                )

            await self._transition(debate, "JUDGING")
            yield SSEDebateEvent(event_type="phase_start", phase="JUDGING")

            from app.services.judge_engine import JudgeEngine

            verdict = await JudgeEngine(self.db, self.judge_llm).evaluate_debate(debate)

            await self._transition(debate, "COMPLETED")
            yield SSEDebateEvent(
                event_type="debate_complete",
                phase="COMPLETED",
                data=verdict,
            )

        except Exception as exc:
            logger.error("Debate %s failed: %s", debate.id, exc, exc_info=True)
            debate.status = "FAILED"
            await self.db.commit()
            yield SSEDebateEvent(event_type="error", content=redact(str(exc)))
