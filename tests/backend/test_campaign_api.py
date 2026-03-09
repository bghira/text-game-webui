def _create_campaign(client, name="Smoke Test", actor_id="dale-denton"):
    res = client.post(
        "/api/campaigns",
        json={"namespace": "default", "name": name, "actor_id": actor_id},
    )
    assert res.status_code == 200
    return res.json()["campaign"]


def test_campaign_flow_and_inspector_surfaces(client):
    campaign = _create_campaign(client)
    campaign_id = campaign["id"]

    sessions_before = client.get(f"/api/campaigns/{campaign_id}/sessions")
    assert sessions_before.status_code == 200
    assert sessions_before.json()["sessions"] == []

    session_create = client.post(
        f"/api/campaigns/{campaign_id}/sessions",
        json={
            "surface": "discord_thread",
            "surface_key": "discord:guild-1:thread-4",
            "surface_guild_id": "guild-1",
            "surface_channel_id": "channel-1",
            "surface_thread_id": "thread-4",
            "enabled": True,
            "metadata": {"active_campaign_id": campaign_id},
        },
    )
    assert session_create.status_code == 200
    session_row = session_create.json()["session"]
    assert session_row["surface_key"] == "discord:guild-1:thread-4"
    assert session_row["enabled"] is True

    session_patch = client.patch(
        f"/api/campaigns/{campaign_id}/sessions/{session_row['id']}",
        json={"enabled": False, "metadata": {"note": "paused"}},
    )
    assert session_patch.status_code == 200
    assert session_patch.json()["session"]["enabled"] is False

    list_res = client.get("/api/campaigns", params={"namespace": "default"})
    assert list_res.status_code == 200
    assert any(row["id"] == campaign_id for row in list_res.json()["campaigns"])

    turn_res = client.post(
        f"/api/campaigns/{campaign_id}/turns",
        json={"actor_id": "dale-denton", "action": "look around"},
    )
    assert turn_res.status_code == 200
    turn = turn_res.json()
    assert "TURN 1" in turn["narration"]
    assert turn["image_prompt"] is not None

    map_res = client.get(f"/api/campaigns/{campaign_id}/map", params={"actor_id": "dale-denton"})
    assert map_res.status_code == 200
    assert "TEST FACILITY" in map_res.json()["map"]

    timers_res = client.get(f"/api/campaigns/{campaign_id}/timers")
    assert timers_res.status_code == 200
    assert "timers" in timers_res.json()

    cal_res = client.get(f"/api/campaigns/{campaign_id}/calendar")
    assert cal_res.status_code == 200
    assert "events" in cal_res.json()

    roster_res = client.get(f"/api/campaigns/{campaign_id}/roster")
    assert roster_res.status_code == 200
    assert roster_res.json()["characters"][0]["slug"] == "dale-denton"

    roster_upsert = client.post(
        f"/api/campaigns/{campaign_id}/roster/upsert",
        json={
            "slug": "arsipea-denton",
            "name": "Arsipea Denton",
            "location": "visitor-room-b",
            "status": "active",
            "fields": {"appearance": "gray jumpsuit"},
        },
    )
    assert roster_upsert.status_code == 200
    assert roster_upsert.json()["ok"] is True

    roster_after_upsert = client.get(f"/api/campaigns/{campaign_id}/roster")
    assert roster_after_upsert.status_code == 200
    assert any(row["slug"] == "arsipea-denton" for row in roster_after_upsert.json()["characters"])

    roster_remove = client.post(
        f"/api/campaigns/{campaign_id}/roster/remove",
        json={"slug": "arsipea-denton", "player": False},
    )
    assert roster_remove.status_code == 200
    assert roster_remove.json()["removed"] is True

    roster_after_remove = client.get(f"/api/campaigns/{campaign_id}/roster")
    assert roster_after_remove.status_code == 200
    assert not any(row["slug"] == "arsipea-denton" for row in roster_after_remove.json()["characters"])

    player_res = client.get(
        f"/api/campaigns/{campaign_id}/player-state",
        params={"actor_id": "dale-denton"},
    )
    assert player_res.status_code == 200
    player_state = player_res.json()["player_state"]
    assert player_state["actor_id"] == "dale-denton"
    assert "inventory" in player_state

    media_res = client.get(
        f"/api/campaigns/{campaign_id}/media",
        params={"actor_id": "dale-denton"},
    )
    assert media_res.status_code == 200
    media = media_res.json()["media"]
    assert "scene" in media
    assert "avatars" in media
    assert "requests" in media["scene"]
    assert media["scene"]["request_count"] >= 0

    # Seed a pending avatar in the in-memory backend and verify action endpoints.
    gateway = client.app.state.gateway
    gateway._players[campaign_id]["dale-denton"]["state"]["pending_avatar_url"] = "https://example.com/pending-avatar.png"
    gateway._players[campaign_id]["dale-denton"]["state"]["pending_avatar_prompt"] = "portrait, noir lighting"

    accept_res = client.post(
        f"/api/campaigns/{campaign_id}/media/avatar/accept",
        json={"actor_id": "dale-denton"},
    )
    assert accept_res.status_code == 200
    assert accept_res.json()["ok"] is True

    decline_res = client.post(
        f"/api/campaigns/{campaign_id}/media/avatar/decline",
        json={"actor_id": "dale-denton"},
    )
    assert decline_res.status_code == 200
    assert decline_res.json()["ok"] is False


