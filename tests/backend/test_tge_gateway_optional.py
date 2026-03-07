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

        session_row = await gateway.create_or_update_session(
            campaign.id,
            surface="discord_thread",
            surface_key="discord:guild-1:thread-11",
            surface_guild_id="guild-1",
            surface_channel_id="channel-9",
            surface_thread_id="thread-11",
            enabled=True,
            metadata={"active_campaign_id": campaign.id},
        )
        assert session_row["surface_key"] == "discord:guild-1:thread-11"
        listed_sessions = await gateway.list_sessions(campaign.id)
        assert listed_sessions
        patched = await gateway.update_session(campaign.id, session_row["id"], enabled=False, metadata={"note": "off"})
        assert patched["enabled"] is False

        private_session = await gateway.create_or_update_session(
            campaign.id,
            surface="web_private",
            surface_key=f"webui:{campaign.id}:private:actor-1",
            enabled=True,
            metadata={
                "label": "Private room: actor-1",
                "scope": "private",
                "turn_visibility_default": "private",
                "owner_actor_id": "actor-1",
                "allowed_actor_ids": ["actor-1"],
            },
        )
        assert private_session["surface"] == "web_private"

        result = await gateway.submit_turn(campaign.id, TurnRequest(actor_id="actor-1", action="look"))
        assert result.narration
        private_result = await gateway.submit_turn(
            campaign.id,
            TurnRequest(actor_id="actor-1", action="whisper to Monet", session_id=private_session["id"]),
        )
        assert private_result.session_id == private_session["id"]
        assert private_result.turn_visibility["scope"] == "private"

        timers = await gateway.get_timers(campaign.id)
        assert "timers" in timers

        cal = await gateway.get_calendar(campaign.id)
        assert "game_time" in cal

        roster = await gateway.get_roster(campaign.id)
        assert "characters" in roster
        upserted = await gateway.upsert_roster_character(
            campaign.id,
            slug="arsipea-denton",
            name="Arsipea Denton",
            location="visitor-room-b",
            status="active",
            player=False,
            fields={"appearance": "gray jumpsuit"},
        )
        assert upserted["ok"] is True
        removed = await gateway.remove_roster_character(campaign.id, "arsipea-denton", player=False)
        assert removed["removed"] is True

        player_state = await gateway.get_player_state(campaign.id, "actor-1")
        assert player_state["actor_id"] == "actor-1"

        media = await gateway.get_media(campaign.id, "actor-1")
        assert "scene" in media
        assert "avatars" in media

        accept = await gateway.accept_pending_avatar(campaign.id, "actor-1")
        assert "ok" in accept
        decline = await gateway.decline_pending_avatar(campaign.id, "actor-1")
        assert "ok" in decline

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


@pytest.mark.skipif(importlib.util.find_spec("text_game_engine") is None, reason="text_game_engine not installed")
def test_runtime_reports_ollama_mode(monkeypatch, tmp_path):
    db_path = tmp_path / "runtime-tge-ollama.db"
    monkeypatch.setenv("TEXT_GAME_WEBUI_GATEWAY_BACKEND", "tge")
    monkeypatch.setenv("TEXT_GAME_WEBUI_TGE_DATABASE_URL", f"sqlite+pysqlite:///{db_path}")
    monkeypatch.setenv("TEXT_GAME_WEBUI_TGE_COMPLETION_MODE", "ollama")
    monkeypatch.setenv("TEXT_GAME_WEBUI_TGE_LLM_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setenv("TEXT_GAME_WEBUI_TGE_LLM_MODEL", "llama3.1")
    monkeypatch.setenv("TEXT_GAME_WEBUI_TGE_OLLAMA_KEEP_ALIVE", "45m")

    app = create_app()
    client = TestClient(app)
    res = client.get("/api/runtime")
    assert res.status_code == 200
    body = res.json()
    assert body["gateway_backend"] == "tge"
    assert body["tge_completion_mode"] == "ollama"
    assert body["tge_llm_base_url"] == "http://127.0.0.1:11434"
    assert body["tge_llm_model"] == "llama3.1"
    assert body["tge_ollama_keep_alive"] == "45m"

    checks = client.get("/api/runtime/checks")
    assert checks.status_code == 200
    checks_json = checks.json()
    checks_body = checks_json["checks"]
    assert checks_json["probe_llm"] is False
    assert checks_body["backend"] == "tge"
    assert checks_body["completion_mode"] == "ollama"
    assert checks_body["database"]["ok"] is True
    assert checks_body["llm"]["configured"] is True
    assert checks_body["llm"]["probe_attempted"] is False
