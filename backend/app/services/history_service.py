"""Reading finished work back: past debates and saved personas.

Everything shown here was already persisted while the debate ran — this module
only queries it. Each list is built from a fixed number of queries rather than
one per row, so it stays quick as history grows.
"""

from collections import defaultdict
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Debate,
    DebateMessage,
    DebateParticipant,
    Evaluation,
    Friend,
    Persona,
)
from app.schemas import (
    DebateMessageResponse,
    DebateSummary,
    DebateTranscriptResponse,
    ParticipantResponse,
    PersonaProfile,
    SavedPersona,
)


async def _participants_by_debate(
    debate_ids: list[UUID], db: AsyncSession
) -> dict[UUID, list[ParticipantResponse]]:
    if not debate_ids:
        return {}
    result = await db.execute(
        select(DebateParticipant, Friend)
        .join(Friend, DebateParticipant.friend_id == Friend.id)
        .where(DebateParticipant.debate_id.in_(debate_ids))
        .order_by(DebateParticipant.slot)
    )
    grouped: dict[UUID, list[ParticipantResponse]] = defaultdict(list)
    for participant, friend in result.all():
        grouped[participant.debate_id].append(ParticipantResponse(
            id=participant.id,
            friend_id=participant.friend_id,
            friend_name=friend.name,
            position=participant.position,
        ))
    return grouped


async def _winners_by_debate(
    debate_ids: list[UUID], db: AsyncSession
) -> dict[UUID, UUID | None]:
    if not debate_ids:
        return {}
    result = await db.execute(
        select(Evaluation.debate_id, Evaluation.winner_participant_id)
        .where(Evaluation.debate_id.in_(debate_ids))
    )
    return {debate_id: winner for debate_id, winner in result.all()}


def _summary(
    debate: Debate,
    participants: list[ParticipantResponse],
    winner_id: UUID | None,
) -> dict:
    return dict(
        id=debate.id,
        topic=debate.topic,
        status=debate.status,
        created_at=debate.created_at,
        completed_at=debate.completed_at,
        participants=participants,
        winner_participant_id=winner_id,
        winner_name=next(
            (p.friend_name for p in participants if p.id == winner_id), None
        ),
    )


async def list_debates(db: AsyncSession) -> list[DebateSummary]:
    """Every debate, newest first, with who argued and who won."""
    debates = list(
        (await db.execute(select(Debate).order_by(Debate.created_at.desc())))
        .scalars()
        .all()
    )
    ids = [debate.id for debate in debates]
    participants = await _participants_by_debate(ids, db)
    winners = await _winners_by_debate(ids, db)

    return [
        DebateSummary(**_summary(d, participants.get(d.id, []), winners.get(d.id)))
        for d in debates
    ]


async def get_transcript(
    debate_id: UUID, db: AsyncSession
) -> DebateTranscriptResponse | None:
    """A saved debate, turn by turn, in the order it was argued."""
    debate = await db.get(Debate, debate_id)
    if debate is None:
        return None

    participants = (await _participants_by_debate([debate_id], db)).get(debate_id, [])
    winner_id = (await _winners_by_debate([debate_id], db)).get(debate_id)

    rows = (
        await db.execute(
            select(DebateMessage)
            .where(DebateMessage.debate_id == debate_id)
            .order_by(DebateMessage.round_number, DebateMessage.created_at)
        )
    ).scalars().all()

    messages = [
        DebateMessageResponse(
            id=row.id,
            participant_id=row.participant_id,
            round_number=row.round_number,
            phase=row.phase,
            content=row.content,
            failed=bool((row.structured_output or {}).get("failed")),
        )
        for row in rows
    ]

    return DebateTranscriptResponse(
        **_summary(debate, participants, winner_id), messages=messages
    )


async def list_personas(db: AsyncSession) -> list[SavedPersona]:
    """Every friend with the latest version of their persona, newest first."""
    friends = list(
        (await db.execute(select(Friend).order_by(Friend.created_at.desc())))
        .scalars()
        .all()
    )

    # Latest version per friend: join each friend's max version back to its row.
    latest_version = (
        select(Persona.friend_id, func.max(Persona.version).label("version"))
        .group_by(Persona.friend_id)
        .subquery()
    )
    latest = {
        persona.friend_id: persona
        for persona in (
            await db.execute(
                select(Persona).join(
                    latest_version,
                    (Persona.friend_id == latest_version.c.friend_id)
                    & (Persona.version == latest_version.c.version),
                )
            )
        ).scalars().all()
    }

    debate_counts = dict(
        (
            await db.execute(
                select(DebateParticipant.friend_id, func.count())
                .group_by(DebateParticipant.friend_id)
            )
        ).all()
    )

    return [
        SavedPersona(
            friend_id=friend.id,
            name=friend.name,
            raw_description=friend.raw_description,
            created_at=friend.created_at,
            persona=(
                PersonaProfile.model_validate(latest[friend.id].persona_json)
                if friend.id in latest
                else None
            ),
            version=latest[friend.id].version if friend.id in latest else None,
            debate_count=debate_counts.get(friend.id, 0),
        )
        for friend in friends
    ]
