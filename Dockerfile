# PersonaArena — one image: the API, with the built frontend served from the
# same origin. Build from the repo root:
#
#   docker build -t persona-arena .
#   docker run -p 8000:8000 --env-file .env -e DATABASE_URL=... persona-arena

# ---- 1. Build the frontend ------------------------------------------------
FROM node:22-alpine AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# Empty VITE_API_URL: the page calls the API on its own origin.
RUN npm run build

# ---- 2. The API -----------------------------------------------------------
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY backend/requirements.txt ./
RUN pip install -r requirements.txt

COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
COPY backend/app ./app
COPY --from=frontend /frontend/dist ./static

# Never run as root. /app/data is the one writable place, for anyone who
# points DATABASE_URL at SQLite on a mounted volume.
RUN useradd --create-home --uid 10001 arena \
    && mkdir -p /app/data \
    && chown -R arena:arena /app/data
USER arena

# FORWARDED_ALLOW_IPS: behind a platform's proxy (Render, Railway, Fly, Cloud
# Run) the client address arrives in X-Forwarded-For, and the per-IP rate
# limits need the real one. Only safe because the container is reachable
# solely through that proxy — on a bare VPS, set it to the proxy's address.
ENV ENVIRONMENT=production \
    STATIC_DIR=/app/static \
    PORT=8000 \
    FORWARDED_ALLOW_IPS="*"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.environ.get('PORT', '8000'), timeout=4)" || exit 1

# Migrate, then serve. Exactly one worker: running debates and their event
# buffers live in this process's memory, so a second worker would answer
# stream requests for debates it is not running.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1 --proxy-headers --no-server-header"]
