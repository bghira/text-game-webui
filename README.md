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
- Image generation for scene images and character avatars via local Diffusers daemon or external ComfyUI server.
- Campaign creation with document upload (`.txt`/`.md` drag-and-drop), automatic source-material digest, and setup wizard auto-start.
- State restoration: selected campaign and session persist to `localStorage` and restore on refresh, with turn stream hydrated from history.
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

Optional: use native Ollama for full model-driven turns/tool calls:

```bash
export TEXT_GAME_WEBUI_TGE_COMPLETION_MODE=ollama
export TEXT_GAME_WEBUI_TGE_LLM_BASE_URL='http://127.0.0.1:11434'
export TEXT_GAME_WEBUI_TGE_LLM_MODEL='qwen2.5:14b'
export TEXT_GAME_WEBUI_TGE_OLLAMA_KEEP_ALIVE='30m'
export TEXT_GAME_WEBUI_TGE_OLLAMA_OPTIONS_JSON='{"num_ctx":32768}'
# optional runtime LLM probe in /api/runtime/checks
export TEXT_GAME_WEBUI_TGE_RUNTIME_PROBE_LLM=1
export TEXT_GAME_WEBUI_TGE_RUNTIME_PROBE_TIMEOUT_SECONDS=8

# one-off manual probe
curl 'http://127.0.0.1:8080/api/runtime/checks?probe_llm=true'
```

The runtime panel will show `Mode: ollama`, the active model, base URL, and configured keep-alive value.

## Image generation

Scene images and character avatars can be generated locally via a Diffusers daemon or an external ComfyUI server. Set the image backend and configure the relevant provider:

### Diffusers (local GPU)

```bash
export TEXT_GAME_WEBUI_IMAGE_BACKEND=diffusers
export TEXT_GAME_WEBUI_DIFFUSERS_MODEL='black-forest-labs/FLUX.2-klein-4b'
export TEXT_GAME_WEBUI_DIFFUSERS_DEVICE=cuda      # cuda | mps | cpu
export TEXT_GAME_WEBUI_DIFFUSERS_DTYPE=bf16        # f16 | bf16 | f32
export TEXT_GAME_WEBUI_DIFFUSERS_AUTOSTART=1       # start daemon on boot
# optional tuning
export TEXT_GAME_WEBUI_DIFFUSERS_OFFLOAD=none      # none | model | sequential
export TEXT_GAME_WEBUI_DIFFUSERS_QUANTIZATION=none # none | int8 | int4
export TEXT_GAME_WEBUI_DIFFUSERS_VAE_TILING=1
```

The diffusers daemon runs as a subprocess on `127.0.0.1:8189` by default. Override with `TEXT_GAME_WEBUI_DIFFUSERS_HOST` / `TEXT_GAME_WEBUI_DIFFUSERS_PORT`.

### ComfyUI (external server)

```bash
export TEXT_GAME_WEBUI_IMAGE_BACKEND=comfyui
export TEXT_GAME_WEBUI_COMFYUI_URL='http://127.0.0.1:8188'
# optional: custom workflow template
export TEXT_GAME_WEBUI_COMFYUI_WORKFLOW_JSON='path/to/workflow.json'
```

### Generation defaults

These apply to both backends and can also be changed at runtime via `POST /api/settings/image`:

```bash
export TEXT_GAME_WEBUI_IMAGE_WIDTH=1024
export TEXT_GAME_WEBUI_IMAGE_HEIGHT=1024
export TEXT_GAME_WEBUI_IMAGE_STEPS=20
export TEXT_GAME_WEBUI_IMAGE_GUIDANCE_SCALE=3.5
export TEXT_GAME_WEBUI_IMAGE_CACHE_MAX_ENTRIES=50
```

When an image backend is active, the engine generates scene images during gameplay and avatar proposals during character creation. Avatars appear in the Player tab with accept/decline controls. Scene images appear in the Campaign tab. Character portraits can be set manually from the Roster tab.

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
- `docs/backends.md`: local model backend configuration for `tge` mode
- `docs/feature-matrix.md`: feature-to-surface mapping
- `docs/testing.md`: backend + Jest flow testing requirements
- `docs/generated/README.md`: generated-doc policy
