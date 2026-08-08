"""JudgeEngine — independent AI judge and persona consistency evaluator.

The judge is completely separate from the debating agents (PRD Section 17).
Uses anonymized participant labels for bias mitigation (PRD Section 19).
Persona consistency evaluation is logically separate from the judge (PRD Section 20).
"""

import logging
import random
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.base import LLMProvider
from app.llm.prompts import (
    JUDGE_SYSTEM_PROMPT,
    PERSONA_CONSISTENCY_SYSTEM,
    build_judge_user_prompt,
    build_persona_consistency_prompt,
    format_anonymized_transcript,
)
from app.models import (
    Debate,
    DebateMessage,
    DebateParticipant,
    Evaluation,
    Friend,
    Persona,
)
from app.schemas import JudgeResult, PersonaConsistencyScore

logger = logging.getLogger(__name__)


class JudgeEngine:
    """Runs the independent judge evaluation and persona consistency checks."""

    def __init__(self, db: AsyncSession, llm: LLMProvider):
        self.db = db
        self.llm = llm

    async def evaluate_debate(self, debate: Debate) -> dict:
        """Run the full evaluation pipeline:
        1. Judge the debate (anonymized, randomized order)
        2. Evaluate persona consistency per participant
        3. Store the evaluation
        4. Return the combined result

        Returns a dict with winner info, scores, and persona consistency.
        """
        # Load participants
        p_result = await self.db.execute(
            select(DebateParticipant).where(DebateParticipant.debate_id == debate.id)
        )
        participants = list(p_result.scalars().all())

        # Load friend names for each participant
        participant_data = {}
        for p in participants:
            f_result = await self.db.execute(
                select(Friend).where(Friend.id == p.friend_id)
            )
            friend = f_result.scalar_one()

            persona_result = await self.db.execute(
                select(Persona)
                .where(Persona.friend_id == p.friend_id)
                .order_by(Persona.version.desc())
                .limit(1)
            )
            persona = persona_result.scalar_one_or_none()
            persona_json = persona.persona_json if persona else {}

            participant_data[p.id] = {
                "participant": p,
                "friend": friend,
                "persona_json": persona_json,
                "label": p.participant_label,
            }

        # Load all messages
        m_result = await self.db.execute(
            select(DebateMessage)
            .where(DebateMessage.debate_id == debate.id)
            .order_by(DebateMessage.created_at)
        )
        all_messages = list(m_result.scalars().all())

        # ------------------------------------------------------------------
        # Step 1: Judge the debate
        # ------------------------------------------------------------------
        judge_result = await self._run_judge(
            debate, participants, participant_data, all_messages
        )

        # ------------------------------------------------------------------
        # Step 2: Persona consistency evaluation (separate from judge)
        # ------------------------------------------------------------------
        consistency_scores = await self._run_persona_consistency(
            participants, participant_data, all_messages
        )

        # ------------------------------------------------------------------
        # Step 3: Map anonymized winner back to real participant
        # ------------------------------------------------------------------
        winner_label = judge_result.winner
        winner_participant_id = None
        winner_name = None
        for pid, data in participant_data.items():
            if data["label"] == winner_label:
                winner_participant_id = pid
                winner_name = data["friend"].name
                break

        # Map anonymized score keys back to real names
        named_scores = {}
        for label, score in judge_result.scores.items():
            for pid, data in participant_data.items():
                if data["label"] == label:
                    named_scores[data["friend"].name] = score
                    break

        # ------------------------------------------------------------------
        # Step 4: Store evaluation
        # ------------------------------------------------------------------
        summary_parts = [
            f"Winner: {winner_name or winner_label}",
            f"Reason: {judge_result.winner_reason}",
            f"Strongest argument: {judge_result.strongest_argument}",
            f"Weakest argument: {judge_result.weakest_argument}",
        ]

        # Build scores JSON with both judge scores and persona consistency
        scores_data = {
            "judge": {name: score.model_dump() for name, score in named_scores.items()},
            "persona_consistency": {
                name: score.model_dump() for name, score in consistency_scores.items()
            },
        }

        evaluation = Evaluation(
            debate_id=debate.id,
            winner_participant_id=winner_participant_id,
            scores_json=scores_data,
            summary="\n".join(summary_parts),
        )
        self.db.add(evaluation)
        await self.db.commit()

        logger.info("Evaluation stored for debate %s. Winner: %s", debate.id, winner_name)

        return {
            "winner_name": winner_name,
            "winner_reason": judge_result.winner_reason,
            "strongest_argument": judge_result.strongest_argument,
            "weakest_argument": judge_result.weakest_argument,
            "scores": {name: score.model_dump() for name, score in named_scores.items()},
            "persona_consistency": {
                name: score.model_dump() for name, score in consistency_scores.items()
            },
        }

    async def _run_judge(
        self,
        debate: Debate,
        participants: list[DebateParticipant],
        participant_data: dict,
        all_messages: list[DebateMessage],
    ) -> JudgeResult:
        """Run the independent judge evaluation with bias mitigation."""

        # Randomize participant order for bias mitigation (PRD Section 19)
        randomized = list(participants)
        random.shuffle(randomized)

        # Build anonymized transcript
        anon_messages = []
        for msg in all_messages:
            data = participant_data.get(msg.participant_id)
            anon_messages.append({
                "participant_label": data["label"] if data else "Unknown",
                "phase": msg.phase,
                "content": msg.content,
            })
        transcript = format_anonymized_transcript(anon_messages)

        # Build participant info for judge (anonymized)
        participants_info = []
        for p in randomized:
            data = participant_data[p.id]
            persona = data["persona_json"]
            traits = ", ".join(persona.get("core_traits", []))
            participants_info.append({
                "label": data["label"],
                "persona_summary": traits or "No persona traits available",
            })

        user_prompt = build_judge_user_prompt(debate.topic, participants_info, transcript)

        logger.info("Running judge for debate %s", debate.id)
        result: JudgeResult = await self.llm.generate_structured(
            system_prompt=JUDGE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
            response_model=JudgeResult,
            temperature=0.3,  # Low temp for consistent evaluation
            max_tokens=1500,
        )

        return result

    async def _run_persona_consistency(
        self,
        participants: list[DebateParticipant],
        participant_data: dict,
        all_messages: list[DebateMessage],
    ) -> dict[str, PersonaConsistencyScore]:
        """Evaluate persona consistency for each participant independently."""
        consistency_scores = {}

        for p in participants:
            data = participant_data[p.id]
            friend_name = data["friend"].name
            persona_json = data["persona_json"]

            # Collect this participant's messages
            participant_messages = [
                msg.content
                for msg in all_messages
                if msg.participant_id == p.id
            ]

            if not participant_messages:
                continue

            user_prompt = build_persona_consistency_prompt(persona_json, participant_messages)

            logger.info("Evaluating persona consistency for %s in debate", friend_name)
            score: PersonaConsistencyScore = await self.llm.generate_structured(
                system_prompt=PERSONA_CONSISTENCY_SYSTEM,
                messages=[{"role": "user", "content": user_prompt}],
                response_model=PersonaConsistencyScore,
                temperature=0.3,
                max_tokens=500,
            )

            consistency_scores[friend_name] = score

        return consistency_scores
