"""Debate routes: create, start, watch, and read the verdict."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.llm.factory import get_llm_provider
from app.models import Debate, DebateParticipant, Evaluation, Friend
from app.schemas import (
    DebateCreateRequest,
    DebateResponse,
    DebateResultResponse,
    ParticipantResponse,
    ParticipantResult,
    ParticipantScore,
)
from app.services import debate_runner
from app.services.debate_engine import DebateEngine

router = APIRouter(prefix="/api/debates", tags=["debates"])

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # stops nginx buffering the stream
}


async def _load_debate(debate_id: UUID, db: AsyncSession) -> Debate:
    debate = await db.get(Debate, debate_id)
    if debate is None:
        raise HTTPException(status_code=404, detail="Debate not found")
    return debate


async def _participants(debate_id: UUID, db: AsyncSession) -> list[ParticipantResponse]:
    result = await db.execute(
        select(DebateParticipant, Friend)
        .join(Friend, DebateParticipant.friend_id == Friend.id)
        .where(DebateParticipant.debate_id == debate_id)
        .order_by(DebateParticipant.slot)
    )
    return [
        ParticipantResponse(
            id=participant.id,
            friend_id=participant.friend_id,
            friend_name=friend.name,
            position=participant.position,
        )
        for participant, friend in result.all()
    ]


async def _debate_response(debate: Debate, db: AsyncSession) -> DebateResponse:
    return DebateResponse(
        id=debate.id,
        topic=debate.topic,
        status=debate.status,
        model_provider=debate.model_provider,
        model_name=debate.model_name,
        temperature=debate.temperature,
        top_p=debate.top_p,
        max_tokens=debate.max_tokens,
        created_at=debate.created_at,
        completed_at=debate.completed_at,
        participants=await _participants(debate.id, db),
    )


@router.post("", response_model=DebateResponse, status_code=201)
async def create_debate(
    data: DebateCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create a debate between exactly two friends.

    Model settings come from the environment and are stored on the debate, so
    a debate always records the configuration it actually ran under.
    """
    for friend_id in data.participant_ids:
        if await db.get(Friend, friend_id) is None:
            raise HTTPException(status_code=404, detail=f"Friend {friend_id} not found")

    if len(set(data.participant_ids)) != 2:
        raise HTTPException(
            status_code=400, detail="A debate needs two different friends"
        )

    engine = DebateEngine(db, get_llm_provider())
    debate = await engine.create_debate(
        topic=data.topic,
        participant_friend_ids=data.participant_ids,
        model_provider=settings.LLM_PROVIDER,
        model_name=settings.LLM_MODEL,
        temperature=settings.DEBATE_TEMPERATURE,
        top_p=settings.DEBATE_TOP_P,
        max_tokens=settings.DEBATE_MAX_TOKENS,
    )
    return await _debate_response(debate, db)


@router.post("/{debate_id}/start", status_code=202)
async def start_debate(debate_id: UUID, db: AsyncSession = Depends(get_db)):
    """Start running a debate in the background.

    Returns immediately; watch it at `GET /api/debates/{id}/stream`.
    """
    debate = await _load_debate(debate_id, db)

    if debate.status != "CREATED" and debate_runner.get_broadcast(debate_id) is None:
        raise HTTPException(
            status_code=409,
            detail=f"Debate cannot be started from status '{debate.status}'",
        )

    debate_runner.start(debate_id)
    return {"debate_id": str(debate_id), "status": "RUNNING"}


@router.get("/{debate_id}/stream")
async def stream_debate(debate_id: UUID, db: AsyncSession = Depends(get_db)):
    """Server-sent events for a running debate, from its first event on."""
    await _load_debate(debate_id, db)

    broadcast = debate_runner.get_broadcast(debate_id)
    if broadcast is None:
        raise HTTPException(
            status_code=409,
            detail="This debate is not running. Start it first.",
        )

    async def events():
        async for event in broadcast.subscribe():
            yield f"data: {event.model_dump_json()}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        events(), media_type="text/event-stream", headers=SSE_HEADERS
    )


@router.get("/{debate_id}/result", response_model=DebateResultResponse)
async def get_debate_result(debate_id: UUID, db: AsyncSession = Depends(get_db)):
    """The verdict for a finished debate."""
    debate = await _load_debate(debate_id, db)

    result = await db.execute(
        select(Evaluation).where(Evaluation.debate_id == debate_id)
    )
    evaluation = result.scalar_one_or_none()
    if evaluation is None:
        raise HTTPException(
            status_code=409,
            detail=f"Debate has not been judged yet (status '{debate.status}')",
        )

    stored = evaluation.scores_json or {}
    scores = stored.get("scores", {})
    participants = await _participants(debate_id, db)

    winner_name = next(
        (p.friend_name for p in participants if p.id == evaluation.winner_participant_id),
        None,
    )

    return DebateResultResponse(
        debate_id=debate.id,
        topic=debate.topic,
        status=debate.status,
        winner_name=winner_name,
        winner_reason=evaluation.summary,
        strongest_argument=stored.get("strongest_argument"),
        weakest_argument=stored.get("weakest_argument"),
        participants=[
            ParticipantResult(
                participant_id=p.id,
                name=p.friend_name,
                position=p.position or "",
                is_winner=p.id == evaluation.winner_participant_id,
                scores=ParticipantScore.model_validate(scores[str(p.id)]),
            )
            for p in participants
            if str(p.id) in scores
        ],
    )
