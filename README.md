# text-game-webui

Web UI shell for [bghira/text-game-engine](https://github.com/bghira/text-game-engine)

<img width="440" alt="image" src="https://github.com/user-attachments/assets/35358b9d-b064-4322-bd03-2e380b8499d0" />


## Features

### Campaign & session management
- Create campaigns with document upload (`.txt`/`.md` drag-and-drop), automatic source-material digest, and guided setup wizard.
  - Upload a TV show script, movie screenplay, or novel to create an interactive game from it.
- Multiple sessions per campaign: main session plus private windows (solo, with actor, with NPC).
- State restoration: selected campaign and session persist to `localStorage` and restore on refresh, with turn stream hydrated from history.
- Multiplayer capable, but no security / auth.

### Turn stream
- Real-time streaming narration with live token-by-token display.
- Turn types: narrator, player, notice, summary, reasoning, image prompt, dice results.
- Turn management: pin/unpin, rewind, edit in-place, delete, copy to clipboard, collapse/expand.
- Full-text turn search with jump-to-result (side rail on desktop, magnifying glass icon on mobile).
- Pinned turns overlay accessible from the topbar.
- Game time display (in-game day/hour/minute) on narrator turns.

### Character & player state
- Character sheet: avatar, name (editable), level, XP bar, attributes with point allocation, inventory list.
- Level-up system with XP threshold tracking.
- Avatar generation: accept/decline proposals during character creation, generate from custom prompt, or set portrait by URL.
- Actor selector for players controlling multiple characters.
- `@mention` autocomplete for addressing NPCs and other actors in the action input.
- Quick-info sidebar widget: avatar thumbnail, name, level/XP, current room, and quick-action buttons.

### World state
- **Map**: Room graph with connections, rendered in the inspector.
- **Calendar**: Upcoming events with title, time, location, and description. Public/private visibility toggle and delete controls.
- **Chapters**: Story progression with current chapter highlight, status indicators, scene list, and summary.
- **Game clock**: In-game time widget in the sidebar, updated in real time via WebSocket.

### Narrator & AI controls
- Multiple LLM backends: Claude Code, Codex, OpenAI-compatible API, native Ollama.
- LLM settings: completion mode, base URL, API key, model, temperature, max tokens, timeout, keep-alive, Ollama options.
- Campaign flags: guardrails, on-rails story mode, timed events, difficulty (story through impossible), speed multiplier, clock type.
- Narrator persona: customizable voice description (max 140 chars).
- Timed events with a sidebar "fires in/at" indicator, cancel control, and real-time WebSocket push.

### Image generation
- Scene images and character avatars via local Diffusers daemon or external ComfyUI server.
- Generate/re-generate buttons on image prompt turns. Inline display below prompt.
- Avatar accept/decline during character creation. Manual portrait setting from Roster tab.
- Configurable resolution, steps, guidance scale, and cache size. Settings adjustable at runtime.

### Text-to-speech
- In-browser TTS toggle in the action bar.
- Engines: Kokoro (local WebGPU, 21+ voices) and Chatterbox (with reference audio for voice cloning).
- Per-NPC voice assignment via roster.
- Configurable sentence splitting, pause timings, and emotive marker handling; turn-stream display strips legacy `<sigh>`-style tags and `[emotive:...]` markers while preserving them for supported TTS paths.

### Tools & mechanics
- **SMS**: Inbox with threaded conversations. Read, write, reply, edit, delete, and schedule messages.
- **Memory**: Full-text search with category filter, key terms lookup, turn recall, and manual store.
- **Roster**: NPC/character list with add/remove, field editing, and portrait management.
- **Puzzles**: Active puzzle display with answer submission and hint system.
- **Minigames**: Board state display with move submission (e.g. chess, card games).
- **Dice**: Roll results displayed as color-coded success/fail cards in the turn stream.

### Source material & world building
- Upload source material with format tagging (story/prose, rulebook, generic/notes, auto-detect).
- Full-text search across uploaded documents.
- Source material digest: automatic summarization for better context reuse.
- Campaign rules: key-value store for persistent game rules.
- Literary styles: narrator voice profile gallery.

### Real-time & multiplayer
- Persistent WebSocket connection with auto-reconnect.
- Event types: turn refresh, DM/channel notifications, song notifications, timer expiry, pending mentions, shared session turns, media job updates.
- Discord account linking (DTM mode) with bot command flow and session cookie.

### Song player
- YouTube song queue parsed from in-game channel messages.
- Embedded playback with previous/next controls and queue position counter.

### Debug & inspection
- Debug mode toggle in the topbar (persisted to `localStorage`).
- Inspector panel with tabs: Map, Player, Campaign, History, Story, Sessions, Timers, Calendar, Roster, Media, Memory, SMS, Debug.
- Raw model output, reasoning traces, and tool call inspection.

### Settings & theming
- Settings panel with LLM, image generation, and TTS configuration.
- Theme system: built-in light/dark themes plus custom CSS upload.
- All settings persisted to the database and restored on reload.

### Runtime status
- Sidebar health panel: gateway, database, and LLM probe status with green/red indicators.
- GPU stats (when available): name, utilization, VRAM, temperature, loaded Ollama models.
- Runtime checks endpoint: `GET /api/runtime/checks` with optional `?probe_llm=true`.

### Mobile
- Responsive layout: sidebar becomes an overlay drawer, turn stream goes edge-to-edge.
- Compact topbar with magnifying glass search icon.
- Sticky action bar with virtual keyboard awareness.

## Local run
```bash
git clone https://github.com/bghira/text-game-webui
git clone https://github.com/bghira/text-game-engine
cd text-game-webui
python -m venv .venv
source .venv/bin/activate
pip install -e '../text-game-engine[cuda,image]' # or rocm/apple instead of cuda for AMD/Apple
pip install -e '.[dev]'
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```
<details>
<summary>
  To configure via backend env vars
</summary>

```bash
pip install -e ../text-game-engine
export TEXT_GAME_WEBUI_GATEWAY_BACKEND=tge
export TEXT_GAME_WEBUI_TGE_DATABASE_URL='sqlite+pysqlite:///./text-game-webui.db'
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```
</details>

<details>
<summary>
Optional: use an OpenAI-compatible model endpoint for full model-driven turns/tool calls:
</summary>

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
</details>

<details>
<summary>
Optional: use native Ollama for full model-driven turns/tool calls:
</summary>

```bash
export TEXT_GAME_WEBUI_TGE_COMPLETION_MODE=ollama
export TEXT_GAME_WEBUI_TGE_LLM_BASE_URL='http://127.0.0.1:11434'
export TEXT_GAME_WEBUI_TGE_LLM_MODEL='qwen2.5:14b'
export TEXT_GAME_WEBUI_TGE_OLLAMA_KEEP_ALIVE='30m'
export TEXT_GAME_WEBUI_TGE_OLLAMA_OPTIONS_JSON='{"num_ctx":32768}'
export TEXT_GAME_WEBUI_TGE_THINKING_ENABLED=1  # set 0 to disable native Ollama thinking
# optional runtime LLM probe in /api/runtime/checks
export TEXT_GAME_WEBUI_TGE_RUNTIME_PROBE_LLM=1
export TEXT_GAME_WEBUI_TGE_RUNTIME_PROBE_TIMEOUT_SECONDS=8

# one-off manual probe
curl 'http://127.0.0.1:8080/api/runtime/checks?probe_llm=true'
```
</details>

The runtime panel will show `Mode: ollama`, the active model, base URL, and configured keep-alive value.

## Image generation

Scene images and character avatars can be generated locally via a Diffusers daemon, an external ComfyUI server, or a discord-tron-master GPU worker pool. Set the image backend and configure the relevant provider:

### DTM bridge

When `text-game-webui` is launched by discord-tron-master, DTM sets these automatically:

```bash
export TEXT_GAME_WEBUI_IMAGE_BACKEND=dtm
export TEXT_GAME_WEBUI_DTM_IMAGE_API_URL='http://127.0.0.1:5099'
export TEXT_GAME_WEBUI_DTM_LINK_SECRET='...'
```

The web UI posts image jobs to DTM's bot-process `/api/zork/image/generate` bridge and receives completed images through `/api/internal/campaigns/{id}/media/deliver`.
Scene prompt generation can run while a text turn is in progress. Use the palette toggle beside the turn composer, or the matching Image settings toggle, to auto-generate newly incoming scene image prompts.

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

When an image backend is active, the engine generates scene image prompts during gameplay and avatar proposals during character creation. Scene image prompt cards can be generated manually or auto-generated for newly incoming prompts when the browser-local toggle is enabled. Avatars appear in the Player tab with accept/decline controls. Scene images appear in the Campaign tab. Character portraits can be set manually from the Roster tab.

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
