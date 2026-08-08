"""API routes for Friend CRUD and Persona compilation."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.llm.factory import get_llm_provider
from app.schemas import (
    FriendCreate,
    FriendResponse,
    FriendUpdate,
    PersonaCompileRequest,
    PersonaCompileResponse,
    PersonaProfile,
    PersonaUpdateRequest,
)
from app.services import friend_service
from app.services.persona_compiler import compile_persona

router = APIRouter(prefix="/api/friends", tags=["friends"])


# ---------------------------------------------------------------------------
# Friends CRUD
# ---------------------------------------------------------------------------

@router.post("", response_model=FriendResponse, status_code=201)
async def create_friend(data: FriendCreate, db: AsyncSession = Depends(get_db)):
    friend = await friend_service.create_friend(data, db)
    return friend


@router.get("", response_model=list[FriendResponse])
async def list_friends(db: AsyncSession = Depends(get_db)):
    return await friend_service.get_friends(db)


@router.get("/{friend_id}", response_model=FriendResponse)
async def get_friend(friend_id: UUID, db: AsyncSession = Depends(get_db)):
    friend = await friend_service.get_friend(friend_id, db)
    if friend is None:
        raise HTTPException(status_code=404, detail="Friend not found")
    return friend


@router.put("/{friend_id}", response_model=FriendResponse)
async def update_friend(
    friend_id: UUID, data: FriendUpdate, db: AsyncSession = Depends(get_db)
):
    friend = await friend_service.update_friend(friend_id, data, db)
    if friend is None:
        raise HTTPException(status_code=404, detail="Friend not found")
    return friend


@router.delete("/{friend_id}", status_code=204)
async def delete_friend(friend_id: UUID, db: AsyncSession = Depends(get_db)):
    deleted = await friend_service.delete_friend(friend_id, db)
    if not deleted:
        raise HTTPException(status_code=404, detail="Friend not found")


# ---------------------------------------------------------------------------
# Persona compilation
# ---------------------------------------------------------------------------

persona_router = APIRouter(prefix="/api/personas", tags=["personas"])


@persona_router.post("/compile", response_model=PersonaCompileResponse)
async def compile_persona_endpoint(
    data: PersonaCompileRequest,
    db: AsyncSession = Depends(get_db),
):
    llm = get_llm_provider()
    try:
        persona = await compile_persona(data.friend_id, db, llm)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return PersonaCompileResponse(
        id=persona.id,
        friend_id=persona.friend_id,
        persona=PersonaProfile.model_validate(persona.persona_json),
        version=persona.version,
        created_at=persona.created_at,
    )


@persona_router.put("/{friend_id}", response_model=PersonaCompileResponse)
async def update_persona(
    friend_id: UUID,
    data: PersonaUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Allow the user to manually edit a generated persona (PRD Section 8)."""
    from app.models import Persona

    existing = await friend_service.get_latest_persona(friend_id, db)
    if existing is None:
        raise HTTPException(
            status_code=404,
            detail="No persona found for this friend. Compile one first.",
        )

    # Create a new version with the user's edits
    new_persona = Persona(
        friend_id=friend_id,
        persona_json=data.persona.model_dump(),
        version=existing.version + 1,
    )
    db.add(new_persona)
    await db.commit()
    await db.refresh(new_persona)

    return PersonaCompileResponse(
        id=new_persona.id,
        friend_id=new_persona.friend_id,
        persona=data.persona,
        version=new_persona.version,
        created_at=new_persona.created_at,
    )
