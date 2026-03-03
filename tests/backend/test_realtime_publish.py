from __future__ import annotations

from unittest.mock import AsyncMock


def _create_campaign(client, name="Realtime Test", actor_id="dale-denton"):
    res = client.post(
        "/api/campaigns",
        json={"namespace": "default", "name": name, "actor_id": actor_id},
    )
    assert res.status_code == 200
    return res.json()["campaign"]


def _published_types(mock: AsyncMock) -> list[str]:
    types: list[str] = []
    for call in mock.await_args_list:
        payload = call.args[1]
        types.append(str(payload.get("type")))
    return types


def test_submit_turn_publishes_turn_timers_without_scene_media(client):
    campaign = _create_campaign(client)
    campaign_id = campaign["id"]
    publish = AsyncMock()
    client.app.state.realtime.publish = publish

    res = client.post(
        f"/api/campaigns/{campaign_id}/turns",
        json={"actor_id": "dale-denton", "action": "wait"},
    )
    assert res.status_code == 200

    assert _published_types(publish) == ["turn", "timers"]


def test_submit_turn_publishes_turn_media_timers_with_scene_media(client):
    campaign = _create_campaign(client)
    campaign_id = campaign["id"]
    publish = AsyncMock()
    client.app.state.realtime.publish = publish

    res = client.post(
        f"/api/campaigns/{campaign_id}/turns",
        json={"actor_id": "dale-denton", "action": "look around"},
    )
    assert res.status_code == 200

    assert _published_types(publish) == ["turn", "media", "timers"]


def test_sms_write_publishes_sms_event(client):
    campaign = _create_campaign(client)
    campaign_id = campaign["id"]
    publish = AsyncMock()
    client.app.state.realtime.publish = publish

    res = client.post(
        f"/api/campaigns/{campaign_id}/sms/write",
        json={
            "thread": "saul",
            "sender": "dale-denton",
            "recipient": "saul-silver",
            "message": "Need pickup now.",
        },
    )
    assert res.status_code == 200

    assert _published_types(publish) == ["sms"]


def test_session_route_publishes_session_event(client):
    campaign = _create_campaign(client)
    campaign_id = campaign["id"]
    publish = AsyncMock()
    client.app.state.realtime.publish = publish

    res = client.post(
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
    assert res.status_code == 200

    assert _published_types(publish) == ["session"]


def test_roster_route_publishes_roster_event(client):
    campaign = _create_campaign(client)
    campaign_id = campaign["id"]
    publish = AsyncMock()
    client.app.state.realtime.publish = publish

    res = client.post(
        f"/api/campaigns/{campaign_id}/roster/upsert",
        json={
            "slug": "arsipea-denton",
            "name": "Arsipea Denton",
            "location": "visitor-room-b",
            "status": "active",
        },
    )
    assert res.status_code == 200

    assert _published_types(publish) == ["roster"]


def test_avatar_accept_publishes_media_event(client):
    campaign = _create_campaign(client)
    campaign_id = campaign["id"]
    gateway = client.app.state.gateway
    gateway._players[campaign_id]["dale-denton"]["state"]["pending_avatar_url"] = "https://example.com/pending.png"

    publish = AsyncMock()
    client.app.state.realtime.publish = publish

    res = client.post(
        f"/api/campaigns/{campaign_id}/media/avatar/accept",
        json={"actor_id": "dale-denton"},
    )
    assert res.status_code == 200

    assert _published_types(publish) == ["media"]
    payload = publish.await_args_list[0].args[1]
    assert payload["payload"]["action"] == "avatar_accept"
