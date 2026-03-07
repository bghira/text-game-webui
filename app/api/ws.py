from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["ws"])


@router.websocket("/ws/campaigns/{campaign_id}")
async def campaign_socket(campaign_id: str, ws: WebSocket) -> None:
    hub = ws.app.state.realtime
    actor_id = str(ws.query_params.get("actor_id") or "").strip() or None
    session_id = str(ws.query_params.get("session_id") or "").strip() or None
    await hub.connect(campaign_id, ws, actor_id=actor_id, session_id=session_id)
    try:
        while True:
            data = await ws.receive_text()
            await ws.send_json({"type": "ack", "campaign_id": campaign_id, "data": data})
    except WebSocketDisconnect:
        hub.disconnect(campaign_id, ws)
