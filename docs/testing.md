# Testing

## Backend
- Command: `pytest`
- Scope:
  - API contract behavior
  - gateway-backed tool surfaces
  - websocket publish behavior (`tests/backend/test_campaign_api.py`)
  - deterministic realtime publish contract assertions (`tests/backend/test_realtime_publish.py`)
  - 404 handling for missing campaigns
  - gateway backend factory behavior

Optional test:
- `tests/backend/test_tge_gateway_optional.py` runs only when `text_game_engine` is installed.
- Diagnostics endpoint coverage:
  - `GET /api/diagnostics/bundle`
  - `GET /api/runtime/checks` (including `probe_llm=true` override path)
  - with and without `campaign_id`
- In `tge` + `openai` mode, run a manual integration check against your model endpoint:
  - create campaign
  - submit turn
  - verify tool-call turns (memory/sms) resolve into final narration JSON
  - if using runtime probes, set `TEXT_GAME_WEBUI_TGE_RUNTIME_PROBE_LLM=1` and verify `GET /api/runtime/checks` reports `llm.probe_attempted=true`

## Frontend
- Command: `cd tests/frontend && npm test`
- Scope:
  - flow helper behavior
  - session management network sequence (create/list/patch/list)
  - roster management network sequence (upsert/remove + refresh)
  - memory tool network sequence (search/terms/turn/store)
  - sms tool network sequence (list/read/write)
  - media avatar action sequence (accept/decline + refresh)
  - multi-step turn flow network sequence
  - timers refresh in post-turn flow
  - player-state refresh in post-turn flow
  - media-status refresh in post-turn flow
  - runtime diagnostics and diagnostics bundle payload shape

## Required Change Discipline
For any user-facing behavior change:
1. Update code.
2. Update canonical docs in `docs/`.
3. Update or add backend/Jest flow tests.
