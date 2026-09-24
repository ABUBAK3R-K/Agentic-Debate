# PersonaArena

**Same model. Different minds.**

Describe two friends' personalities in plain English, or pick two public
figures. PersonaArena compiles each into a structured persona, runs a four-round
debate between them — both agents driven by the *same* model with the *same*
settings — and then hands the transcript to an independent judge that never
learns whose argument is whose.

The question the product is built around: can one underlying model hold two
genuinely distinct personalities apart, under pressure, across four rounds?

> Everything the arena produces is a fictional simulation — of what the user
> wrote, or of a public figure's public image. It never claims to represent what
> a real person thinks.

---

## How it works

```
friend A description ─┐
                      ├─→ persona compiler (LLM) ─→ structured JSON ─→ user reviews/edits
friend B description ─┘

topic ─→ debate created ─→ backend assigns FOR / AGAINST
             │
             ├─ round 1  OPENING    A then B
             ├─ round 2  REBUTTAL   A then B
             ├─ round 3  COUNTER    A then B
             └─ round 4  CLOSING    A then B
                          │
                          └─→ blind judge ─→ scores, winner, rationale
```

The backend owns the state machine end to end:

```
CREATED → POSITIONING → OPENING → REBUTTAL → COUNTER → CLOSING → JUDGING → COMPLETED
```

The models generate content when asked. They never decide what happens next,
and they never pick their own side — positions are assigned by the backend, or
both agents drift toward whichever side sounds safer.

### Streaming

`POST /api/debates/{id}/start` hands the debate to `debate_runner`, which runs
the engine on its own database session in the background and publishes every
event into a `DebateBroadcast`. `GET /api/debates/{id}/stream` subscribes to
that buffer from its first event, so a client that connects a moment late still
sees the opening.

Each turn emits `turn_start`, then a run of `token` events as the argument is
written, then exactly one of `message` (the authoritative final text) or
`turn_failed`. Tokens are a live preview; `message` is the truth.

Turns are generated as JSON, not prose, so the argument text has to be pulled
out of a half-finished JSON object while it streams — `JsonStringFieldExtractor`
does that. The screen gets live text; the backend still gets validated
structured output.

### The blind judge

A separate LLM call, never one of the debaters' instances. It receives the
topic, the personas and the full transcript, but sees the debaters only as
`Participant A` and `Participant B`, with the order randomized per debate. The
backend maps the result back to friend IDs afterwards. Scores come back per
participant across logic, evidence, rebuttal and persuasiveness.

### Private by default, no accounts

Each browser is issued an anonymous id in an `HttpOnly`, `SameSite=Lax` cookie
the first time it calls the API, and every friend, persona and debate it creates
is stamped with a SHA-256 of that id. Everything is scoped to it: another
browser cannot list, read, edit, compile, start or stream what this one made,
and gets the same 404 as for an id that never existed. The database never holds
the token itself. The trade-off is the usual one for anonymous sessions:
clearing site data or switching devices starts an empty arena.

### Public figures

Twenty shared personas — Indian cinema, Hollywood, cricket and football — are
seeded at startup from `backend/app/data/public_figures.json`, so a visitor can
set, say, Dhoni against Kohli and judge whether the simulation argues the way
they come across. Each is written from public image only: interviews, press
conferences, on screen and on the field. Nothing about private life, health,
politics or controversies, and no trait that would name the person to the blind
judge. They are read-only for everyone; editing one on the setup screen saves
the visitor's own private copy. Reseeding is idempotent, and a changed entry
becomes a new persona version.

### Identical settings, by construction

Model, temperature, top-p and max tokens come from environment variables, are
written onto the debate record when it is created, and are never hardcoded in
the engine. The only differences between the two agents are persona, assigned
position and conversation context. A finished debate therefore records the exact
configuration it ran under.

---

## Stack

| Layer | Choices |
|---|---|
| Backend | Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy (async), Alembic, httpx |
| Database | PostgreSQL via asyncpg; SQLite via aiosqlite for local runs and tests |
| Providers | OpenAI and Gemini behind one `LLMProvider` abstraction |
| Frontend | React 19, Vite, React Router, Axios, hand-written CSS design tokens |
| Tests | pytest + pytest-asyncio — 236 tests, no network, no Postgres |
| Deploy | One Docker image (API + built frontend), Alembic migrations |

---

## Project layout

