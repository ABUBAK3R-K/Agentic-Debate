"""PersonaArena API."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.debates import router as debates_router
from app.api.friends import persona_router, router as friends_router
from app.core.config import settings

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="PersonaArena API", version="2.0.0")

# Any loopback port is allowed alongside the configured origins. The dev
# server moves to 5174 when 5173 is taken and `vite preview` serves on 4173,
# and a CORS rejection reaches the browser as a bare "Network Error" with
# nothing in it to explain the cause.
LOOPBACK_ORIGIN = r"^http://(localhost|127\.0\.0\.1)(:\d+)?$"

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=LOOPBACK_ORIGIN,
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
