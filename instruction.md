# Instructions for Claude Code — PersonaArena restructure

You're picking up an existing project, not starting fresh. `PRD.md` and `design.md` in this repo (both just replaced) are now the source of truth — read both in full before touching any code.

## Context

v1 of this project was built from an earlier PRD that tried to cover the entire vision in one pass (full debate engine, judge, persona-consistency scoring, streaming, results dashboard, history, observability, prompt versioning, and a research/experiment mode, all at once). The result worked but felt generic — broad and shallow rather than a few things done with care. This restructure has two changes: a much smaller MVP scope, and an actual design system (`design.md`) where before there was none.

## Step 1 — Audit before you touch anything

Inspect the current `backend/` and `frontend/` code and write a short audit (in your response, not a new file) covering:

- What already matches the new `PRD.md` closely enough to keep (the debate state machine and persona schema were solid in v1 — they probably still are).
- What's now out of scope per the new MVP list in `PRD.md` and should be removed or left disabled rather than finished.
- What in the current frontend needs a full visual rebuild against `design.md` (this is probably most of it, since v1 had no design spec to follow).

Show this audit and wait for confirmation before making large changes. Small, obviously-safe fixes don't need to wait.

## Step 2 — Build in this order, and stop expanding scope

1. Confirm the backend debate engine + persona compiler match the trimmed schema in `PRD.md`. Fix drift, don't rewrite what already matches.
2. Rebuild the frontend for exactly three screens: persona creation/review, live debate, verdict. Follow `design.md` precisely — the color-to-position binding, the two-family type system, the center-aisle layout, and the anti-patterns list are not optional.
3. Wire SSE streaming end to end for the live debate screen.
4. Only after those three screens genuinely match `design.md`, revisit anything from the "Later" list in `PRD.md` — and confirm first.

Do not scaffold pages, routes, or disabled UI for anything in the "Later" list. If it's not in the MVP scope, it doesn't exist in this codebase yet.

## Standing rules (carried over from before, still apply)

- Keep business logic out of route handlers; keep LLM prompts in one dedicated prompt module, never duplicated.
- Every debate participant uses identical model/temperature/top_p/max_tokens, sourced from environment variables — never hardcoded.
- Never expose API keys to the frontend.
- Use typed Pydantic schemas for structured LLM output; if structured output fails, retry once, then fall back to a parser, then mark the turn failed — never silently continue with invalid data.
- Use async APIs where it matters (the LLM calls and the SSE stream).
- Run and fix tests after each step before moving to the next.

## Before you consider a screen done

Check it against the anti-patterns list in `design.md` explicitly — uniform card shadows, ALL-CAPS eyebrows, decorative gradients, trailing arrows on buttons, invented stats. If you're unsure whether something reads as generic, ask.
