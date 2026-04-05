from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import Request, WebSocket


LINK_PENDING_COOKIE = "dtm_link_code"
LINK_SESSION_COOKIE = "dtm_link_session"
LINK_CONFIRM_HEADER = "X-DTM-Link-Secret"
LINK_CODE_TTL_SECONDS = 60 * 60 * 12
LINK_SESSION_TTL_SECONDS = 60 * 60 * 24 * 30


@dataclass(frozen=True)
class LinkedActor:
    actor_id: str
    display_name: str
    issued_at: int


def dtm_link_enabled(settings: Any) -> bool:
    return bool(getattr(settings, "dtm_link_auth_enabled", False))


def _secret_bytes(settings: Any) -> bytes:
    return str(getattr(settings, "dtm_link_secret", "") or "").encode("utf-8")


def _urlsafe_b64encode_text(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


def _urlsafe_b64decode_text(text: str) -> str:
    padded = text + "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")


def _sign(settings: Any, payload_b64: str) -> str:
    return hmac.new(_secret_bytes(settings), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()


def issue_session_cookie_value(settings: Any, *, actor_id: str, display_name: str = "") -> str:
    payload = {
        "actor_id": str(actor_id or "").strip(),
        "display_name": str(display_name or "").strip(),
        "issued_at": int(time.time()),
    }
    payload_b64 = _urlsafe_b64encode_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=True))
    return f"{payload_b64}.{_sign(settings, payload_b64)}"


def decode_session_cookie_value(settings: Any, raw_value: str | None) -> LinkedActor | None:
    text = str(raw_value or "").strip()
    if not text or "." not in text:
        return None
    payload_b64, signature = text.rsplit(".", 1)
    expected = _sign(settings, payload_b64)
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        payload = json.loads(_urlsafe_b64decode_text(payload_b64))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    actor_id = str(payload.get("actor_id") or "").strip()
    if not actor_id:
        return None
    issued_at = int(payload.get("issued_at") or 0)
    now = int(time.time())
    if issued_at <= 0 or (issued_at + LINK_SESSION_TTL_SECONDS) < now:
        return None
    return LinkedActor(
        actor_id=actor_id,
        display_name=str(payload.get("display_name") or "").strip(),
        issued_at=issued_at,
    )


def get_linked_actor_from_request(request: Request) -> LinkedActor | None:
    settings = request.app.state.settings
    if not dtm_link_enabled(settings):
        return None
    return decode_session_cookie_value(settings, request.cookies.get(LINK_SESSION_COOKIE))


def get_linked_actor_from_websocket(ws: WebSocket) -> LinkedActor | None:
    settings = ws.app.state.settings
    if not dtm_link_enabled(settings):
        return None
    return decode_session_cookie_value(settings, ws.cookies.get(LINK_SESSION_COOKIE))


def ensure_pending_links_store(app: Any) -> dict[str, dict[str, Any]]:
    store = getattr(app.state, "dtm_pending_links", None)
    if isinstance(store, dict):
        return store
    store = {}
    app.state.dtm_pending_links = store
    return store


def prune_pending_links(app: Any) -> None:
    now = int(time.time())
    store = ensure_pending_links_store(app)
    stale = [
        code
        for code, row in store.items()
        if not isinstance(row, dict)
        or int(row.get("created_at") or 0) <= 0
        or int(row.get("created_at") or 0) + LINK_CODE_TTL_SECONDS < now
    ]
    for code in stale:
        store.pop(code, None)


def get_or_create_pending_link(app: Any, code: str | None = None) -> dict[str, Any]:
    prune_pending_links(app)
    store = ensure_pending_links_store(app)
    normalized = str(code or "").strip()
    row = store.get(normalized)
    if isinstance(row, dict):
        return row
    new_code = str(uuid.uuid4())
    row = {
        "code": new_code,
        "created_at": int(time.time()),
        "actor_id": None,
        "display_name": None,
        "confirmed_at": None,
    }
    store[new_code] = row
    return row


def confirm_pending_link(app: Any, *, code: str, actor_id: str, display_name: str = "") -> dict[str, Any] | None:
    prune_pending_links(app)
    store = ensure_pending_links_store(app)
    normalized = str(code or "").strip()
    row = store.get(normalized)
    if not isinstance(row, dict):
        return None
    row["actor_id"] = str(actor_id or "").strip()
    row["display_name"] = str(display_name or "").strip()
    row["confirmed_at"] = int(time.time())
    return row

