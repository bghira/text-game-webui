from __future__ import annotations

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.services.dtm_link_auth import dtm_link_enabled, get_linked_actor_from_websocket

router = APIRouter(tags=["ws"])


@router.websocket("/ws/campaigns/{campaign_id}")
async def campaign_socket(campaign_id: str, ws: WebSocket) -> None:
    hub = ws.app.state.realtime
    gateway = ws.app.state.gateway
    actor_id = str(ws.query_params.get("actor_id") or "").strip() or None
    session_id = str(ws.query_params.get("session_id") or "").strip() or None
    if dtm_link_enabled(ws.app.state.settings):
        linked = get_linked_actor_from_websocket(ws)
        if linked is None:
            await ws.close(code=1008, reason="Discord account link required.")
            return
        try:
            allowed = await gateway.actor_can_access_campaign(campaign_id, linked.actor_id)
        except KeyError as err:
            await ws.close(code=1008, reason=str(err)[:120])
            return
        if not allowed:
            await ws.close(code=1008, reason="Campaign is not linked to your Discord account.")
            return
        actor_id = linked.actor_id
    try:
        await gateway.validate_realtime_subscription(
            campaign_id,
            actor_id=actor_id,
            session_id=session_id,
        )
    except (KeyError, ValueError) as err:
        await ws.close(code=1008, reason=str(err)[:120])
        return
    await hub.connect(campaign_id, ws, actor_id=actor_id, session_id=session_id)
    try:
        while True:
            data = await ws.receive_text()
            try:
                payload = json.loads(data)
            except Exception:
                payload = None
            if isinstance(payload, dict):
                msg_type = str(payload.get("type") or "").strip().lower()
                if msg_type == "browser_llm_result" and hasattr(gateway, "handle_browser_llm_result"):
                    await gateway.handle_browser_llm_result(payload)
                    continue
            await ws.send_json({"type": "ack", "campaign_id": campaign_id, "data": data})
    except WebSocketDisconnect:
        hub.disconnect(campaign_id, ws)
