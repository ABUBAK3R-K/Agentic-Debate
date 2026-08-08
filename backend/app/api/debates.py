"""API routes for Debate creation, control, and SSE streaming."""

import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.llm.factory import get_llm_provider
from app.models import Debate, DebateParticipant, DebateMessage, Friend
from app.schemas import (
    DebateCreateRequest,
    DebateDetailResponse,
    DebateMessageResponse,
    DebateResponse,
    ParticipantResponse,
)
from app.services.debate_engine import DebateEngine

router = APIRouter(prefix="/api/debates", tags=["debates"])


# ---------------------------------------------------------------------------
# Create debate
# ---------------------------------------------------------------------------

@router.post("", response_model=DebateResponse, status_code=201)
async def create_debate(
    data: DebateCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    llm = get_llm_provider()
    engine = DebateEngine(db, llm)

    # Verify all friends exist
    for fid in data.participant_ids:
        result = await db.execute(select(Friend).where(Friend.id == fid))
        if result.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail=f"Friend {fid} not found")

    debate = await engine.create_debate(
        topic=data.topic,
        category=data.category,
        participant_friend_ids=data.participant_ids,
        round_count=data.round_count,
        temperature=data.temperature,
        max_tokens=data.max_tokens,
        top_p=data.top_p,
        model_provider=settings.LLM_PROVIDER,
        model_name=settings.LLM_MODEL,
    )
    return debate


# ---------------------------------------------------------------------------
# List debates
# ---------------------------------------------------------------------------

@router.get("", response_model=list[DebateResponse])
async def list_debates(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Debate).order_by(Debate.created_at.desc()))
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Get debate detail
# ---------------------------------------------------------------------------

@router.get("/{debate_id}", response_model=DebateDetailResponse)
async def get_debate(debate_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Debate).where(Debate.id == debate_id))
    debate = result.scalar_one_or_none()
    if debate is None:
        raise HTTPException(status_code=404, detail="Debate not found")

    # Load participants with friend names
    p_result = await db.execute(
        select(DebateParticipant).where(DebateParticipant.debate_id == debate_id)
    )
    participants = []
    for p in p_result.scalars().all():
        f_result = await db.execute(select(Friend).where(Friend.id == p.friend_id))
        friend = f_result.scalar_one()
        participants.append(ParticipantResponse(
            id=p.id,
            friend_id=p.friend_id,
            friend_name=friend.name,
            position=p.position,
            participant_label=p.participant_label,
        ))

    # Load messages
    m_result = await db.execute(
        select(DebateMessage)
        .where(DebateMessage.debate_id == debate_id)
        .order_by(DebateMessage.created_at)
    )
    messages = []
    for msg in m_result.scalars().all():
        # Find participant name
        p_name = next(
            (p.friend_name for p in participants if p.id == msg.participant_id),
            "Unknown",
        )
        messages.append(DebateMessageResponse(
            id=msg.id,
            participant_id=msg.participant_id,
            participant_name=p_name,
            round_number=msg.round_number,
            phase=msg.phase,
            content=msg.content,
            created_at=msg.created_at,
        ))

    return DebateDetailResponse(
        id=debate.id,
        topic=debate.topic,
        category=debate.category,
        status=debate.status,
        round_count=debate.round_count,
        model_provider=debate.model_provider,
        model_name=debate.model_name,
        temperature=debate.temperature,
        created_at=debate.created_at,
        completed_at=debate.completed_at,
        participants=participants,
        messages=messages,
    )


# ---------------------------------------------------------------------------
# Start debate + SSE stream
# ---------------------------------------------------------------------------

@router.post("/{debate_id}/start")
async def start_debate(debate_id: UUID, db: AsyncSession = Depends(get_db)):
    """Start a debate. Returns an SSE stream of debate events."""
    result = await db.execute(select(Debate).where(Debate.id == debate_id))
    debate = result.scalar_one_or_none()
    if debate is None:
        raise HTTPException(status_code=404, detail="Debate not found")
    if debate.status != "CREATED":
        raise HTTPException(
            status_code=400,
            detail=f"Debate cannot be started from status '{debate.status}'",
        )

    llm = get_llm_provider()
    engine = DebateEngine(db, llm)

    async def event_generator():
        async for event in engine.run_debate(debate):
            yield f"data: {event.model_dump_json()}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Get debate stream (reconnect-safe)
# ---------------------------------------------------------------------------

@router.get("/{debate_id}/stream")
async def stream_debate(debate_id: UUID, db: AsyncSession = Depends(get_db)):
    """Subscribe to the live SSE stream for a debate.

    If the debate is already completed, returns the full transcript as events.
    """
    result = await db.execute(select(Debate).where(Debate.id == debate_id))
    debate = result.scalar_one_or_none()
    if debate is None:
        raise HTTPException(status_code=404, detail="Debate not found")

    # For completed debates, replay stored messages as SSE events
    if debate.status in ("COMPLETED", "JUDGING"):
        async def replay_generator():
            m_result = await db.execute(
                select(DebateMessage)
                .where(DebateMessage.debate_id == debate_id)
                .order_by(DebateMessage.created_at)
            )
            for msg in m_result.scalars().all():
                p_result = await db.execute(
                    select(DebateParticipant).where(DebateParticipant.id == msg.participant_id)
                )
                participant = p_result.scalar_one()
                f_result = await db.execute(
                    select(Friend).where(Friend.id == participant.friend_id)
                )
                friend = f_result.scalar_one()
                event_data = json.dumps({
                    "event_type": "message",
                    "phase": msg.phase,
                    "round_number": msg.round_number,
                    "participant_name": friend.name,
                    "content": msg.content,
                })
                yield f"data: {event_data}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            replay_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    raise HTTPException(
        status_code=400,
        detail=f"Debate is in status '{debate.status}'. Use POST /start to begin.",
    )


# ---------------------------------------------------------------------------
# Get debate result
# ---------------------------------------------------------------------------

@router.get("/{debate_id}/result")
async def get_debate_result(debate_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get the final evaluation result for a completed debate."""
    result = await db.execute(select(Debate).where(Debate.id == debate_id))
    debate = result.scalar_one_or_none()
    if debate is None:
        raise HTTPException(status_code=404, detail="Debate not found")

    if debate.status not in ("COMPLETED", "JUDGING"):
        raise HTTPException(
            status_code=400,
            detail="Debate has not completed yet",
        )

    # Load evaluation
    from app.models import Evaluation
    eval_result = await db.execute(
        select(Evaluation).where(Evaluation.debate_id == debate_id)
    )
    evaluation = eval_result.scalar_one_or_none()

    if evaluation is None:
        return {"debate_id": str(debate_id), "status": debate.status, "evaluation": None}

    # Map winner participant ID to friend name
    winner_name = None
    if evaluation.winner_participant_id:
        p_result = await db.execute(
            select(DebateParticipant).where(
                DebateParticipant.id == evaluation.winner_participant_id
            )
        )
        winner_p = p_result.scalar_one_or_none()
        if winner_p:
            f_result = await db.execute(
                select(Friend).where(Friend.id == winner_p.friend_id)
            )
            winner_friend = f_result.scalar_one_or_none()
            if winner_friend:
                winner_name = winner_friend.name

    scores_data = evaluation.scores_json or {}

    return {
        "debate_id": str(debate_id),
        "status": debate.status,
        "winner_name": winner_name,
        "summary": evaluation.summary,
        "judge_scores": scores_data.get("judge", {}),
        "persona_consistency": scores_data.get("persona_consistency", {}),
    }

