"""Persona Compiler service.

Converts raw natural-language friend descriptions into structured
PersonaProfile JSON using the LLM, then stores the result.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.base import LLMProvider
from app.llm.prompts import PERSONA_COMPILER_SYSTEM, persona_compiler_user_prompt
from app.models import Friend, Persona
from app.schemas import PersonaProfile

logger = logging.getLogger(__name__)


async def compile_persona(
    friend_id,
    db: AsyncSession,
    llm: LLMProvider,
) -> Persona:
    """Run the persona compiler pipeline for a given friend.

    1. Load the friend's raw description.
    2. Call the LLM with the compiler prompt.
    3. Validate the output via Pydantic.
    4. Persist a new Persona row (incrementing version).
    5. Return the Persona ORM object.
    """
    # 1. Load friend
    result = await db.execute(select(Friend).where(Friend.id == friend_id))
    friend = result.scalar_one_or_none()
    if friend is None:
        raise ValueError(f"Friend {friend_id} not found")

    # 2-3. Generate structured persona via LLM
    user_msg = persona_compiler_user_prompt(friend.name, friend.raw_description)

    logger.info("Compiling persona for friend=%s (%s)", friend.id, friend.name)
    persona_profile: PersonaProfile = await llm.generate_structured(
        system_prompt=PERSONA_COMPILER_SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
        response_model=PersonaProfile,
        temperature=0.4,  # Lower temp for extraction accuracy
        max_tokens=1000,
    )

    # 4. Determine next version
    latest = await db.execute(
        select(Persona)
        .where(Persona.friend_id == friend_id)
        .order_by(Persona.version.desc())
        .limit(1)
    )
    latest_persona = latest.scalar_one_or_none()
    next_version = (latest_persona.version + 1) if latest_persona else 1

    # 5. Persist
    persona = Persona(
        friend_id=friend_id,
        persona_json=persona_profile.model_dump(),
        version=next_version,
    )
    db.add(persona)
    await db.commit()
    await db.refresh(persona)

    logger.info("Persona v%d saved for friend=%s", next_version, friend.id)
    return persona
