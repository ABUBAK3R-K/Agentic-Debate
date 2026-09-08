"""PersonaArena API."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.debates import router as debates_router
from app.api.friends import persona_router, router as friends_router
from app.core.config import ENV_FILE, settings

logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)


def _log_effective_config() -> None:
    """Say which model this process is actually going to call, at startup.

    Nothing else in the app ever states it, and the two ways it goes wrong
    both look like a working server until a turn fails minutes later:

    * `.env` is edited while uvicorn is running. `--reload` watches Python
      files, not `.env`, and settings are read once at import — so the
      process keeps calling the old model and every tuned value in the file
      is fiction until someone restarts it.
    * `.env` is not found at all, and the field defaults stand in silently.

    Printing the values that were actually loaded turns both into something
    visible in the first line of the log. The key is reported as present or
    missing, never echoed.
    """
    logger.info(
        "LLM config: provider=%s model=%s judge_model=%s "
        "max_tokens=%s rpm=%s env_file=%s (%s)",
        settings.LLM_PROVIDER,
        settings.LLM_MODEL,
        settings.JUDGE_MODEL or f"{settings.LLM_MODEL} (same as debaters)",
        settings.DEBATE_MAX_TOKENS,
        settings.LLM_REQUESTS_PER_MINUTE,
        ENV_FILE,
        "loaded" if ENV_FILE.exists() else "MISSING",
    )
    if not settings.LLM_API_KEY:
        logger.error(
            "LLM_API_KEY is empty — every model call will be rejected. "
            "Check that %s exists and that this process was restarted "
            "after it was last edited.",
            ENV_FILE,
        )


_log_effective_config()

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
