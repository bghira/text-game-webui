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


def _parse_sse_events(raw_text: str) -> list[dict]:
    """Parse a raw SSE text body into a list of {event, data} dicts."""
    events = []
    current_event = None
    current_data_lines: list[str] = []
    for line in raw_text.splitlines():
        if line.startswith("event:"):
            current_event = line[len("event:"):].strip()
        elif line.startswith("data:"):
            current_data_lines.append(line[len("data:"):].strip())
        elif line == "":
            if current_event is not None or current_data_lines:
                import json as _json
                data_str = "\n".join(current_data_lines)
                try:
                    data = _json.loads(data_str)
                except (ValueError, TypeError):
                    data = data_str
                events.append({"event": current_event or "message", "data": data})
                current_event = None
                current_data_lines = []
    # Handle trailing event without final blank line
    if current_event is not None or current_data_lines:
        import json as _json
        data_str = "\n".join(current_data_lines)
        try:
            data = _json.loads(data_str)
        except (ValueError, TypeError):
            data = data_str
        events.append({"event": current_event or "message", "data": data})
    return events


def test_stream_turn_returns_sse_events(client):
    """POST /turns/stream should return phase, token, and complete SSE events."""
    campaign = _create_campaign(client)
    campaign_id = campaign["id"]

    res = client.post(
        f"/api/campaigns/{campaign_id}/turns/stream",
        json={"actor_id": "dale-denton", "action": "look around"},
    )
    assert res.status_code == 200
    assert "text/event-stream" in res.headers.get("content-type", "")

    events = _parse_sse_events(res.text)
    event_types = [e["event"] for e in events]

    # Must contain at least: phase(starting), phase(generating), phase(narrating), token(s), complete
    assert "phase" in event_types
    assert "token" in event_types
    assert "complete" in event_types

    # Phase events should come before tokens which should come before complete
    first_phase = event_types.index("phase")
    first_token = event_types.index("token")
    complete_idx = event_types.index("complete")
    assert first_phase < first_token < complete_idx

    # The complete event should contain a valid TurnResult-like payload
    complete_data = events[complete_idx]["data"]
    assert "narration" in complete_data
    assert "TURN 1" in complete_data["narration"]
    assert complete_data["actor_id"] == "dale-denton"
    assert complete_data["image_prompt"] is not None


def test_stream_turn_unknown_campaign_returns_error_event(client):
    """POST /turns/stream with bad campaign_id should yield an error SSE event."""
    res = client.post(
        "/api/campaigns/nonexistent-campaign/turns/stream",
        json={"actor_id": "dale-denton", "action": "wait"},
    )
    assert res.status_code == 200
    events = _parse_sse_events(res.text)
    assert len(events) >= 1
    assert events[-1]["event"] == "error"


def test_stream_turn_token_text_matches_narration(client):
    """Token texts concatenated should equal the complete narration."""
    campaign = _create_campaign(client)
    campaign_id = campaign["id"]

    res = client.post(
        f"/api/campaigns/{campaign_id}/turns/stream",
        json={"actor_id": "dale-denton", "action": "wait"},
    )
    assert res.status_code == 200

    events = _parse_sse_events(res.text)
    token_texts = "".join(
        e["data"]["text"] for e in events if e["event"] == "token"
    )
    complete_event = next(e for e in events if e["event"] == "complete")
    assert token_texts == complete_event["data"]["narration"]


def test_delete_campaign_removes_it(client):
    """DELETE /campaigns/{id} should remove the campaign from listings."""
    campaign = _create_campaign(client)
    campaign_id = campaign["id"]

    # Verify it exists
    list_before = client.get("/api/campaigns", params={"namespace": "default"})
    assert any(c["id"] == campaign_id for c in list_before.json()["campaigns"])

    # Delete
    del_res = client.delete(f"/api/campaigns/{campaign_id}")
    assert del_res.status_code == 200
    assert del_res.json()["ok"] is True
    assert del_res.json()["deleted_campaign_id"] == campaign_id

    # Verify it's gone
    list_after = client.get("/api/campaigns", params={"namespace": "default"})
    assert not any(c["id"] == campaign_id for c in list_after.json()["campaigns"])

    # Subsequent reads should 404
    get_res = client.get(f"/api/campaigns/{campaign_id}/roster")
    assert get_res.status_code == 404


