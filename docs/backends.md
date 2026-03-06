# Backends

`text-game-webui` supports three `tge` completion paths:

- `deterministic`: no model endpoint, local fallback behavior only
- `openai`: OpenAI-compatible `/chat/completions`
- `ollama`: native Ollama backend through `text-game-engine`

## Ollama

Use Ollama when you want local model-driven setup, tool loops, attachment summarization, and map generation without the OpenAI compatibility layer.

Environment:

```bash
export TEXT_GAME_WEBUI_GATEWAY_BACKEND=tge
export TEXT_GAME_WEBUI_TGE_DATABASE_URL='sqlite+pysqlite:///./text-game-webui.db'
export TEXT_GAME_WEBUI_TGE_COMPLETION_MODE=ollama
export TEXT_GAME_WEBUI_TGE_LLM_BASE_URL='http://127.0.0.1:11434'
export TEXT_GAME_WEBUI_TGE_LLM_MODEL='qwen2.5:14b'
export TEXT_GAME_WEBUI_TGE_OLLAMA_KEEP_ALIVE='30m'
export TEXT_GAME_WEBUI_TGE_OLLAMA_OPTIONS_JSON='{"num_ctx":32768}'
```

Notes:

- `TEXT_GAME_WEBUI_TGE_LLM_BASE_URL` should point at the Ollama root URL, not `/v1`.
- `TEXT_GAME_WEBUI_TGE_OLLAMA_OPTIONS_JSON` must decode to a JSON object.
- Runtime probe uses the same native Ollama completion path as gameplay setup/tool calls.

## OpenAI-Compatible

Use `openai` mode for LM Studio, vLLM OpenAI server mode, OpenWebUI-compatible proxies, or hosted endpoints exposing `/chat/completions`.

## Scope

For `tge` mode, the web UI uses:

- a completion port for emulator-side generation tasks
- a tool-aware turn loop for model-driven turns

Both now work in `openai` and `ollama` modes.
