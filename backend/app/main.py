"""PersonaArena API."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.debates import router as debates_router
from app.api.friends import persona_router, router as friends_router
from app.core.config import settings

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="PersonaArena API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(friends_router)
app.include_router(persona_router)
app.include_router(debates_router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
