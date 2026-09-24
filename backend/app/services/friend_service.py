"""Friend and persona persistence.

Keeps database work out of the route handlers, and is the one place that
decides who may see a friend. Two rules, both fail-closed:

* a visitor sees their own friends and the seeded public figures;
* a visitor edits or recompiles only their own friends — a public figure is
  shared by everyone, so nobody changes it in place.
"""

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Friend, Persona
from app.schemas import FriendCreate


def visible_to(owner_key: str):
    """The SQL condition for friends this visitor may see."""
    return or_(Friend.owner_key == owner_key, Friend.is_public.is_(True))


async def create_friend(data: FriendCreate, owner_key: str, db: AsyncSession) -> Friend:
    friend = Friend(
        name=data.name,
        raw_description=data.raw_description,
        owner_key=owner_key,
    )
    db.add(friend)
    await db.commit()
    await db.refresh(friend)
    return friend


async def get_friends(owner_key: str, db: AsyncSession) -> list[Friend]:
    """The visitor's own friends, newest first."""
    result = await db.execute(
        select(Friend)
        .where(Friend.owner_key == owner_key)
        .order_by(Friend.created_at.desc())
    )
    return list(result.scalars().all())


async def get_friend(friend_id: UUID, db: AsyncSession) -> Friend | None:
    """Any friend by id, regardless of owner. Internal use only."""
    return await db.get(Friend, friend_id)


async def get_visible_friend(
    friend_id: UUID, owner_key: str, db: AsyncSession
) -> Friend | None:
    """A friend this visitor may see and debate with, or None."""
    result = await db.execute(
        select(Friend).where(Friend.id == friend_id, visible_to(owner_key))
    )
    return result.scalar_one_or_none()


async def get_owned_friend(
    friend_id: UUID, owner_key: str, db: AsyncSession
) -> Friend | None:
    """A friend this visitor may edit, or None. Public figures never are."""
    result = await db.execute(
        select(Friend).where(
            Friend.id == friend_id,
            Friend.owner_key == owner_key,
            Friend.is_public.is_(False),
        )
    )
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
    stays on record next to whatever the user changed it to. Callers check
    ownership first.
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
