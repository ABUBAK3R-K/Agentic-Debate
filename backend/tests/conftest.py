"""Shared test fixtures.

Tests run against an in-memory SQLite database and a scripted fake LLM, so the
suite never touches Postgres or a real provider.
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("LLM_API_KEY", "test-key")
# The repo's .env is read too, and tuning written there for a real provider
# must not change what the suite expects a request body to contain or how
# long the pacer holds a test. Environment variables win over .env.
os.environ.setdefault("GEMINI_THINKING_LEVEL", "")
os.environ.setdefault("LLM_REQUESTS_PER_MINUTE", "0")

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models import Friend, Persona


@pytest.fixture
async def db():
    """A fresh in-memory database per test."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


PERSONA_FIXTURE = {
    "name": "Rahul",
    "core_traits": ["skeptical", "data-driven"],
    "values": ["rigor", "honesty"],
    "reasoning_style": {
        "decision_making": "deliberate",
        "risk_tolerance": "low",
        "evidence_preference": "quantitative",
    },
    "strengths": ["spots weak claims"],
    "weaknesses": ["slow to commit"],
    "communication_style": {
        "tone": "dry",
        "directness": "very direct",
        "humor": "deadpan",
    },
    "debate_style": {
        "aggressiveness": "measured",
        "preferred_tactics": ["asks for sources"],
    },
}


@pytest.fixture
async def two_friends(db):
    """Two friends, each with a compiled persona."""
    friends = []
    for name in ("Rahul", "Aman"):
        friend = Friend(name=name, raw_description=f"{name} is a friend of mine.")
        db.add(friend)
        await db.flush()
        db.add(Persona(
            friend_id=friend.id,
            persona_json={**PERSONA_FIXTURE, "name": name},
            version=1,
        ))
        friends.append(friend)
    await db.commit()
    return friends
