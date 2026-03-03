from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture()
def client(monkeypatch) -> TestClient:
    monkeypatch.setenv("TEXT_GAME_WEBUI_GATEWAY_BACKEND", "inmemory")
    app = create_app()
    return TestClient(app)