def test_memory_and_sms_tools(client):
    campaign = _create_campaign(client)
    campaign_id = campaign["id"]

    turn_res = client.post(
        f"/api/campaigns/{campaign_id}/turns",
        json={"actor_id": "dale-denton", "action": "look around"},
    )
    assert turn_res.status_code == 200

    memory_turn_res = client.post(
        f"/api/campaigns/{campaign_id}/memory/turn",
        json={"turn_id": 1},
    )
    assert memory_turn_res.status_code == 200
    turn_payload = memory_turn_res.json()["turn"]
    assert turn_payload is not None
    assert turn_payload["id"] == 1

    store_res = client.post(
        f"/api/campaigns/{campaign_id}/memory/store",
        json={"category": "char:dale-denton", "term": "belmond", "memory": "Booked room 420."},
    )
    assert store_res.status_code == 200
    assert store_res.json()["stored"] is True

    search_res = client.post(
        f"/api/campaigns/{campaign_id}/memory/search",
        json={"queries": ["room 420"], "category": "char:dale-denton"},
    )
    assert search_res.status_code == 200
    assert len(search_res.json()["hits"]) == 1

    terms_res = client.post(
        f"/api/campaigns/{campaign_id}/memory/terms",
        json={"wildcard": "*"},
    )
    assert terms_res.status_code == 200
    assert "belmond" in terms_res.json()["terms"]

    sms_write_res = client.post(
        f"/api/campaigns/{campaign_id}/sms/write",
        json={
            "thread": "saul",
            "sender": "dale-denton",
            "recipient": "saul-silver",
            "message": "Need pickup now.",
        },
    )
    assert sms_write_res.status_code == 200

    sms_list_res = client.post(f"/api/campaigns/{campaign_id}/sms/list", json={"wildcard": "*"})
    assert sms_list_res.status_code == 200
    assert "saul" in sms_list_res.json()["threads"]

    sms_read_res = client.post(
        f"/api/campaigns/{campaign_id}/sms/read",
        json={"thread": "saul", "limit": 10},
    )
    assert sms_read_res.status_code == 200
    assert sms_read_res.json()["messages"][0]["message"] == "Need pickup now."


def test_debug_snapshot_and_unknown_campaign(client):
    campaign = _create_campaign(client)
    campaign_id = campaign["id"]

    client.post(
        f"/api/campaigns/{campaign_id}/turns",
        json={"actor_id": "dale-denton", "action": "wait"},
    )
    debug_res = client.get(f"/api/campaigns/{campaign_id}/debug/snapshot")
    assert debug_res.status_code == 200
    body = debug_res.json()
    assert "turns" in body

    missing = client.get("/api/campaigns/missing-campaign/debug/snapshot")
    assert missing.status_code == 404

    missing_player = client.get(
        f"/api/campaigns/{campaign_id}/player-state",
        params={"actor_id": "missing-actor"},
    )
    assert missing_player.status_code == 404

    missing_session = client.patch(
        f"/api/campaigns/{campaign_id}/sessions/missing-session-id",
        json={"enabled": False},
    )
    assert missing_session.status_code == 404

    missing_media_player = client.get(
        f"/api/campaigns/{campaign_id}/media",
        params={"actor_id": "missing-actor"},
    )
    assert missing_media_player.status_code == 200

    missing_avatar_action = client.post(
        f"/api/campaigns/{campaign_id}/media/avatar/accept",
        json={"actor_id": "missing-actor"},
    )
    assert missing_avatar_action.status_code == 404

    missing_campaign_sessions = client.get("/api/campaigns/missing-campaign/sessions")
    assert missing_campaign_sessions.status_code == 404


def test_diagnostics_bundle_with_campaign(client):
    campaign = _create_campaign(client)
    campaign_id = campaign["id"]

    client.post(
        f"/api/campaigns/{campaign_id}/turns",
        json={"actor_id": "dale-denton", "action": "look"},
    )
    res = client.get("/api/diagnostics/bundle", params={"campaign_id": campaign_id})
    assert res.status_code == 200
    body = res.json()
    assert body["campaign_id"] == campaign_id
    assert "campaign_debug_snapshot" in body
    assert "runtime_checks" in body
    assert "checks" in body["runtime_checks"]
    assert "turns" in body["campaign_debug_snapshot"]

    missing = client.get("/api/diagnostics/bundle", params={"campaign_id": "missing-campaign"})
    assert missing.status_code == 404


