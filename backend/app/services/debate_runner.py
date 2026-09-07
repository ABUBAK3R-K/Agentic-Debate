"""Runs debates in the background and broadcasts their events.

The PRD splits starting a debate (`POST /start`) from watching it
(`GET /stream`). That split needs somewhere for events to live in between, so
a running debate gets a :class:`DebateBroadcast`: an append-only buffer that
any number of subscribers can read from, each at its own pace.

Buffering matters — a client that connects to the stream a moment after
starting the debate still receives the opening events rather than joining
mid-argument. The registry is in-process, which is right for the MVP's single
worker; sharing it across workers would mean an external broker.
"""

import asyncio
import logging
from typing import AsyncGenerator
from uuid import UUID

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.llm.errors import redact
from app.llm.factory import get_llm_provider
from app.models import Debate
from app.schemas import SSEDebateEvent
from app.services.debate_engine import DebateEngine

logger = logging.getLogger(__name__)


class DebateBroadcast:
    """An append-only event buffer with async fan-out to subscribers."""

    def __init__(self) -> None:
        self._events: list[SSEDebateEvent] = []
        self._updated = asyncio.Event()
        self.finished = False

    def publish(self, event: SSEDebateEvent) -> None:
        self._events.append(event)
        self._updated.set()

    def finish(self) -> None:
        self.finished = True
        self._updated.set()

    async def subscribe(self) -> AsyncGenerator[SSEDebateEvent, None]:
        """Yield every event from the beginning, then follow along live."""
        index = 0
        while True:
            if index < len(self._events):
                event = self._events[index]
                index += 1
                yield event
                continue
            if self.finished:
                return
            # No await between clearing and re-checking, so an event published
            # in the meantime can't be missed.
            self._updated.clear()
            if index < len(self._events) or self.finished:
                continue
            await self._updated.wait()


_broadcasts: dict[UUID, DebateBroadcast] = {}
_tasks: dict[UUID, asyncio.Task] = {}


def get_broadcast(debate_id: UUID) -> DebateBroadcast | None:
    return _broadcasts.get(debate_id)


def start(debate_id: UUID) -> DebateBroadcast:
    """Begin running a debate in the background, or return the running one."""
    existing = _broadcasts.get(debate_id)
    if existing is not None:
        return existing

    broadcast = DebateBroadcast()
    _broadcasts[debate_id] = broadcast

    # Hold a reference — a bare create_task can be garbage collected mid-run.
    task = asyncio.create_task(_run(debate_id, broadcast))
    _tasks[debate_id] = task
    task.add_done_callback(lambda _: _tasks.pop(debate_id, None))

    return broadcast


async def _run(debate_id: UUID, broadcast: DebateBroadcast) -> None:
    """Drive the engine to completion, publishing as it goes.

    Runs on its own session: it outlives the request that started it.
    """
    try:
        async with AsyncSessionLocal() as db:
            debate = await db.get(Debate, debate_id)
            if debate is None:
                raise ValueError(f"Debate {debate_id} disappeared before it started")

            engine = DebateEngine(
                db,
                get_llm_provider(),
                judge_llm=get_llm_provider(settings.JUDGE_MODEL),
            )
            async for event in engine.run_debate(debate):
                broadcast.publish(event)
    except Exception as exc:
        logger.error("Debate %s crashed: %s", debate_id, exc, exc_info=True)
        broadcast.publish(SSEDebateEvent(event_type="error", content=redact(str(exc))))
    finally:
        broadcast.finish()
