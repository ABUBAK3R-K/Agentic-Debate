# CLAUDE.md — PersonaArena

Guidance for Claude Code working in this repository.

## What this is

PersonaArena — "Same model. Different minds." A user describes two friends'
personalities; the system compiles each into a structured persona, runs a
same-model AI debate between them across four fixed rounds, and an independent
AI judge scores the exchange.

## Source of truth

Read these in full before changing code. They outrank anything remembered from
a previous pass of this project:

- `PRD.md` — behavior, data model, API, model constraints. **Scope authority.**
- `design.md` — visual identity, layout, color/type system, anti-patterns.
  **Design authority.** Tailwind is a utility layer, not the design system.
- `instruction.md` — the working process for the current restructure.

`PRD.md` and `design.md` were both replaced for v2. v1 was built from a much
larger PRD; anything in the code that only made sense under the old PRD is
out of scope now, not a feature to finish.

## Scope discipline (the point of this revision)

MVP is exactly: two friends → persona compiler (with user review/edit) → one
debate with four fixed rounds → live SSE streaming → independent blind judge →
persistence of the above.

Deferred to v2 (see "Later" in `PRD.md`): debate history/replay, persona-
consistency evaluator + dashboard, 3-participant debates, topic categories,
configurable rounds/temperature in the UI, observability logging, prompt
versioning, research/experiment mode, authentication.

**Do not scaffold pages, routes, disabled UI, or placeholder endpoints for
anything deferred.** If it isn't in the MVP list, it doesn't exist in this
codebase yet. Confirm with the user before building anything from "Later".

## Architecture

```
backend/app/
  api/         FastAPI routers — thin. No business logic here.
  services/    DebateEngine, JudgeEngine, debate_runner, persona_compiler,
               friend_service.
  llm/         LLMProvider ABC, providers, prompts.py, structured.py.
  models/      SQLAlchemy ORM.
  schemas/     Pydantic request/response + structured LLM output.
  core/        config (env settings), database (async engine/session).
backend/tests/ pytest suite; fakes.py holds the scripted FakeLLM.
frontend/src/
  pages/       Setup, LiveDebate, Verdict. Exactly three.
  components/  SiteHeader, Aisle, PersonaSheet, SimulationNotice.
  services/    Axios API client.
  hooks/       useDebateStream — the SSE reducer.
  index.css    Design tokens and primitives.
  screens.css  Per-screen layout.
```

### How a debate actually runs

`POST /start` hands the debate to `debate_runner`, which runs the engine on
its own session in the background and publishes each event into a
`DebateBroadcast`. `GET /stream` subscribes to that buffer, so a client that
connects a moment late still receives the debate from its first event.

Each turn emits `turn_start`, then `token` events as the argument is written,
then exactly one of `message` (authoritative final text) or `turn_failed`.
Tokens are a live preview; `message` is the truth. A turn is streamed as JSON
and the argument field is extracted from the stream by
`JsonStringFieldExtractor`, so the screen gets live text and the backend still
gets validated structured output.

## Standing rules

- **Route handlers stay thin.** Business logic lives in `services/`.
- **All prompts live in `app/llm/prompts.py`.** One prompt builder per purpose,
  never duplicated. No prompt strings anywhere else in the codebase.
- **Identical model settings for every debate participant.** Model, temperature,
  top_p, max_tokens come from environment variables, are stored on the debate
  record, and are never hardcoded in the debate engine. The only difference
  between two agents is persona + assigned position + conversation context.
- **Never expose API keys to the frontend — or to a log.** All LLM calls are
  server-side, and credentials travel in headers, never in a URL. A key in a
  query string ends up in every provider error message, and those messages
  reach both the logs and the browser. Every user-facing error string passes
  through `app.llm.errors.redact` first.
- **Pace the provider.** One debate is nine requests back to back, which walks
  straight into a free tier's per-minute limit. `app/llm/transport.py` holds a
  process-wide minimum interval between requests plus retry-with-backoff that
  honours the provider's own `Retry-After` / `retryDelay`. Tune with
  `LLM_MIN_REQUEST_INTERVAL`.
