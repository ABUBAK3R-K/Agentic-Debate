"""Friend and persona persistence.

Keeps database work out of the route handlers.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Friend, Persona
from app.schemas import FriendCreate


async def create_friend(data: FriendCreate, db: AsyncSession) -> Friend:
    friend = Friend(name=data.name, raw_description=data.raw_description)
    db.add(friend)
    await db.commit()
    await db.refresh(friend)
    return friend


async def get_friends(db: AsyncSession) -> list[Friend]:
    result = await db.execute(select(Friend).order_by(Friend.created_at.desc()))
    return list(result.scalars().all())


async def get_friend(friend_id: UUID, db: AsyncSession) -> Friend | None:
    result = await db.execute(select(Friend).where(Friend.id == friend_id))
    return result.scalar_one_or_none()


async def get_latest_persona(friend_id: UUID, db: AsyncSession) -> Persona | None:
    """The most recent persona version for a friend."""
    result = await db.execute(
        select(Persona)
        .where(Persona.friend_id == friend_id)
        .order_by(Persona.version.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def save_persona_edit(
    friend_id: UUID, persona_json: dict, db: AsyncSession
) -> Persona:
    """Save a user's edits as a new persona version.

    Versions accumulate rather than overwrite — the compiler's original output
    stays on record next to whatever the user changed it to.
    """
    latest = await get_latest_persona(friend_id, db)
    persona = Persona(
        friend_id=friend_id,
        persona_json=persona_json,
        version=(latest.version + 1) if latest else 1,
    )
    db.add(persona)
    await db.commit()
    await db.refresh(persona)
    return persona
