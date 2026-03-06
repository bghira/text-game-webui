# AGENTS.md - text-game-webui

Operating contract for agents and contributors working in this repository.

## Mission
- Build a local/remote web UI for `text-game-engine`.
- Expose the full engine feature set with a practical, maintainable interface.
- Keep docs and tests authoritative and synchronized with code.

## Primary Stack
- Backend: `FastAPI` + `Jinja2` + `WebSocket` endpoints.
- Frontend: server-rendered HTML + `HTMX` + `Alpine.js`.
- Styling: plain CSS (or Tailwind only if explicitly introduced later).
- Python tests: `pytest`.
- Frontend tests: `Jest` (required for flow coverage).

## Architecture Direction
- Keep a strict adapter layer between UI/API and `text-game-engine`.
- No direct DB coupling from UI handlers.
- Realtime events must use websocket push (timers, turn updates, media status).

## Target Repository Layout
- `app/main.py`: FastAPI app bootstrap.
- `app/api/`: JSON endpoints and websocket handlers.
- `app/ui/`: HTML route handlers and HTMX partial handlers.
- `app/services/`: engine gateway, orchestration, session logic.
- `app/realtime/`: websocket manager, subscriptions, fanout.
- `app/templates/`: Jinja templates and HTMX partials.
- `app/static/`: JS/CSS assets.
- `tests/backend/`: pytest tests.
- `tests/frontend/`: Jest tests.
- `tests/frontend/flows/`: required user-flow tests (Jest).
- `docs/`: canonical human-authored docs.
- `docs/generated/`: non-authoritative generated notes only.

## Feature Set (Must Be Supported)
- Campaign/session management.
- Turn submission and narration stream.
- Realtime updates (timers, async events, multi-user activity).
- Map rendering.
- Calendar and game-time visibility.
- Character roster visibility and updates.
- Memory tools: search/terms/turn/store.
- SMS tools: list/read/write.
- Inventory and player state display.
- Scene/avatar media job status and outputs.
- Debug/inspection surfaces for raw model/tool outputs.

## Documentation Policy
- Canonical docs live in `docs/` and are human-maintained.
- Internal LLM-generated docs are allowed only in `docs/generated/`.
- Any file in `docs/generated/` must include at top:
  - `Generated: true`
  - `Source of truth: <path(s)>`
  - `Last verified against code/tests: <date>`
- Never treat generated docs as authoritative for behavior.
- Do not store speculative design notes in root or beside source files.
- Source-material authoring rules for `!zork source-material` live in the sibling
  engine repo at `../text-game-engine/docs/source-material.md`. If web UI behavior
  or prompts depend on source-material formats, keep that document in sync.
- Model backend integration details for `tge` mode should stay aligned with the
  sibling engine repo backend surface. When updating completion modes such as
  native Ollama, keep `docs/backends.md` here and the engine repo backend docs in sync.

## Preventing Doc Drift
- Any behavior change must update:
  1. Code
  2. Relevant canonical doc in `docs/`
  3. Tests (backend and/or Jest flow)
- PRs/changes are incomplete if docs describe behavior not covered by tests.
- Prefer short docs with links to exact source/test files over long prose.

## Test Policy (Jest Flow Requirement)
- Every user-facing feature must have at least one Jest flow test in:
  - `tests/frontend/flows/*.test.ts`
- "Flow test" means multi-step behavior, not only component snapshots.
- Flow tests must assert visible outcomes and network interactions.
- If feature touches realtime behavior, include mocked websocket flow in Jest.
- Keep tests deterministic: no sleeping/timeouts without explicit clock control.

## Definition of Done
- Feature implemented through service adapter layer.
- Backend tests pass (`pytest`).
- Frontend/unit/flow tests pass (`jest`), including new or changed flows.
- Canonical docs updated in `docs/`.
- Any generated docs regenerated or explicitly marked stale.

## Non-Goals
- Duplicating engine business logic in the web UI.
- Unbounded internal design docs that drift from implementation.
- Merging features that bypass Jest flow coverage.
