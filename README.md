# text-game-webui

Web UI shell for `text-game-engine`.

## Current status
- FastAPI app with server-rendered UI (`Jinja2` + `HTMX` + `Alpine`).
- Adapter-driven backend surface.
- Runtime-selectable gateway backend:
  - `inmemory` (default)
  - `tge` (uses local `text-game-engine` installation + SQLite)
- Realtime campaign stream via websocket (`/ws/campaigns/{campaign_id}`).
- Inspector surfaces for sessions/map/timers/calendar/roster (including upsert/remove actions)/player state+inventory/media status+avatar actions/memory/SMS/debug snapshot.
- Runtime checks endpoint for gateway/database/LLM probe status (`GET /api/runtime/checks`).
  - Supports explicit probe override: `GET /api/runtime/checks?probe_llm=true`.

## Local run
```bash
git clone https://github.com/bghira/text-game-webui
cd text-game-webui
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

## Use text-game-engine backend
Install `text-game-engine` into the same environment and set backend env vars:

```bash
pip install -e ../text-game-engine
export TEXT_GAME_WEBUI_GATEWAY_BACKEND=tge
export TEXT_GAME_WEBUI_TGE_DATABASE_URL='sqlite+pysqlite:///./text-game-webui.db'
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

Optional: use an OpenAI-compatible model endpoint for full model-driven turns/tool calls:

```bash
export TEXT_GAME_WEBUI_TGE_COMPLETION_MODE=openai
export TEXT_GAME_WEBUI_TGE_LLM_BASE_URL='http://127.0.0.1:1234/v1'
export TEXT_GAME_WEBUI_TGE_LLM_API_KEY='sk-local'
export TEXT_GAME_WEBUI_TGE_LLM_MODEL='your-model-id'
# optional runtime LLM probe in /api/runtime/checks
export TEXT_GAME_WEBUI_TGE_RUNTIME_PROBE_LLM=1
export TEXT_GAME_WEBUI_TGE_RUNTIME_PROBE_TIMEOUT_SECONDS=8

# one-off manual probe
curl 'http://127.0.0.1:8080/api/runtime/checks?probe_llm=true'
```

## Test
```bash
source .venv/bin/activate
pytest
```

```bash
cd tests/frontend
npm install
npm test
```

## Docs
- `AGENTS.md`: contributor/agent contract
- `docs/architecture.md`: runtime architecture and boundaries
- `docs/feature-matrix.md`: feature-to-surface mapping
- `docs/testing.md`: backend + Jest flow testing requirements
- `docs/generated/README.md`: generated-doc policy
