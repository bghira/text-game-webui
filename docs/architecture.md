# Architecture

## Goal
Expose `text-game-engine` features through a local/remote web UI without duplicating engine logic.

## Runtime Layers
1. UI layer (`app/ui`, `app/templates`, `app/static`)
2. API layer (`app/api/routes.py`, `app/api/ws.py`)
3. Adapter layer (`app/services/engine_gateway.py`, `app/services/gateway_factory.py`)
4. Realtime fanout (`app/realtime/hub.py`)

## Backend Modes
- `inmemory`: local scaffold backend for UI/API development.
- `tge`: `text-game-engine` backend using `ZorkEmulator` + SQLAlchemy persistence.
  - `TEXT_GAME_WEBUI_TGE_COMPLETION_MODE=deterministic`: local deterministic turn resolver.
  - `TEXT_GAME_WEBUI_TGE_COMPLETION_MODE=openai`: OpenAI-compatible `/chat/completions` + tool-call loop.
  - runtime checks via `GET /api/runtime/checks` include DB connectivity and optional LLM probe (`TEXT_GAME_WEBUI_TGE_RUNTIME_PROBE_LLM`), with request-level override using `probe_llm=true`.

Mode is selected by `TEXT_GAME_WEBUI_GATEWAY_BACKEND`.

## Boundaries
- UI/API handlers call gateway methods only.
- Persistence/model logic belongs in `text-game-engine` for `tge` mode.
- Realtime events are publish/fanout; no game logic in websocket handlers.

## Request/Update Flow
1. Browser submits turn to `POST /api/campaigns/{id}/turns`.
2. API calls selected gateway `submit_turn`.
3. API publishes turn payload to websocket hub.
4. Browser receives websocket event and updates stream.
5. Browser refreshes map/calendar/roster/player-state/media/debug surfaces via API.
