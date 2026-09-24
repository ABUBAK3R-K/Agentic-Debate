"""Reading finished work back: past debates and saved personas.

Everything shown here was already persisted while the debate ran — this module
only queries it. Each list is built from a fixed number of queries rather than
one per row, so it stays quick as history grows.

Every query is scoped to the visitor asking: their own debates, their own
personas, and the public figures everyone shares.
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
from app.services.friend_service import visible_to
from app.services.public_figures import category_rank


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


# The past-debates page lists at most this many, newest first.
DEBATE_LIST_LIMIT = 200


async def get_owned_debate(
    debate_id: UUID, owner_key: str, db: AsyncSession
) -> Debate | None:
    """A debate this visitor set up, or None — whether it is missing or
    someone else's, the answer is the same, so ids reveal nothing."""
    debate = await db.get(Debate, debate_id)
    if debate is None or debate.owner_key != owner_key:
        return None
    return debate


async def list_debates(owner_key: str, db: AsyncSession) -> list[DebateSummary]:
    """The visitor's debates, newest first, with who argued and who won."""
    debates = list(
        (
            await db.execute(
                select(Debate)
                .where(Debate.owner_key == owner_key)
                .order_by(Debate.created_at.desc())
                .limit(DEBATE_LIST_LIMIT)
            )
        )
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
    debate_id: UUID, owner_key: str, db: AsyncSession
) -> DebateTranscriptResponse | None:
    """A saved debate, turn by turn, in the order it was argued."""
    debate = await get_owned_debate(debate_id, owner_key, db)
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


async def list_personas(owner_key: str, db: AsyncSession) -> list[SavedPersona]:
    """The visitor's friends, newest first, then the public figures.

    Each comes with the latest version of its persona. Debate counts cover
    only this visitor's debates — how often anyone else has picked a public
    figure is not theirs to see.
    """
    friends = list(
        (
            await db.execute(
                select(Friend)
                .where(visible_to(owner_key))
                .order_by(Friend.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    own = [f for f in friends if not f.is_public]
    public = sorted(
        (f for f in friends if f.is_public),
        key=lambda f: (category_rank(f.category), f.name),
    )
    ids = [friend.id for friend in friends]

    # Latest version per friend: join each friend's max version back to its row.
    latest_version = (
        select(Persona.friend_id, func.max(Persona.version).label("version"))
        .where(Persona.friend_id.in_(ids))
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
    } if ids else {}

    debate_counts = dict(
        (
            await db.execute(
                select(DebateParticipant.friend_id, func.count())
                .join(Debate, Debate.id == DebateParticipant.debate_id)
                .where(Debate.owner_key == owner_key)
                .group_by(DebateParticipant.friend_id)
            )
        ).all()
    )

    return [
        SavedPersona(
            friend_id=friend.id,
            name=friend.name,
            raw_description=friend.raw_description,
            is_public=friend.is_public,
            category=friend.category,
            created_at=friend.created_at,
            persona=(
                PersonaProfile.model_validate(latest[friend.id].persona_json)
                if friend.id in latest
                else None
            ),
            version=latest[friend.id].version if friend.id in latest else None,
            debate_count=debate_counts.get(friend.id, 0),
        )
        for friend in own + public
    ]
