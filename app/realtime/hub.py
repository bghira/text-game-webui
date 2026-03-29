from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from fastapi import WebSocket


@dataclass(frozen=True)
class RealtimeSubscription:
    ws: WebSocket
    actor_id: str | None = None
    session_id: str | None = None


class RealtimeHub:
    # Event types that carry session/actor scope and must honour visibility rules.
    _SESSION_SCOPED_TYPES: frozenset[str] = frozenset(
        {
            "turn",
            "media",
            "timers",
            "turn_progress",
            "pending_shared_turn",
            "pending_shared_turn_clear",
        }
    )

    def __init__(self) -> None:
        self._subs: dict[str, set[RealtimeSubscription]] = defaultdict(set)

    async def connect(
        self,
        campaign_id: str,
        ws: WebSocket,
        *,
        actor_id: str | None = None,
        session_id: str | None = None,
    ) -> None:
        await ws.accept()
        self._subs[campaign_id].add(
            RealtimeSubscription(
                ws=ws,
                actor_id=str(actor_id or "").strip() or None,
                session_id=str(session_id or "").strip() or None,
            )
        )

    def disconnect(self, campaign_id: str, ws: WebSocket) -> None:
        stale = {sub for sub in self._subs[campaign_id] if sub.ws is ws}
        for sub in stale:
            self._subs[campaign_id].discard(sub)

    @staticmethod
    def _session_id_for_event(payload: dict) -> str | None:
        top_level = str(payload.get("session_id") or "").strip() or None
        if top_level:
            return top_level
        body = payload.get("payload")
        if isinstance(body, dict):
            return str(body.get("session_id") or "").strip() or None
        return None

    @staticmethod
    def _actor_id_for_event(payload: dict) -> str | None:
        top_level = str(payload.get("actor_id") or "").strip() or None
        if top_level:
            return top_level
        body = payload.get("payload")
        if isinstance(body, dict):
            return str(body.get("actor_id") or "").strip() or None
        return None

    @staticmethod
    def _turn_visibility_for_event(payload: dict) -> dict | None:
        body = payload.get("payload")
        if not isinstance(body, dict):
            return None
        visibility = body.get("turn_visibility")
        return visibility if isinstance(visibility, dict) else None

    @classmethod
    def _event_visible_to_subscription(cls, sub: RealtimeSubscription, payload: dict) -> bool:
        payload_type = str(payload.get("type") or "").strip().lower()
        event_session_id = cls._session_id_for_event(payload)
        session_mismatch = False
        if sub.session_id:
            if event_session_id is not None and event_session_id != sub.session_id:
                session_mismatch = True
        elif event_session_id is not None and payload_type in cls._SESSION_SCOPED_TYPES:
            return False

        if payload_type not in cls._SESSION_SCOPED_TYPES:
            return True

        if payload_type == "turn_progress":
            if session_mismatch:
                return False
            event_actor_id = cls._actor_id_for_event(payload)
            if not event_actor_id or not sub.actor_id:
                return False
            return sub.actor_id == event_actor_id

        visibility = cls._turn_visibility_for_event(payload)
        if not isinstance(visibility, dict):
            return True
        scope = str(visibility.get("scope") or "public").strip().lower()
        if scope in {"", "public"}:
            return True
        if not sub.actor_id:
            return False
        event_actor_id = cls._actor_id_for_event(payload)
        if event_actor_id and sub.actor_id == event_actor_id:
            return True
        raw_actor_ids = visibility.get("visible_actor_ids")
        if isinstance(raw_actor_ids, list):
            allowed = {str(item or "").strip() for item in raw_actor_ids if str(item or "").strip()}
            if sub.actor_id in allowed:
                return True
        if session_mismatch:
            return False
        if scope == "local":
            return False
        return False

    async def publish(self, campaign_id: str, payload: dict) -> None:
        for sub in list(self._subs[campaign_id]):
            if not self._event_visible_to_subscription(sub, payload):
                continue
            try:
                await sub.ws.send_json(payload)
            except Exception:
                self._subs[campaign_id].discard(sub)

    def campaigns_for_actor(self, actor_id: str) -> list[str]:
        """Return a stable list of campaign IDs where *actor_id* has a subscription."""
        return [
            cid
            for cid, subs in list(self._subs.items())
            if any(sub.actor_id == actor_id for sub in subs)
        ]

    def has_actor_subscription(self, campaign_id: str, actor_id: str) -> bool:
        wanted_campaign = str(campaign_id or "").strip()
        wanted_actor = str(actor_id or "").strip()
        if not wanted_campaign or not wanted_actor:
            return False
        return any(sub.actor_id == wanted_actor for sub in list(self._subs[wanted_campaign]))

    async def publish_to_actor(self, campaign_id: str, actor_id: str, payload: dict) -> None:
        """Send a message only to subscriptions matching a specific actor_id."""
        for sub in list(self._subs[campaign_id]):
            if sub.actor_id != actor_id:
                continue
            try:
                await sub.ws.send_json(payload)
            except Exception:
                self._subs[campaign_id].discard(sub)
