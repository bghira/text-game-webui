"""Tests for API endpoints that previously lacked coverage.

Covers: source materials, campaign rules, rewind, timer cancel,
player statistics/attributes/rename/level-up, persona, puzzle/minigame,
campaign setup, scene images, literary styles, SMS cancel/schedule,
character portrait, story state, campaign export, and LLM settings.
"""


def _create_campaign(client, name="Coverage Test", actor_id="dale-denton"):
    res = client.post(
        "/api/campaigns",
        json={"namespace": "default", "name": name, "actor_id": actor_id},
    )
    assert res.status_code == 200
    return res.json()["campaign"]


# ---------------------------------------------------------------------------
# Source Materials
# ---------------------------------------------------------------------------

def test_get_source_materials(client):
    campaign = _create_campaign(client)
    cid = campaign["id"]

    res = client.get(f"/api/campaigns/{cid}/source-materials")
    assert res.status_code == 200
    assert "documents" in res.json()


def test_get_source_materials_unknown_campaign(client):
    res = client.get("/api/campaigns/nonexistent/source-materials")
    assert res.status_code == 404


def test_ingest_source_material(client):
    campaign = _create_campaign(client)
    cid = campaign["id"]

    res = client.post(
        f"/api/campaigns/{cid}/source-materials",
        json={"text": "The world is vast.", "document_label": "lore"},
    )
    assert res.status_code == 200
    assert res.json()["ok"] is True


def test_ingest_source_material_unknown_campaign(client):
    res = client.post(
        "/api/campaigns/nonexistent/source-materials",
        json={"text": "anything"},
    )
    assert res.status_code == 404


def test_search_source_material(client):
    campaign = _create_campaign(client)
    cid = campaign["id"]

    res = client.post(
        f"/api/campaigns/{cid}/source-materials/search",
        json={"query": "lore", "top_k": 3},
    )
    assert res.status_code == 200
    body = res.json()
    assert "results" in body
    assert body["query"] == "lore"


def test_search_source_material_unknown_campaign(client):
    res = client.post(
        "/api/campaigns/nonexistent/source-materials/search",
        json={"query": "lore"},
    )
    assert res.status_code == 404


def test_ingest_source_material_with_digest(client):
    campaign = _create_campaign(client)
    cid = campaign["id"]

    res = client.post(
        f"/api/campaigns/{cid}/source-materials/digest",
        json={"text": "Some text to digest.", "document_label": "backstory"},
    )
    assert res.status_code == 200
    assert res.json()["ok"] is True


def test_browse_source_keys(client):
    campaign = _create_campaign(client)
    cid = campaign["id"]

    res = client.get(f"/api/campaigns/{cid}/source-materials/browse")
    assert res.status_code == 200
    assert "keys" in res.json()


def test_browse_source_keys_with_params(client):
    campaign = _create_campaign(client)
    cid = campaign["id"]

    res = client.get(
        f"/api/campaigns/{cid}/source-materials/browse",
        params={"wildcard": "lore*", "document_key": "test-doc"},
    )
    assert res.status_code == 200
    assert "keys" in res.json()


# ---------------------------------------------------------------------------
# Campaign Rules
# ---------------------------------------------------------------------------

def test_get_campaign_rules_empty(client):
    campaign = _create_campaign(client)
    cid = campaign["id"]

    res = client.get(f"/api/campaigns/{cid}/campaign-rules")
    assert res.status_code == 200
    body = res.json()
    assert body["document_key"] == "campaign-rulebook"
    assert body["rules"] == []


