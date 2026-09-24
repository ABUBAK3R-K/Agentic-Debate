"""Public-figure personas every visitor can pick.

Actors, cricketers and footballers, each written up from how they come across
in public — interviews, press conferences, on screen and on the field — so a
visitor can set two of them against each other and judge for themselves
whether the simulation argues the way the real person comes across.

They are curated, not compiled: `app/data/public_figures.json` is the source,
and :func:`seed_public_figures` writes it into the database at startup. Each
figure gets a fixed id derived from its slug, so reseeding updates the same
rows and debates that used a figure keep pointing at it. A changed persona is
saved as a new version, the same way a visitor's edit is.

Nobody owns a public figure, so nobody can edit or recompile it in place
(see friend_service). The safety rule still holds: these are simulations of a
public image, never a claim about what the person actually thinks.
"""

import json
import logging
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Friend, Persona
from app.schemas import MAX_DESCRIPTION_CHARS, PersonaProfile
from app.services import friend_service

logger = logging.getLogger(__name__)

DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "public_figures.json"

# Display order, and the only categories a figure may have.
CATEGORIES = ("Indian cinema", "Hollywood", "Cricket", "Football")

_ID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "personaarena/public-figures")


class PublicFigure(BaseModel):
    """One entry in the data file."""
    slug: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    name: str = Field(min_length=1, max_length=100)
    category: Literal[CATEGORIES]
    summary: str = Field(min_length=10, max_length=MAX_DESCRIPTION_CHARS)
    persona: PersonaProfile

    @property
    def id(self) -> uuid.UUID:
        return uuid.uuid5(_ID_NAMESPACE, self.slug)


@lru_cache(maxsize=1)
def load_public_figures() -> tuple[PublicFigure, ...]:
    figures = tuple(
        PublicFigure.model_validate(entry)
        for entry in json.loads(DATA_FILE.read_text(encoding="utf-8"))
    )
    slugs = [figure.slug for figure in figures]
    if len(slugs) != len(set(slugs)):
        raise ValueError(f"Duplicate slug in {DATA_FILE.name}")
    return figures


def category_rank(category: str | None) -> int:
    """Where a category sorts; unknown ones go last."""
    return CATEGORIES.index(category) if category in CATEGORIES else len(CATEGORIES)


async def seed_public_figures(db: AsyncSession) -> int:
    """Write the data file into the database. Returns how many rows changed.

    Idempotent: an unchanged figure touches nothing, so this is safe on every
    startup.
    """
    changed = 0
    for figure in load_public_figures():
        friend = await db.get(Friend, figure.id)
        if friend is None:
            friend = Friend(id=figure.id)
            db.add(friend)
            changed += 1

        # Re-asserted every time: a public id must never end up owned.
        friend.name = figure.name
        friend.raw_description = figure.summary
        friend.category = figure.category
        friend.is_public = True
        friend.owner_key = None
        await db.flush()

        wanted = figure.persona.model_dump()
        latest = await friend_service.get_latest_persona(friend.id, db)
        if latest is None or latest.persona_json != wanted:
            db.add(Persona(
                friend_id=friend.id,
                persona_json=wanted,
                version=(latest.version + 1) if latest else 1,
            ))
            changed += 1

    await db.commit()
    if changed:
        logger.info("Public figures seeded: %d rows written", changed)
    return changed
