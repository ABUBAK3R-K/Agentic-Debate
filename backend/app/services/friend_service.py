"""CRUD operations for the Friend model.

Keeps business logic out of route handlers (instruction.md rule).
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Friend, Persona
from app.schemas import FriendCreate, FriendUpdate


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


async def update_friend(
    friend_id: UUID, data: FriendUpdate, db: AsyncSession
) -> Friend | None:
    friend = await get_friend(friend_id, db)
    if friend is None:
        return None
    if data.name is not None:
        friend.name = data.name
    if data.raw_description is not None:
        friend.raw_description = data.raw_description
    await db.commit()
    await db.refresh(friend)
    return friend


async def delete_friend(friend_id: UUID, db: AsyncSession) -> bool:
    friend = await get_friend(friend_id, db)
    if friend is None:
        return False
    await db.delete(friend)
    await db.commit()
    return True


async def get_latest_persona(friend_id: UUID, db: AsyncSession) -> Persona | None:
    """Return the most recent persona version for a friend."""
    result = await db.execute(
        select(Persona)
        .where(Persona.friend_id == friend_id)
        .order_by(Persona.version.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()
