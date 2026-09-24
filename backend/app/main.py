"""PersonaArena API."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.debates import router as debates_router
from app.api.friends import persona_router, router as friends_router
from app.core.config import ENV_FILE, settings
from app.core.database import AsyncSessionLocal, engine
from app.core.frontend import mount_frontend
from app.core.identity import OwnerCookieMiddleware
from app.core.security import SecurityHeadersMiddleware
from app.services import debate_runner
from app.services.public_figures import seed_public_figures

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
        # A container is configured through its environment, not a file.
        "loaded" if ENV_FILE.exists() else "absent, using process environment",
    )
    logger.info(
        "Deployment: environment=%s static_dir=%s secure_cookies=%s",
        settings.ENVIRONMENT,
        settings.STATIC_DIR or "(none, API only)",
        settings.cookie_secure,
    )
    if not settings.LLM_API_KEY:
        logger.error(
            "LLM_API_KEY is empty — every model call will be rejected. "
            "Check that %s exists and that this process was restarted "
            "after it was last edited.",
            ENV_FILE,
        )
    if settings.is_production and settings.DATABASE_URL.startswith("sqlite"):
        logger.warning(
            "Running in production on SQLite. Most hosts give a container a "
            "disk that is wiped on every deploy; set DATABASE_URL to Postgres."
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Tidy up after the last process, and make sure the public figures exist."""
    try:
        async with AsyncSessionLocal() as db:
            interrupted = await debate_runner.fail_interrupted(db)
            if interrupted:
                logger.warning(
                    "%d debate(s) were cut off by a restart and marked FAILED",
                    interrupted,
                )
            await seed_public_figures(db)
    except Exception as exc:
        logger.error(
            "The database is not ready: %s. Create the tables first with "
            "`alembic upgrade head` (or `python init_db.py` for local SQLite).",
            exc,
        )
        raise
    yield
    await engine.dispose()


# Any loopback port is allowed alongside the configured origins in development.
# The dev server moves to 5174 when 5173 is taken and `vite preview` serves on
# 4173, and a CORS rejection reaches the browser as a bare "Network Error" with
# nothing in it to explain the cause. Never in production, where the page is
# served from the API's own origin.
LOOPBACK_ORIGIN = r"^http://(localhost|127\.0\.0\.1)(:\d+)?$"


def create_app() -> FastAPI:
    production = settings.is_production

    app = FastAPI(
        title="PersonaArena API",
        version="2.1.0",
        lifespan=lifespan,
        # The interactive docs are a map of the API for anyone who finds
        # them; a public deployment does not publish one.
        docs_url=None if production else "/docs",
        redoc_url=None if production else "/redoc",
        openapi_url=None if production else "/openapi.json",
    )

    # Added innermost first. A CORS preflight is answered before the identity
    # middleware, so it never mints a visitor cookie; the security headers
    # wrap everything, preflights and errors included.
    app.add_middleware(OwnerCookieMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_origin_regex=None if production else LOOPBACK_ORIGIN,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Content-Type"],
    )
    app.add_middleware(SecurityHeadersMiddleware, production=production)

    app.include_router(friends_router)
    app.include_router(persona_router)
    app.include_router(debates_router)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    # Last, so its catch-all never shadows an API route.
    if settings.STATIC_DIR:
        mount_frontend(app, settings.STATIC_DIR)

    return app


_log_effective_config()

app = create_app()
