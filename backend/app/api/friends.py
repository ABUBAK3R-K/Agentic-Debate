"""Friend and persona routes."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.llm.factory import get_llm_provider
from app.llm.structured import StructuredOutputError
from app.schemas import (
    FriendCreate,
    FriendResponse,
    PersonaCompileRequest,
    PersonaCompileResponse,
    PersonaProfile,
    PersonaUpdateRequest,
)
from app.services import friend_service
from app.services.persona_compiler import compile_persona

router = APIRouter(prefix="/api/friends", tags=["friends"])
persona_router = APIRouter(prefix="/api/personas", tags=["personas"])


@router.post("", response_model=FriendResponse, status_code=201)
async def create_friend(data: FriendCreate, db: AsyncSession = Depends(get_db)):
    return await friend_service.create_friend(data, db)


@router.get("", response_model=list[FriendResponse])
async def list_friends(db: AsyncSession = Depends(get_db)):
    return await friend_service.get_friends(db)


@persona_router.post("/compile", response_model=PersonaCompileResponse)
async def compile_persona_endpoint(
    data: PersonaCompileRequest,
    db: AsyncSession = Depends(get_db),
):
    """Compile a friend's raw description into a structured persona.

    The result is returned for the user to review and edit before it is used.
    """
    try:
        persona = await compile_persona(data.friend_id, db, get_llm_provider())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except StructuredOutputError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"The persona compiler did not return a usable persona: {exc}",
        )

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
    """Save the user's edits to a compiled persona as a new version."""
    if await friend_service.get_friend(friend_id, db) is None:
        raise HTTPException(status_code=404, detail="Friend not found")

    persona = await friend_service.save_persona_edit(
        friend_id, data.persona.model_dump(), db
    )
    return PersonaCompileResponse(
        id=persona.id,
        friend_id=persona.friend_id,
        persona=data.persona,
        version=persona.version,
        created_at=persona.created_at,
    )
