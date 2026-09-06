"""Persona compiler.

Turns a raw, user-written description into a structured, validated persona.
The raw text is never handed to a debate agent as its system prompt — it is
always compiled first.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.llm.base import LLMProvider
from app.llm.prompts import PERSONA_COMPILER_SYSTEM, persona_compiler_user_prompt
from app.llm.structured import generate_structured_resilient
from app.models import Persona
from app.schemas import PersonaProfile
from app.services import friend_service

logger = logging.getLogger(__name__)


async def compile_persona(
    friend_id,
    db: AsyncSession,
    llm: LLMProvider,
) -> Persona:
    """Compile a friend's description into a stored persona version.

    raw description → LLM → Pydantic validation → stored persona
    """
    friend = await friend_service.get_friend(friend_id, db)
    if friend is None:
        raise ValueError(f"Friend {friend_id} not found")

    logger.info("Compiling persona for %s (%s)", friend.id, friend.name)
    profile: PersonaProfile = await generate_structured_resilient(
        llm,
        system_prompt=PERSONA_COMPILER_SYSTEM,
        messages=[{
            "role": "user",
            "content": persona_compiler_user_prompt(
                friend.name, friend.raw_description
            ),
        }],
        response_model=PersonaProfile,
        temperature=settings.COMPILER_TEMPERATURE,
        max_tokens=settings.COMPILER_MAX_TOKENS,
        context=f"persona compilation for friend {friend.id}",
    )

    persona = await friend_service.save_persona_edit(
        friend_id, profile.model_dump(), db
    )
    logger.info("Persona v%d saved for %s", persona.version, friend.id)
    return persona
