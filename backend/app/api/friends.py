"""Friend and persona routes.

Every route is scoped to the visitor making the request (app.core.identity).
Someone else's friend answers 404, exactly like a friend that does not exist,
so an id reveals nothing about whether it is in use.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.identity import current_owner
from app.core.security import rate_limited
from app.llm.factory import get_llm_provider
from app.llm.structured import StructuredOutputError
from app.schemas import (
    FriendCreate,
    FriendResponse,
    PersonaCompileRequest,
    PersonaCompileResponse,
    PersonaProfile,
    PersonaUpdateRequest,
    SavedPersona,
)
from app.services import friend_service, history_service
from app.services.persona_compiler import compile_persona

router = APIRouter(prefix="/api/friends", tags=["friends"])
persona_router = APIRouter(prefix="/api/personas", tags=["personas"])


@router.post(
    "",
    response_model=FriendResponse,
    status_code=201,
    dependencies=[Depends(rate_limited("friends", "RATE_LIMIT_FRIENDS_PER_HOUR"))],
)
async def create_friend(
    data: FriendCreate,
    owner: str = Depends(current_owner),
    db: AsyncSession = Depends(get_db),
):
    return await friend_service.create_friend(data, owner, db)


@router.get("", response_model=list[FriendResponse])
async def list_friends(
    owner: str = Depends(current_owner),
    db: AsyncSession = Depends(get_db),
):
    """The visitor's own friends."""
    return await friend_service.get_friends(owner, db)


@persona_router.get("", response_model=list[SavedPersona])
async def list_personas(
    owner: str = Depends(current_owner),
    db: AsyncSession = Depends(get_db),
):
    """The visitor's friends, then the public figures, each with the latest
    version of their persona."""
    return await history_service.list_personas(owner, db)


@persona_router.post(
    "/compile",
    response_model=PersonaCompileResponse,
    dependencies=[Depends(rate_limited("compile", "RATE_LIMIT_COMPILES_PER_HOUR"))],
)
async def compile_persona_endpoint(
    data: PersonaCompileRequest,
    owner: str = Depends(current_owner),
    db: AsyncSession = Depends(get_db),
):
    """Compile a friend's raw description into a structured persona.

    The result is returned for the user to review and edit before it is used.
    """
    try:
        persona = await compile_persona(data.friend_id, owner, db, get_llm_provider())
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
    owner: str = Depends(current_owner),
    db: AsyncSession = Depends(get_db),
):
    """Save the user's edits to a compiled persona as a new version.

    Public figures are shared, so they are never edited in place; the
    frontend saves an edited public figure as the visitor's own copy.
    """
    if await friend_service.get_owned_friend(friend_id, owner, db) is None:
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