- **Transport failures are not output failures.** A 429 or a 5xx means "ask
  again later" and must not be escalated through the structured-output chain —
  that just spends more requests against the limit that already refused. A
  turn that fails this way stops the debate rather than leaving every
  remaining round empty.
- **Structured output discipline.** Ask for typed Pydantic output. On failure:
  retry once → fall back to a lenient parser → mark the turn failed. Never
  silently continue with invalid data.
- **Async where it matters** — LLM calls and the SSE stream.
- **Backend owns the state machine.** LLMs generate content when asked; they
  never decide what happens next.
- **Judge is blind.** It sees `Participant A` / `Participant B` with the order
  randomized per debate; the backend maps results back to friend IDs after.
- **Safety copy is visible.** Persona creation and debate screens must say this
  is a fictional simulation of what the user wrote — never "X actually thinks".
- Run and fix tests after each step before starting the next.

## Debate state machine

```
CREATED → POSITIONING → OPENING → REBUTTAL → COUNTER → CLOSING → JUDGING → COMPLETED
```

Positions (FOR / AGAINST) are assigned by the backend, never chosen by agents.

## Design rules (non-negotiable for any screen)

- `--for` (`#E8A33D` amber) and `--against` (`#6C6FE0` indigo) bind to the
  **debate position, never to a person.** The same friend is amber in one
  debate and indigo in another.
- No success green. A win is shown by filling the winner's own position color
  and fading the loser to `--text-muted`.
- Two type families only: Big Shoulders Display (persona names, round numbers,
  verdict) and IBM Plex Sans (everything else). No third face, no monospace.
- The center aisle is a real vertical rule on every debate screen; each side's
  transcript grows in its own column. Not a merged chat thread.
- Motion budget is spent entirely on the debate → verdict transition.
- Argument text under ~70 characters per line.

### Anti-patterns — check every screen against this before calling it done

- Uniform rounded cards with the same soft drop-shadow on everything.
- ALL-CAPS eyebrow labels above headings.
- Monospace for small data labels.
- Meta strings joined with middle dots (`Rahul · Skeptical · Round 2`).
- Trailing arrows on buttons or links (`Start debate →`).
- Gradient washes used as decoration.
- Progress bars or percentage stats invented for visual interest.
- One fade-and-slide-up entrance animation repeated on every section.

The palette carries one addition to `design.md`: `--alert` (`#E4726A`) for
genuine error text. Amber and indigo mean FOR and AGAINST and nothing else, so
error states must not borrow them.

Also required: single-column mobile layout (aisle becomes a horizontal
divider), visible keyboard focus on every interactive element, respect
`prefers-reduced-motion`, and contrast-check `--text-muted` against both
`--stage` and `--panel`.

## Commands

```bash
# Backend (from backend/) — deps live in backend/.venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe -m pytest             # 115 tests, no network, no DB
.venv/Scripts/python.exe init_db.py            # create tables
.venv/Scripts/python.exe -m uvicorn app.main:app --reload

# Frontend (from frontend/)
npm install
npm run dev
npm run build
npm run lint                       # oxlint
```

Tests run against in-memory SQLite and `tests/fakes.FakeLLM`, so they never
touch Postgres or a provider. A `.env` at the repo root is needed to run for
real — copy `.env.example`.

## Environment

Config is read from `.env` at the repo root via `app/core/config.py`. See
`.env.example`. Never commit `.env`.

## Installed skills

`.claude/skills/` carries the skills from `github.com/emilkowalski/skills`.
The ones that apply here: `animate` (build motion), `review-animations`
(critique it), `emil-design-eng` (UI polish), `animation-vocabulary`, and
`find-animation-opportunities`. The verdict reveal was built against
`animate` — if you touch it, re-read that skill first, and remember the
product's entire motion budget is spent on that one transition.