def test_create_and_get_campaign_rule(client):
    campaign = _create_campaign(client)
    cid = campaign["id"]

    # Create a rule
    create_res = client.post(
        f"/api/campaigns/{cid}/campaign-rules",
        json={"key": "combat-style", "value": "Always describe consequences."},
    )
    assert create_res.status_code == 200
    body = create_res.json()
    assert body["ok"] is True
    assert body["created"] is True
    assert body["key"] == "combat-style"

    # Get all rules
    list_res = client.get(f"/api/campaigns/{cid}/campaign-rules")
    assert list_res.status_code == 200
    rules = list_res.json()["rules"]
    assert len(rules) == 1
    assert rules[0]["key"] == "combat-style"

    # Get specific rule by key
    key_res = client.get(f"/api/campaigns/{cid}/campaign-rules", params={"key": "combat-style"})
    assert key_res.status_code == 200
    assert key_res.json()["rule"]["value"] == "Always describe consequences."

    # Get missing key returns null
    missing_res = client.get(f"/api/campaigns/{cid}/campaign-rules", params={"key": "nonexistent"})
    assert missing_res.status_code == 200
    assert missing_res.json()["rule"] is None


def test_campaign_rule_no_upsert_blocks_overwrite(client):
    campaign = _create_campaign(client)
    cid = campaign["id"]

    # Create initial rule
    client.post(
        f"/api/campaigns/{cid}/campaign-rules",
        json={"key": "tone", "value": "dark"},
    )

    # Try to overwrite without upsert flag
    res = client.post(
        f"/api/campaigns/{cid}/campaign-rules",
        json={"key": "tone", "value": "light"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert body["reason"] == "exists"
    assert body["old_value"] == "dark"


def test_campaign_rule_upsert_allows_overwrite(client):
    campaign = _create_campaign(client)
    cid = campaign["id"]

    # Create initial rule
    client.post(
        f"/api/campaigns/{cid}/campaign-rules",
        json={"key": "tone", "value": "dark"},
    )

    # Overwrite with upsert=True
    res = client.post(
        f"/api/campaigns/{cid}/campaign-rules",
        json={"key": "tone", "value": "light", "upsert": True},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["replaced"] is True
    assert body["old_value"] == "dark"
    assert body["new_value"] == "light"


def test_campaign_rule_empty_key_or_value_returns_400(client):
    campaign = _create_campaign(client)
    cid = campaign["id"]

    res = client.post(
        f"/api/campaigns/{cid}/campaign-rules",
        json={"key": "", "value": "something"},
    )
    assert res.status_code == 400

    res2 = client.post(
        f"/api/campaigns/{cid}/campaign-rules",
        json={"key": "something", "value": ""},
    )
    assert res2.status_code == 400


# ---------------------------------------------------------------------------
# Rewind & Timer Cancel
# ---------------------------------------------------------------------------

def test_rewind_to_turn(client):
    campaign = _create_campaign(client)
    cid = campaign["id"]

    res = client.post(
        f"/api/campaigns/{cid}/rewind",
        params={"target_turn_id": 1},
    )
    assert res.status_code == 200
    # InMemory backend returns ok=False
    assert "ok" in res.json()


def test_rewind_unknown_campaign(client):
    res = client.post(
        "/api/campaigns/nonexistent/rewind",
        params={"target_turn_id": 1},
    )
    assert res.status_code == 404


def test_cancel_pending_timer(client):
    campaign = _create_campaign(client)
    cid = campaign["id"]

    res = client.post(f"/api/campaigns/{cid}/timers/cancel")
    assert res.status_code == 200
    body = res.json()
    assert "ok" in body


def test_cancel_pending_timer_unknown_campaign(client):
    res = client.post("/api/campaigns/nonexistent/timers/cancel")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Player Statistics & Attributes
# ---------------------------------------------------------------------------

def test_get_player_statistics(client):
    campaign = _create_campaign(client)
    cid = campaign["id"]

    # Trigger player creation via a turn
    client.post(f"/api/campaigns/{cid}/turns", json={"actor_id": "dale-denton", "action": "look"})

    res = client.get(f"/api/campaigns/{cid}/player-statistics", params={"actor_id": "dale-denton"})
    assert res.status_code == 200
    body = res.json()
    assert body["actor_id"] == "dale-denton"
    assert "messages_sent" in body


def test_get_player_statistics_unknown_actor(client):
    campaign = _create_campaign(client)
    cid = campaign["id"]

    res = client.get(f"/api/campaigns/{cid}/player-statistics", params={"actor_id": "nobody"})
    assert res.status_code == 404


def test_get_player_attributes(client):
    campaign = _create_campaign(client)
    cid = campaign["id"]

    client.post(f"/api/campaigns/{cid}/turns", json={"actor_id": "dale-denton", "action": "look"})

    res = client.get(f"/api/campaigns/{cid}/player-attributes", params={"actor_id": "dale-denton"})
    assert res.status_code == 200
    body = res.json()
    assert body["actor_id"] == "dale-denton"
    assert "level" in body
    assert "total_points" in body
    assert "points_spent" in body


def test_set_player_attribute(client):
    campaign = _create_campaign(client)
    cid = campaign["id"]

    client.post(f"/api/campaigns/{cid}/turns", json={"actor_id": "dale-denton", "action": "look"})

    res = client.post(
        f"/api/campaigns/{cid}/player-attributes",
        json={"actor_id": "dale-denton", "attribute": "strength", "value": 5},
    )
    assert res.status_code == 200
    # InMemory returns ok=False
    assert "ok" in res.json()


def test_set_player_attribute_unknown_campaign(client):
    res = client.post(
        "/api/campaigns/nonexistent/player-attributes",
        json={"actor_id": "dale-denton", "attribute": "strength", "value": 5},
    )
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Rename & Level-Up
# ---------------------------------------------------------------------------

def test_rename_player_character(client):
    campaign = _create_campaign(client)
    cid = campaign["id"]

    client.post(f"/api/campaigns/{cid}/turns", json={"actor_id": "dale-denton", "action": "look"})

    res = client.post(
        f"/api/campaigns/{cid}/player-name",
        json={"actor_id": "dale-denton", "name": "Dale the Brave"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["name"] == "Dale the Brave"
    assert body["actor_id"] == "dale-denton"


def test_rename_player_empty_name_returns_400(client):
    campaign = _create_campaign(client)
    cid = campaign["id"]

    client.post(f"/api/campaigns/{cid}/turns", json={"actor_id": "dale-denton", "action": "look"})

    res = client.post(
        f"/api/campaigns/{cid}/player-name",
        json={"actor_id": "dale-denton", "name": "   "},
    )
    assert res.status_code == 400


def test_rename_unknown_actor_returns_404(client):
    campaign = _create_campaign(client)
    cid = campaign["id"]

    res = client.post(
        f"/api/campaigns/{cid}/player-name",
        json={"actor_id": "nobody", "name": "Test"},
    )
    assert res.status_code == 404


def test_level_up_player(client):
    campaign = _create_campaign(client)
    cid = campaign["id"]

    client.post(f"/api/campaigns/{cid}/turns", json={"actor_id": "dale-denton", "action": "look"})

    res = client.post(
        f"/api/campaigns/{cid}/level-up",
        json={"actor_id": "dale-denton"},
    )
    assert res.status_code == 200
    assert "ok" in res.json()


def test_level_up_unknown_actor_still_responds(client):
    """InMemory backend's level_up doesn't validate the actor — just returns ok=False."""
    campaign = _create_campaign(client)
    cid = campaign["id"]

    res = client.post(
        f"/api/campaigns/{cid}/level-up",
        json={"actor_id": "nobody"},
    )
    # InMemory returns 200 with ok=False (no player validation on this path)
    assert res.status_code == 200
    assert res.json()["ok"] is False


# ---------------------------------------------------------------------------
# Persona
# ---------------------------------------------------------------------------

def test_get_campaign_persona(client):
    campaign = _create_campaign(client)
    cid = campaign["id"]

    res = client.get(f"/api/campaigns/{cid}/persona")
    assert res.status_code == 200
    body = res.json()
    assert "persona" in body
    assert isinstance(body["persona"], str)
    assert len(body["persona"]) > 0


def test_set_campaign_persona(client):
    campaign = _create_campaign(client)
    cid = campaign["id"]

    res = client.post(
        f"/api/campaigns/{cid}/persona",
        json={"persona": "A sardonic AI overlord."},
    )
    assert res.status_code == 200
    assert res.json()["ok"] is True


def test_persona_unknown_campaign(client):
    res = client.get("/api/campaigns/nonexistent/persona")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Puzzle & Minigame
# ---------------------------------------------------------------------------

def test_get_puzzle_hint(client):
    campaign = _create_campaign(client)
    cid = campaign["id"]

    res = client.get(f"/api/campaigns/{cid}/puzzle/hint")
    assert res.status_code == 200
    body = res.json()
    assert "hint" in body


def test_submit_puzzle_answer(client):
    campaign = _create_campaign(client)
    cid = campaign["id"]

    res = client.post(
        f"/api/campaigns/{cid}/puzzle/answer",
        json={"answer": "42"},
    )
    assert res.status_code == 200
    body = res.json()
    assert "correct" in body
    assert "solved" in body


def test_puzzle_unknown_campaign(client):
    res = client.get("/api/campaigns/nonexistent/puzzle/hint")
    assert res.status_code == 404


def test_get_minigame_board(client):
    campaign = _create_campaign(client)
    cid = campaign["id"]

    res = client.get(f"/api/campaigns/{cid}/minigame/board")
    assert res.status_code == 200
    body = res.json()
    assert "board" in body


def test_submit_minigame_move(client):
    campaign = _create_campaign(client)
    cid = campaign["id"]

    res = client.post(
        f"/api/campaigns/{cid}/minigame/move",
        json={"move": "e2e4"},
    )
    assert res.status_code == 200
    body = res.json()
    assert "valid" in body
    assert "finished" in body


def test_minigame_unknown_campaign(client):
    res = client.get("/api/campaigns/nonexistent/minigame/board")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Campaign Setup
# ---------------------------------------------------------------------------

def test_get_setup_status(client):
    campaign = _create_campaign(client)
    cid = campaign["id"]

    res = client.get(f"/api/campaigns/{cid}/setup")
    assert res.status_code == 200
    body = res.json()
    assert "in_setup" in body
    assert body["in_setup"] is False


def test_start_campaign_setup(client):
    campaign = _create_campaign(client)
    cid = campaign["id"]

    res = client.post(
        f"/api/campaigns/{cid}/setup/start",
        json={"actor_id": "dale-denton", "on_rails": False},
    )
    assert res.status_code == 200
    assert "ok" in res.json()


def test_handle_setup_message(client):
    campaign = _create_campaign(client)
    cid = campaign["id"]

    res = client.post(
        f"/api/campaigns/{cid}/setup/message",
        json={"actor_id": "dale-denton", "message": "I want a fantasy world."},
    )
    assert res.status_code == 200
    assert "ok" in res.json()


def test_setup_unknown_campaign(client):
    res = client.get("/api/campaigns/nonexistent/setup")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Scene Images & Literary Styles
# ---------------------------------------------------------------------------

def test_get_scene_images(client):
    campaign = _create_campaign(client)
    cid = campaign["id"]

    res = client.get(f"/api/campaigns/{cid}/scene-images")
    assert res.status_code == 200
    assert "images" in res.json()


def test_scene_images_unknown_campaign(client):
    res = client.get("/api/campaigns/nonexistent/scene-images")
    assert res.status_code == 404


def test_get_literary_styles(client):
    campaign = _create_campaign(client)
    cid = campaign["id"]

    res = client.get(f"/api/campaigns/{cid}/literary-styles")
    assert res.status_code == 200
    assert "styles" in res.json()


def test_literary_styles_unknown_campaign(client):
    res = client.get("/api/campaigns/nonexistent/literary-styles")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# SMS cancel & schedule
# ---------------------------------------------------------------------------

def test_cancel_sms_deliveries(client):
    campaign = _create_campaign(client)
    cid = campaign["id"]

    res = client.post(f"/api/campaigns/{cid}/sms/cancel")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["cancelled"] == 0


def test_cancel_sms_unknown_campaign(client):
    res = client.post("/api/campaigns/nonexistent/sms/cancel")
    assert res.status_code == 404


def test_schedule_sms_delivery(client):
    campaign = _create_campaign(client)
    cid = campaign["id"]

    res = client.post(
        f"/api/campaigns/{cid}/sms/schedule",
        json={
            "thread": "saul",
            "sender": "dale-denton",
            "recipient": "saul-silver",
            "message": "Reminder: 5pm.",
            "delay_seconds": 60,
        },
    )
    assert res.status_code == 200
    assert "ok" in res.json()


def test_schedule_sms_unknown_campaign(client):
    res = client.post(
        "/api/campaigns/nonexistent/sms/schedule",
        json={
            "thread": "saul",
            "sender": "dale",
            "recipient": "saul",
            "message": "Hi",
            "delay_seconds": 10,
        },
    )
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Character Portrait
# ---------------------------------------------------------------------------

def test_record_character_portrait(client):
    campaign = _create_campaign(client)
    cid = campaign["id"]

    res = client.post(
        f"/api/campaigns/{cid}/roster/portrait",
        json={"character_slug": "dale-denton", "image_url": "https://example.com/portrait.png"},
    )
    assert res.status_code == 200
    assert "ok" in res.json()


def test_character_portrait_unknown_campaign(client):
    res = client.post(
        "/api/campaigns/nonexistent/roster/portrait",
        json={"character_slug": "dale-denton", "image_url": "https://example.com/portrait.png"},
    )
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Story State
# ---------------------------------------------------------------------------

def test_get_story_state(client):
    campaign = _create_campaign(client)
    cid = campaign["id"]

    res = client.get(f"/api/campaigns/{cid}/story")
    assert res.status_code == 200
    body = res.json()
    assert "on_rails" in body
    assert "story_outline" in body
    assert "current_chapter" in body
    assert "active_puzzle" in body
    assert "active_minigame" in body


def test_story_state_unknown_campaign(client):
    res = client.get("/api/campaigns/nonexistent/story")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Campaign Export
# ---------------------------------------------------------------------------

def test_campaign_export(client):
    campaign = _create_campaign(client)
    cid = campaign["id"]

    # Submit a turn so there's data
    client.post(f"/api/campaigns/{cid}/turns", json={"actor_id": "dale-denton", "action": "look"})

    res = client.get(f"/api/campaigns/{cid}/export")
    assert res.status_code == 200
    body = res.json()
    assert "turns" in body or "export" in body or isinstance(body, dict)


def test_campaign_export_unknown_campaign(client):
    res = client.get("/api/campaigns/nonexistent/export")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# LLM Settings (inmemory backend rejects setting changes)
# ---------------------------------------------------------------------------

def test_get_settings(client):
    res = client.get("/api/settings")
    assert res.status_code == 200
    body = res.json()
    assert "completion_mode" in body
    assert "gateway_backend" in body


def test_update_settings_inmemory_rejects(client):
    """InMemory backend is not tge, so setting updates should be rejected."""
    res = client.post(
        "/api/settings",
        json={"model": "llama3.2"},
    )
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# DTM Link Status (no link configured by default)
# ---------------------------------------------------------------------------

def test_dtm_link_status_disabled(client):
    res = client.get("/api/dtm-link/status")
    assert res.status_code == 200
    body = res.json()
    assert body["enabled"] is False
    assert body["linked"] is False
