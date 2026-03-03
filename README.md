# text-game-webui

Web UI for `text-game-engine`, designed for local or remote deployment.

## Stack
- FastAPI + Jinja2 + WebSocket
- HTMX + Alpine.js
- pytest (backend), Jest (frontend flow tests)

## Run (local)
```bash
git clone https://github.com/bghira/text-game-webui
cd text-game-webui
uv venv
source .venv/bin/activate
uv pip install -e .[dev]
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

## Frontend tests (Jest)
```bash
cd tests/frontend
npm install
npm test
```

## Docs
- Architecture: `docs/architecture.md`
- Feature matrix: `docs/feature-matrix.md`
- Testing policy: `docs/testing.md`
- Generated docs policy: `docs/generated/README.md`