```
backend/app/
  api/         FastAPI routers — thin, no business logic
  services/    DebateEngine, JudgeEngine, debate_runner, persona_compiler,
               friend_service
  llm/         LLMProvider ABC, OpenAI + Gemini providers, prompts, structured
               output recovery, transport pacing, error redaction
  models/      SQLAlchemy ORM
  schemas/     Pydantic request/response + structured LLM output
  core/        config (env settings), database (async engine/session),
               identity (visitor cookie), security (headers, rate limits),
               frontend (serving the built SPA)
  data/        public_figures.json — the seeded public-figure personas
backend/alembic/ migrations; `alembic upgrade head` creates the schema
backend/tests/ pytest suite; fakes.py holds the scripted FakeLLM

frontend/src/
  pages/       Landing, Setup, LiveDebate, Verdict, PastDebates,
               SavedDebate, Personas
  components/  SiteHeader, Aisle, PersonaSheet, SimulationNotice,
               TranscriptSide
  services/    Axios API client
  hooks/       useDebateStream — the SSE reducer
  index.css    Design tokens and primitives
  screens.css  Per-screen layout
```

Reference documents that outrank anything inferred from the code:
`PRD.md` (scope and behavior), `design.md` (visual identity),
`CLAUDE.md` (working rules for this repo).

---

## Getting started

### 1. Configure

```bash
cp .env.example .env
```

Fill in `LLM_API_KEY`, and set `LLM_PROVIDER` / `LLM_MODEL` / `LLM_BASE_URL` to
match it. Leaving `DATABASE_URL` unset falls back to a local SQLite file, which
is enough to run the whole product.

Notable settings:

| Variable | Default | Notes |
|---|---|---|
| `LLM_PROVIDER` | `gemini` | `openai` or `gemini` |
| `LLM_MODEL` | `gemini-1.5-pro` | Never hardcoded in the engine |
| `DEBATE_TEMPERATURE` / `DEBATE_TOP_P` / `DEBATE_MAX_TOKENS` | `0.8` / `1.0` / `500` | Identical for both debaters |
| `JUDGE_TEMPERATURE` / `JUDGE_MAX_TOKENS` | `0.3` / `1500` | The judge runs cooler so scoring stays stable |
| `COMPILER_TEMPERATURE` / `COMPILER_MAX_TOKENS` | `0.4` / `1000` | Compilation is extraction, not creation |
| `LLM_MIN_REQUEST_INTERVAL` | `4.0` | Seconds between provider calls — see below |
| `CORS_ORIGINS` | `http://localhost:5173` | Comma-separated |

**Pacing matters on a free tier.** One debate is nine requests back to back,
which walks straight into a per-minute rate limit. `app/llm/transport.py` holds
a process-wide minimum interval plus retry-with-backoff that honours the
provider's own `Retry-After` / `retryDelay`. Raise `LLM_MIN_REQUEST_INTERVAL` if
you still see 429s; set it to `0` on a paid key.

### 2. Backend

From `backend/` — dependencies live in `backend/.venv`:

```bash
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
.venv/Scripts/python.exe -m alembic upgrade head          # create tables
.venv/Scripts/python.exe -m uvicorn app.main:app --reload # http://localhost:8000
```

The public figures are written into the database when the server starts.

On macOS or Linux the interpreter is `.venv/bin/python` instead.

### 3. Frontend

From `frontend/`:

```bash
npm install
npm run dev        # http://localhost:5173
```

`VITE_API_URL` overrides the API base if the backend is not on
`http://localhost:8000`.

### 4. Tests

```bash
cd backend && .venv/Scripts/python.exe -m pytest     # 236 tests
cd backend && .venv/Scripts/python.exe -m pip_audit -r requirements.txt
cd frontend && npm run lint && npm audit
```

The suite runs against in-memory SQLite and a scripted `FakeLLM`, so it never
touches Postgres or a provider and needs no API key.

---

## API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/friends` | Create a friend from a raw description |
| `GET` | `/api/friends` | List friends |
| `POST` | `/api/personas/compile` | Compile a description into a structured persona |
| `PUT` | `/api/personas/{friend_id}` | Save the user's edits to a persona |
| `POST` | `/api/debates` | Create a debate between exactly two friends |
| `POST` | `/api/debates/{id}/start` | Run the debate in the background (202) |
| `GET` | `/api/debates/{id}/stream` | SSE event stream for a running debate |
| `GET` | `/api/debates/{id}/result` | The verdict for a finished debate |
| `GET` | `/api/health` | Liveness |

Every route except health is scoped to the calling browser's visitor cookie.
`GET /api/personas` returns the visitor's own personas followed by the public
figures (`is_public: true`, with a `category`). Creating friends, compiling and
starting debates are rate-limited per client IP and answer `429` with
`Retry-After`; a full arena answers `503`.

Interactive docs at `http://localhost:8000/docs` in development. Production
does not publish them.

### Persona shape

```json
{
  "name": "",
  "core_traits": [],
  "values": [],
  "reasoning_style": { "decision_making": "", "risk_tolerance": "", "evidence_preference": "" },
  "strengths": [],
  "weaknesses": [],
  "communication_style": { "tone": "", "directness": "", "humor": "" },
  "debate_style": { "aggressiveness": "", "preferred_tactics": [] }
}
```

