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

    cal_res = client.get(f"/api/campaigns/{campaign_id}/calendar")
    assert cal_res.status_code == 200
    assert "events" in cal_res.json()

    roster_res = client.get(f"/api/campaigns/{campaign_id}/roster")
    assert roster_res.status_code == 200
    assert roster_res.json()["characters"][0]["slug"] == "dale-denton"

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


def test_memory_and_sms_tools(client):
    campaign = _create_campaign(client)
    campaign_id = campaign["id"]

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

    missing_media_player = client.get(
        f"/api/campaigns/{campaign_id}/media",
        params={"actor_id": "missing-actor"},
    )
    assert missing_media_player.status_code == 200


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
