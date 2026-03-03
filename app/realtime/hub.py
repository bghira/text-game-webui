from __future__ import annotations

from collections import defaultdict
from fastapi import WebSocket


class RealtimeHub:
    def __init__(self) -> None:
        self._subs: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, campaign_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._subs[campaign_id].add(ws)

    def disconnect(self, campaign_id: str, ws: WebSocket) -> None:
        self._subs[campaign_id].discard(ws)

    async def publish(self, campaign_id: str, payload: dict) -> None:
        for ws in list(self._subs[campaign_id]):
            try:
                await ws.send_json(payload)
            except Exception:
                self._subs[campaign_id].discard(ws)