def test_ws_receives_turn_event(client):
    campaign = _create_campaign(client)
    campaign_id = campaign["id"]

    with client.websocket_connect(f"/ws/campaigns/{campaign_id}") as ws:
        post = client.post(
            f"/api/campaigns/{campaign_id}/turns",
            json={"actor_id": "dale-denton", "action": "look"},
        )
        assert post.status_code == 200
        message = ws.receive_json()
        assert message["type"] == "turn"
        assert message["payload"]["narration"].startswith("TURN 1")


def test_private_window_turn_submission_returns_session_visibility(client):
    campaign = _create_campaign(client)
    campaign_id = campaign["id"]

    session_create = client.post(
        f"/api/campaigns/{campaign_id}/sessions",
        json={
            "surface": "web_private",
            "surface_key": f"webui:{campaign_id}:private:dale-denton",
            "enabled": True,
            "metadata": {
                "label": "Private room: dale-denton",
                "scope": "private",
                "turn_visibility_default": "private",
                "owner_actor_id": "dale-denton",
                "allowed_actor_ids": ["dale-denton"],
            },
        },
    )
    assert session_create.status_code == 200
    session_row = session_create.json()["session"]

    turn_res = client.post(
        f"/api/campaigns/{campaign_id}/turns",
        json={"actor_id": "dale-denton", "action": "whisper to Monet", "session_id": session_row["id"]},
    )
    assert turn_res.status_code == 200
    turn = turn_res.json()
    assert turn["session_id"] == session_row["id"]
    assert turn["actor_id"] == "dale-denton"
    assert turn["turn_visibility"]["scope"] == "private"


def test_shared_window_turn_submission_returns_local_visibility(client):
    campaign = _create_campaign(client)
    campaign_id = campaign["id"]

    session_create = client.post(
        f"/api/campaigns/{campaign_id}/sessions",
        json={
            "surface": "web_shared",
            "surface_key": f"webui:{campaign_id}:shared",
            "enabled": True,
            "metadata": {
                "label": "Shared web room",
                "scope": "local",
                "turn_visibility_default": "local",
            },
        },
    )
    assert session_create.status_code == 200
    session_row = session_create.json()["session"]

    turn_res = client.post(
        f"/api/campaigns/{campaign_id}/turns",
        json={"actor_id": "dale-denton", "action": "look around", "session_id": session_row["id"]},
    )
    assert turn_res.status_code == 200
    turn = turn_res.json()
    assert turn["session_id"] == session_row["id"]
    assert turn["turn_visibility"]["scope"] == "local"


def test_ws_receives_session_event(client):
    campaign = _create_campaign(client)
    campaign_id = campaign["id"]

    with client.websocket_connect(f"/ws/campaigns/{campaign_id}") as ws:
        post = client.post(
            f"/api/campaigns/{campaign_id}/sessions",
            json={
                "surface": "discord_thread",
                "surface_key": "discord:guild-9:thread-77",
                "surface_guild_id": "guild-9",
                "surface_channel_id": "channel-77",
                "surface_thread_id": "thread-77",
                "enabled": True,
                "metadata": {},
            },
        )
        assert post.status_code == 200
        message = ws.receive_json()
        assert message["type"] == "session"
        assert message["payload"]["surface_key"] == "discord:guild-9:thread-77"


def test_ws_receives_roster_event(client):
    campaign = _create_campaign(client)
    campaign_id = campaign["id"]

    with client.websocket_connect(f"/ws/campaigns/{campaign_id}") as ws:
        post = client.post(
            f"/api/campaigns/{campaign_id}/roster/upsert",
            json={
                "slug": "arsipea-denton",
                "name": "Arsipea Denton",
                "location": "visitor-room-b",
                "status": "active",
            },
        )
        assert post.status_code == 200
        message = ws.receive_json()
        assert message["type"] == "roster"
        assert any(row["slug"] == "arsipea-denton" for row in message["payload"]["characters"])


def test_ws_receives_media_event_on_avatar_action(client):
    campaign = _create_campaign(client)
    campaign_id = campaign["id"]
    gateway = client.app.state.gateway
    gateway._players[campaign_id]["dale-denton"]["state"]["pending_avatar_url"] = "https://example.com/pending.png"

    with client.websocket_connect(f"/ws/campaigns/{campaign_id}") as ws:
        post = client.post(
            f"/api/campaigns/{campaign_id}/media/avatar/accept",
            json={"actor_id": "dale-denton"},
        )
        assert post.status_code == 200
        message = ws.receive_json()
        assert message["type"] == "media"
        assert message["payload"]["action"] == "avatar_accept"
        assert message["payload"]["ok"] is True