A raw description is never used directly as a system prompt. It is always
compiled, validated against this schema, shown to the user for editing, and only
then stored.

### Data model

`friends`, `personas`, `debates`, `debate_participants`, `debate_messages`,
`evaluations`. `friends` and `debates` carry `owner_key` (the visitor); public
figures are `friends` rows with `is_public` and a `category`.

---

## Deploying

The repo builds into **one container**: the frontend is compiled in a Node
stage and served by the API from the same origin, which keeps the visitor
cookie first-party. On start it runs `alembic upgrade head`, marks any debate a
previous process was cut off in as failed, seeds the public figures, and serves
on `$PORT` as a non-root user.

```bash
docker build -t persona-arena .
docker run -p 8000:8000 --env-file .env -e DATABASE_URL=postgresql://... persona-arena
```

Or with a bundled Postgres: set `POSTGRES_PASSWORD` in `.env`, run
`docker compose up --build`, and open `http://localhost:8000`.

On a platform (Render, Railway, Fly.io, Cloud Run), point it at the
`Dockerfile`, attach a managed Postgres, and set the variables below. The image
already sets `ENVIRONMENT=production` and `STATIC_DIR`.

| Variable | Needed | Notes |
|---|---|---|
| `LLM_API_KEY`, `LLM_PROVIDER`, `LLM_MODEL` | yes | Plus `LLM_BASE_URL` for OpenAI-compatible providers |
| `DATABASE_URL` | yes | Postgres. The provider's URL works as given, `sslmode` included |
| `RATE_LIMIT_*`, `MAX_CONCURRENT_DEBATES` | tune | Per-IP hourly limits, and the cap on debates running at once |
| `FORWARDED_ALLOW_IPS` | maybe | Image default `*` suits a platform proxy; on a bare VPS set your proxy's IP |

Before going live:

- **Run exactly one instance with one worker.** Running debates live in the
  process's memory, so a second replica would answer stream requests for
  debates it is not running.
- **Serve over HTTPS.** Production cookies are `Secure`, and HSTS is sent.
- **Put a spending cap on the provider key.** The per-IP limits slow abuse, but
  cannot stop someone rotating addresses; the provider's budget cap is the
  backstop.
- **SQLite is for demos only.** Most platforms wipe a container's disk on
  every deploy.

---

## Design

The visual direction is a live debate broadcast: two podiums, a real vertical
aisle between them, a verdict at the end. `design.md` is the authority; Tailwind
is a utility layer, not the design system.

Two rules carry most of the identity:

- `--for` (amber `#E8A33D`) and `--against` (indigo `#6C6FE0`) bind to the
  **debate position, never to a person.** The same friend is amber in one debate
  and indigo in the next.
- There is no success green. A win is shown by filling the winner's own position
  color and fading the loser to `--text-muted`. `--alert` (`#E4726A`) is
  reserved for genuine errors, so error states never borrow the position colors.

Type is two families only — Big Shoulders Display for persona names, round
numbers and the verdict; IBM Plex Sans for everything else. The entire motion
budget is spent on the debate → verdict transition. Mobile collapses to a single
column with the aisle as a horizontal divider, and `prefers-reduced-motion` is
respected.

---

## Engineering rules

These are enforced in review and, where possible, in tests:

- Route handlers stay thin; business logic lives in `services/`.
- **Every prompt lives in `app/llm/prompts.py`** — one builder per purpose, no
  prompt strings anywhere else.
- API keys never reach the frontend, a URL, or a log. Credentials travel in
  headers, and every user-facing error string passes through
  `app.llm.errors.redact` first.
- Transport failures are not output failures. A 429 or 5xx means "ask again
  later" and is never escalated through the structured-output retry chain — that
  only spends more requests against the limit that just refused.
- Structured output discipline: ask for typed Pydantic output; on failure retry
  once, then fall back to a lenient parser, then mark the turn failed. Never
  continue silently with invalid data.
- Safety copy is visible on the persona and debate screens, not buried in a
  footer.

---

## Scope

The MVP is exactly: two friends → persona compiler with user review → one debate
of four fixed rounds → live SSE streaming → independent blind judge →
persistence of all of it — plus, at the user's request, past debates and saved
personas, per-browser privacy, and the seeded public figures.

Deliberately **not** built yet, and not scaffolded either — no placeholder
routes, no disabled UI:

- Live replay of a finished debate
- Persona-consistency evaluator and its dashboard
- Three-participant debates, topic categories, configurable rounds/temperature
  in the UI
- Observability logging, prompt versioning
- Research/experiment mode and batch benchmarking
- Accounts and sign-in (privacy is per browser for now)

See "Later" in `PRD.md`.
