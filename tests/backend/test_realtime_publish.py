from __future__ import annotations

import asyncio
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


def test_stream_turn_publishes_realtime_events(client):
    """POST /turns/stream should still publish turn+timers via realtime."""
    campaign = _create_campaign(client)
    campaign_id = campaign["id"]
    publish = AsyncMock()
    client.app.state.realtime.publish = publish

    res = client.post(
        f"/api/campaigns/{campaign_id}/turns/stream",
        json={"actor_id": "dale-denton", "action": "wait"},
    )
    assert res.status_code == 200

    # Even though it's streaming, realtime events must be published
    assert _published_types(publish) == ["turn", "timers"]


def test_stream_turn_publishes_media_event_for_look(client):
    """POST /turns/stream with scene-triggering action publishes turn+media+timers."""
    campaign = _create_campaign(client)
    campaign_id = campaign["id"]
    publish = AsyncMock()
    client.app.state.realtime.publish = publish

    res = client.post(
        f"/api/campaigns/{campaign_id}/turns/stream",
        json={"actor_id": "dale-denton", "action": "look around"},
    )
    assert res.status_code == 200

    assert _published_types(publish) == ["turn", "media", "timers"]


def test_web_timer_effects_port_publishes_timed_event():
    """WebTimerEffectsPort.emit_timed_event should publish via RealtimeHub."""
    from app.main import WebTimerEffectsPort

    hub_publish = AsyncMock()

    class FakeHub:
        publish = hub_publish

    port = WebTimerEffectsPort(FakeHub())

    asyncio.get_event_loop().run_until_complete(
        port.emit_timed_event(
            campaign_id="campaign-42",
            channel_id="ch-1",
            actor_id="dale-denton",
            narration="A rumbling sound echoes through the cave.",
        )
    )

    hub_publish.assert_awaited_once()
    call_args = hub_publish.await_args
    assert call_args.args[0] == "campaign-42"
    payload = call_args.args[1]
    assert payload["type"] == "timed_event"
    assert payload["actor_id"] == "dale-denton"
    assert payload["payload"]["narration"] == "A rumbling sound echoes through the cave."
    assert payload["payload"]["actor_id"] == "dale-denton"


def test_web_timer_effects_port_edit_timer_line_is_noop():
    """edit_timer_line should be a no-op (web UI has no editable messages)."""
    from app.main import WebTimerEffectsPort

    hub_publish = AsyncMock()

    class FakeHub:
        publish = hub_publish

    port = WebTimerEffectsPort(FakeHub())

    asyncio.get_event_loop().run_until_complete(
        port.edit_timer_line(
            channel_id="ch-1",
            message_id="msg-1",
            replacement="updated text",
        )
    )

    hub_publish.assert_not_awaited()
