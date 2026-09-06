"""JudgeEngine — the independent judge.

The judge is a separate LLM call. It never sees a friend's name: participants
reach it only as "Participant A" and "Participant B", and which friend holds
which label was randomized when the debate was created. The mapping back to
real identities happens here, after the judge has answered.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.llm.base import LLMProvider
from app.llm.prompts import (
    JUDGE_SYSTEM_PROMPT,
    build_judge_user_prompt,
    format_anonymized_transcript,
)
from app.llm.structured import generate_structured_resilient
from app.models import (
    Debate,
    DebateMessage,
    DebateParticipant,
    Evaluation,
    Friend,
    Persona,
)
from app.schemas import JudgeResult

logger = logging.getLogger(__name__)


class JudgeEngine:
    """Scores a completed debate and stores the verdict."""

    def __init__(self, db: AsyncSession, llm: LLMProvider):
        self.db = db
        self.llm = llm

    async def evaluate_debate(self, debate: Debate) -> dict:
        """Judge the debate, store the evaluation, and return the verdict."""
        participants = await self._load_participants(debate.id)
        transcript = await self._anonymized_transcript(debate.id, participants)

        judge_result = await self._run_judge(debate, participants, transcript)

        # Map the judge's anonymized answer back onto real participants.
        by_label = {p["label"]: p for p in participants.values()}
        winner = by_label.get(judge_result.winner)
        if winner is None:
            raise ValueError(
                f"Judge named an unknown participant: {judge_result.winner!r}"
            )

        scores_by_participant = {}
        for label, score in judge_result.scores.items():
            participant = by_label.get(label)
            if participant is None:
                logger.warning("Judge scored an unknown label %r; ignoring", label)
                continue
            scores_by_participant[str(participant["id"])] = score.model_dump()

        evaluation = Evaluation(
            debate_id=debate.id,
            winner_participant_id=winner["id"],
            scores_json={
                "scores": scores_by_participant,
                "strongest_argument": judge_result.strongest_argument,
                "weakest_argument": judge_result.weakest_argument,
            },
            summary=judge_result.winner_reason,
        )
        self.db.add(evaluation)
        await self.db.commit()

        logger.info(
            "Debate %s judged. Winner: %s (%s)",
            debate.id, winner["name"], winner["label"],
        )

        return {
            "winner_name": winner["name"],
            "winner_participant_id": str(winner["id"]),
            "winner_reason": judge_result.winner_reason,
            "strongest_argument": judge_result.strongest_argument,
            "weakest_argument": judge_result.weakest_argument,
            "participants": [
                {
                    "participant_id": str(p["id"]),
                    "name": p["name"],
                    "position": p["position"],
                    "is_winner": p["id"] == winner["id"],
                    "scores": scores_by_participant.get(str(p["id"])),
                }
                for p in sorted(participants.values(), key=lambda p: p["slot"])
            ],
        }

    # ------------------------------------------------------------------ #
    # Loading
    # ------------------------------------------------------------------ #

    async def _load_participants(self, debate_id) -> dict:
        """Participants keyed by id, with friend name and persona traits."""
        result = await self.db.execute(
            select(DebateParticipant, Friend)
            .join(Friend, DebateParticipant.friend_id == Friend.id)
            .where(DebateParticipant.debate_id == debate_id)
            .order_by(DebateParticipant.slot)
        )

        participants = {}
        for participant, friend in result.all():
            persona_result = await self.db.execute(
                select(Persona)
                .where(Persona.friend_id == participant.friend_id)
                .order_by(Persona.version.desc())
                .limit(1)
            )
            persona = persona_result.scalar_one_or_none()
            traits = (persona.persona_json or {}).get("core_traits", []) if persona else []

            participants[participant.id] = {
                "id": participant.id,
                "slot": participant.slot,
                "name": friend.name,
                "position": participant.position,
                "label": participant.participant_label,
                "traits": ", ".join(traits),
            }
        return participants

    async def _anonymized_transcript(self, debate_id, participants: dict) -> str:
        """The full transcript, with every name replaced by a label."""
        result = await self.db.execute(
            select(DebateMessage)
            .where(DebateMessage.debate_id == debate_id)
            .order_by(DebateMessage.created_at)
        )
        messages = list(result.scalars().all())

        return format_anonymized_transcript([
            {
                "participant_label": participants[msg.participant_id]["label"],
                "phase": msg.phase,
                "content": msg.content or "[no argument was produced for this turn]",
            }
            for msg in messages
            if msg.participant_id in participants
        ])

    # ------------------------------------------------------------------ #
    # The judge call
    # ------------------------------------------------------------------ #

    async def _run_judge(
        self, debate: Debate, participants: dict, transcript: str
    ) -> JudgeResult:
        """Run the judge. Participants are described by traits only — no names.

        The judge is deliberately given traits rather than full personas: it is
        scoring the arguments, not how well each side impersonated someone.
        """
        participants_info = [
            {
                "label": p["label"],
                "persona_summary": p["traits"] or "No persona traits available",
            }
            for p in sorted(participants.values(), key=lambda p: p["label"])
        ]

        user_prompt = build_judge_user_prompt(
            debate.topic, participants_info, transcript
        )

        logger.info("Judging debate %s", debate.id)
        return await generate_structured_resilient(
            self.llm,
            system_prompt=JUDGE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
            response_model=JudgeResult,
            temperature=settings.JUDGE_TEMPERATURE,
            max_tokens=settings.JUDGE_MAX_TOKENS,
            context=f"judge for debate {debate.id}",
        )
