from __future__ import annotations

import asyncio
import importlib.util

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.gateway_factory import build_gateway
from app.services.schemas import TurnRequest
from app.settings import Settings


@pytest.mark.skipif(importlib.util.find_spec("text_game_engine") is None, reason="text_game_engine not installed")
def test_tge_gateway_smoke(tmp_path):
    db_path = tmp_path / "tge-webui.db"
    settings = Settings(
        gateway_backend="tge",
        tge_database_url=f"sqlite+pysqlite:///{db_path}",
    )
    gateway, backend = build_gateway(settings)
    assert backend == "tge"

    async def run_flow() -> None:
        campaign = await gateway.create_campaign("default", "main", "actor-1")
        assert campaign.id

        result = await gateway.submit_turn(campaign.id, TurnRequest(actor_id="actor-1", action="look"))
        assert result.narration

        cal = await gateway.get_calendar(campaign.id)
        assert "game_time" in cal

        roster = await gateway.get_roster(campaign.id)
        assert "characters" in roster

        player_state = await gateway.get_player_state(campaign.id, "actor-1")
        assert player_state["actor_id"] == "actor-1"

        media = await gateway.get_media(campaign.id, "actor-1")
        assert "scene" in media
        assert "avatars" in media

        sms = await gateway.sms_write(campaign.id, "saul", "actor-1", "saul", "test")
        assert sms["stored"] is True

    asyncio.run(run_flow())


@pytest.mark.skipif(importlib.util.find_spec("text_game_engine") is None, reason="text_game_engine not installed")
def test_runtime_reports_tge_mode(monkeypatch, tmp_path):
    db_path = tmp_path / "runtime-tge.db"
    monkeypatch.setenv("TEXT_GAME_WEBUI_GATEWAY_BACKEND", "tge")
    monkeypatch.setenv("TEXT_GAME_WEBUI_TGE_DATABASE_URL", f"sqlite+pysqlite:///{db_path}")
    monkeypatch.setenv("TEXT_GAME_WEBUI_TGE_COMPLETION_MODE", "deterministic")

    app = create_app()
    client = TestClient(app)
    res = client.get("/api/runtime")
    assert res.status_code == 200
    body = res.json()
    assert body["gateway_backend"] == "tge"
    assert body["tge_completion_mode"] == "deterministic"

    checks = client.get("/api/runtime/checks")
    assert checks.status_code == 200
    checks_json = checks.json()
    checks_body = checks_json["checks"]
    assert checks_json["probe_llm"] is False
    assert checks_body["backend"] == "tge"
    assert checks_body["database"]["ok"] is True
    assert checks_body["llm"]["configured"] is False