def test_delete_campaign_unknown_returns_404(client):
    """DELETE /campaigns/{id} with unknown id should return 404."""
    res = client.delete("/api/campaigns/nonexistent-campaign")
    assert res.status_code == 404


def test_sms_read_with_viewer_actor_id(client):
    """POST /sms/read should accept viewer_actor_id without error."""
    campaign = _create_campaign(client)
    campaign_id = campaign["id"]

    # Write a message first
    client.post(
        f"/api/campaigns/{campaign_id}/sms/write",
        json={
            "thread": "saul",
            "sender": "dale-denton",
            "recipient": "saul-silver",
            "message": "Hey dude.",
        },
    )

    # Read with viewer_actor_id
    res = client.post(
        f"/api/campaigns/{campaign_id}/sms/read",
        json={"thread": "saul", "limit": 10, "viewer_actor_id": "dale-denton"},
    )
    assert res.status_code == 200
    assert res.json()["thread"] == "saul"
    assert len(res.json()["messages"]) == 1

    # Read without viewer_actor_id (should also work)
    res_no_viewer = client.post(
        f"/api/campaigns/{campaign_id}/sms/read",
        json={"thread": "saul", "limit": 10},
    )
    assert res_no_viewer.status_code == 200
    assert len(res_no_viewer.json()["messages"]) == 1


def test_get_chapters_happy_path(client):
    campaign = _create_campaign(client)
    campaign_id = campaign["id"]

    res = client.get(f"/api/campaigns/{campaign_id}/chapters")
    assert res.status_code == 200
    body = res.json()
    assert "chapters" in body
    assert isinstance(body["chapters"], list)
    assert "on_rails" in body


def test_get_chapters_unknown_campaign(client):
    res = client.get("/api/campaigns/nonexistent-campaign/chapters")
    assert res.status_code == 404


def test_recent_turns_offset_pagination(client):
    campaign = _create_campaign(client)
    campaign_id = campaign["id"]

    # Submit 5 turns
    for i in range(5):
        res = client.post(
            f"/api/campaigns/{campaign_id}/turns",
            json={"actor_id": "dale-denton", "action": f"action {i + 1}"},
        )
        assert res.status_code == 200

    # Page 1: latest 2 turns (turns 4 & 5)
    res1 = client.get(f"/api/campaigns/{campaign_id}/recent-turns", params={"limit": 2, "offset": 0})
    assert res1.status_code == 200
    body1 = res1.json()
    assert body1["count"] == 2
    assert body1["has_more"] is True
    ids1 = [t["id"] for t in body1["turns"]]
    assert ids1 == [4, 5]

    # Page 2: next 2 turns (turns 2 & 3)
    res2 = client.get(f"/api/campaigns/{campaign_id}/recent-turns", params={"limit": 2, "offset": 2})
    assert res2.status_code == 200
    body2 = res2.json()
    assert body2["count"] == 2
    assert body2["has_more"] is True
    ids2 = [t["id"] for t in body2["turns"]]
    assert ids2 == [2, 3]

    # Page 3: last turn (turn 1)
    res3 = client.get(f"/api/campaigns/{campaign_id}/recent-turns", params={"limit": 2, "offset": 4})
    assert res3.status_code == 200
    body3 = res3.json()
    assert body3["count"] == 1
    assert body3["has_more"] is False
    ids3 = [t["id"] for t in body3["turns"]]
    assert ids3 == [1]

    # Offset beyond total returns empty
    res4 = client.get(f"/api/campaigns/{campaign_id}/recent-turns", params={"limit": 2, "offset": 10})
    assert res4.status_code == 200
    body4 = res4.json()
    assert body4["count"] == 0
    assert body4["has_more"] is False
    assert body4["turns"] == []

    # Default (no offset) returns all 5 with has_more false
    res5 = client.get(f"/api/campaigns/{campaign_id}/recent-turns", params={"limit": 30})
    assert res5.status_code == 200
    body5 = res5.json()
    assert body5["count"] == 5
    assert body5["has_more"] is False
