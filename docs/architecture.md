# Architecture

## Layers
1. `app/ui` renders pages and HTMX partials.
2. `app/api` exposes JSON and websocket surfaces.
3. `app/services/engine_gateway.py` adapts to `text-game-engine`.
4. `app/realtime` fans out async state changes.

## Rule
UI/API must call gateway methods only. No direct persistence coupling.
