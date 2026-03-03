from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from fnmatch import fnmatch
from typing import Protocol
from uuid import uuid4

from .schemas import CampaignSummary, MemoryStoreRequest, SmsMessage, TurnRequest, TurnResult


FEATURES = [
    "campaigns",
    "sessions",
    "turns",
    "timers",
    "map",
    "calendar",
    "roster",
    "player_state",
    "media_status",
    "memory_search",
    "memory_terms",
    "memory_turn",
    "memory_store",
    "sms_list",
    "sms_read",
    "sms_write",
    "debug_snapshot",
    "realtime",
]


class EngineGateway(Protocol):
    async def list_campaigns(self, namespace: str) -> list[CampaignSummary]: ...
    async def create_campaign(self, namespace: str, name: str, actor_id: str) -> CampaignSummary: ...
    async def list_sessions(self, campaign_id: str) -> list[dict]: ...
    async def create_or_update_session(
        self,
        campaign_id: str,
        *,
        surface: str,
        surface_key: str,
        surface_guild_id: str | None = None,
        surface_channel_id: str | None = None,
        surface_thread_id: str | None = None,
        enabled: bool = True,
        metadata: dict | None = None,
    ) -> dict: ...
    async def update_session(
        self,
        campaign_id: str,
        session_id: str,
        *,
        enabled: bool | None = None,
        metadata: dict | None = None,
    ) -> dict: ...
    async def runtime_checks(self, probe_llm: bool = False) -> dict: ...
    async def submit_turn(self, campaign_id: str, request: TurnRequest) -> TurnResult: ...
    async def get_map(self, campaign_id: str, actor_id: str) -> str: ...
    async def get_timers(self, campaign_id: str) -> dict: ...
    async def get_calendar(self, campaign_id: str) -> dict: ...
    async def get_roster(self, campaign_id: str) -> dict: ...
    async def upsert_roster_character(
        self,
        campaign_id: str,
        *,
        slug: str,
        name: str | None = None,
        location: str | None = None,
        status: str | None = None,
        player: bool = False,
        fields: dict | None = None,
    ) -> dict: ...
    async def remove_roster_character(self, campaign_id: str, slug: str, *, player: bool = False) -> dict: ...
    async def get_player_state(self, campaign_id: str, actor_id: str) -> dict: ...
    async def get_media(self, campaign_id: str, actor_id: str | None = None) -> dict: ...
    async def accept_pending_avatar(self, campaign_id: str, actor_id: str) -> dict: ...
    async def decline_pending_avatar(self, campaign_id: str, actor_id: str) -> dict: ...
    async def memory_search(self, campaign_id: str, queries: list[str], category: str | None) -> dict: ...
    async def memory_terms(self, campaign_id: str, wildcard: str) -> dict: ...
    async def memory_turn(self, campaign_id: str, turn_id: int) -> dict: ...
    async def memory_store(self, campaign_id: str, payload: MemoryStoreRequest) -> dict: ...
    async def sms_list(self, campaign_id: str, wildcard: str) -> dict: ...
    async def sms_read(self, campaign_id: str, thread: str, limit: int) -> dict: ...
    async def sms_write(self, campaign_id: str, thread: str, sender: str, recipient: str, message: str) -> dict: ...
    async def debug_snapshot(self, campaign_id: str) -> dict: ...


class InMemoryEngineGateway:
    """Development adapter mirroring the text-game-engine surface."""

    def __init__(self) -> None:
        self._campaigns: dict[str, CampaignSummary] = {}
        self._sessions: dict[str, dict[str, dict]] = defaultdict(dict)
        self._turns: dict[str, list[dict]] = defaultdict(list)
        self._timers: dict[str, list[dict]] = defaultdict(list)
        self._memory: dict[str, list[dict]] = defaultdict(list)
        self._sms: dict[str, dict[str, list[SmsMessage]]] = defaultdict(lambda: defaultdict(list))
        self._players: dict[str, dict[str, dict]] = defaultdict(dict)
        self._roster_npcs: dict[str, dict[str, dict]] = defaultdict(dict)
        self._media: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))

    def _require_campaign(self, campaign_id: str) -> CampaignSummary:
        if campaign_id not in self._campaigns:
            raise KeyError(f"Unknown campaign: {campaign_id}")
        return self._campaigns[campaign_id]

    async def list_campaigns(self, namespace: str) -> list[CampaignSummary]:
        return [row for row in self._campaigns.values() if row.namespace == namespace]

    async def create_campaign(self, namespace: str, name: str, actor_id: str) -> CampaignSummary:
        campaign = CampaignSummary(
            id=str(uuid4()),
            namespace=namespace,
            name=name,
            actor_id=actor_id,
            created_at=datetime.now(UTC),
        )
        self._campaigns[campaign.id] = campaign
        self._ensure_player(campaign.id, actor_id)
        return campaign

    def _session_row(self, campaign_id: str, row: dict) -> dict:
        return {
            "id": row.get("id"),
            "campaign_id": campaign_id,
            "surface": row.get("surface"),
            "surface_key": row.get("surface_key"),
            "surface_guild_id": row.get("surface_guild_id"),
            "surface_channel_id": row.get("surface_channel_id"),
            "surface_thread_id": row.get("surface_thread_id"),
            "enabled": bool(row.get("enabled", True)),
            "metadata": row.get("metadata", {}),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }

    async def list_sessions(self, campaign_id: str) -> list[dict]:
        self._require_campaign(campaign_id)
        rows = list(self._sessions[campaign_id].values())
        rows.sort(key=lambda row: str(row.get("created_at") or ""))
        return [self._session_row(campaign_id, row) for row in rows]

    async def create_or_update_session(
        self,
        campaign_id: str,
        *,
        surface: str,
        surface_key: str,
        surface_guild_id: str | None = None,
        surface_channel_id: str | None = None,
        surface_thread_id: str | None = None,
        enabled: bool = True,
        metadata: dict | None = None,
    ) -> dict:
        self._require_campaign(campaign_id)
        now = datetime.now(UTC).isoformat()
        existing = None
        for row in self._sessions[campaign_id].values():
            if row.get("surface_key") == surface_key:
                existing = row
                break
        if existing is None:
            sid = str(uuid4())
            row = {
                "id": sid,
                "surface": surface,
                "surface_key": surface_key,
                "surface_guild_id": surface_guild_id,
                "surface_channel_id": surface_channel_id,
                "surface_thread_id": surface_thread_id,
                "enabled": bool(enabled),
                "metadata": metadata if isinstance(metadata, dict) else {},
                "created_at": now,
                "updated_at": now,
            }
            self._sessions[campaign_id][sid] = row
            return self._session_row(campaign_id, row)

        existing["surface"] = surface
        existing["surface_guild_id"] = surface_guild_id
        existing["surface_channel_id"] = surface_channel_id
        existing["surface_thread_id"] = surface_thread_id
        existing["enabled"] = bool(enabled)
        if isinstance(metadata, dict):
            existing["metadata"] = metadata
        existing["updated_at"] = now
        return self._session_row(campaign_id, existing)

    async def update_session(
        self,
        campaign_id: str,
        session_id: str,
        *,
        enabled: bool | None = None,
        metadata: dict | None = None,
    ) -> dict:
        self._require_campaign(campaign_id)
        row = self._sessions[campaign_id].get(session_id)
        if row is None:
            raise KeyError(f"Unknown session: {session_id}")
        if enabled is not None:
            row["enabled"] = bool(enabled)
        if metadata is not None:
            row["metadata"] = metadata if isinstance(metadata, dict) else {}
        row["updated_at"] = datetime.now(UTC).isoformat()
        return self._session_row(campaign_id, row)

    def _ensure_player(self, campaign_id: str, actor_id: str) -> dict:
        existing = self._players[campaign_id].get(actor_id)
        if existing is not None:
            return existing
        state = {
            "room_title": "Holding Room",
            "room_summary": "You are in a scaffolded test chamber.",
            "location": "holding-room",
            "exits": ["north door", "desk drawer"],
            "inventory": [],
        }
        player = {
            "actor_id": actor_id,
            "level": 1,
            "xp": 0,
            "state": state,
            "last_active_at": datetime.now(UTC).isoformat(),
        }
        self._players[campaign_id][actor_id] = player
        return player

    async def runtime_checks(self, probe_llm: bool = False) -> dict:
        _ = probe_llm
        return {
            "backend": "inmemory",
            "database": {"ok": True, "detail": "In-memory gateway has no external database dependency."},
            "engine": {"ok": True, "detail": "In-memory gateway initialized."},
            "llm": {"configured": False, "probe_attempted": False, "ok": None, "detail": "Not applicable."},
        }

    async def submit_turn(self, campaign_id: str, request: TurnRequest) -> TurnResult:
        self._require_campaign(campaign_id)
        player = self._ensure_player(campaign_id, request.actor_id)
        turn_id = len(self._turns[campaign_id]) + 1
        created_at = datetime.now(UTC)
        self._turns[campaign_id].append(
            {
                "id": turn_id,
                "actor_id": request.actor_id,
                "action": request.action,
                "created_at": created_at.isoformat(),
            }
        )

        action = request.action.strip().lower()
        image_prompt: str | None = None
        if any(token in action for token in ["look", "see", "enter", "approach", "open"]):
            image_prompt = (
                "Interactive fiction scene concept art, grounded lighting, accurate props, "
                "no text overlay"
            )
        if image_prompt:
            self._media[campaign_id]["scene_prompts"].append(
                {
                    "turn_id": turn_id,
                    "actor_id": request.actor_id,
                    "prompt": image_prompt,
                    "status": "requested",
                    "created_at": created_at.isoformat(),
                    "room_key": str(player.get("state", {}).get("location") or "unknown-room"),
                }
            )
        if action.startswith("take "):
            item = request.action.strip()[5:].strip()
            inventory = player["state"].get("inventory")
            if isinstance(inventory, list) and item and item not in inventory:
                inventory.append(item)

        player["xp"] = int(player.get("xp", 0)) + 1
        player["last_active_at"] = created_at.isoformat()
        player_state = player.get("state", {})
        if not isinstance(player_state, dict):
            player_state = {}
            player["state"] = player_state

        return TurnResult(
            narration=f"TURN {turn_id}: {request.actor_id} -> {request.action}",
            player_state_update={
                "room_title": player_state.get("room_title"),
                "room_summary": player_state.get("room_summary"),
                "location": player_state.get("location"),
                "exits": player_state.get("exits", []),
                "inventory": player_state.get("inventory", []),
            },
            state_update={
                "game_time": {"day": 1, "hour": 9, "minute": 15 + min(turn_id, 40)},
                "last_actor": request.actor_id,
            },
            summary_update=f"{request.actor_id} performed action: {request.action}",
            xp_awarded=1,
            image_prompt=image_prompt,
        )

    async def get_map(self, campaign_id: str, actor_id: str) -> str:
        _ = actor_id
        self._require_campaign(campaign_id)
        return """TEST FACILITY
+-----------------------+
| Lobby       Engine Bay|
|   @         [Gateway] |
+-----------------------+
Legend: @ current player
"""

    async def get_timers(self, campaign_id: str) -> dict:
        self._require_campaign(campaign_id)
        return {"timers": self._timers[campaign_id][-30:]}

    async def get_calendar(self, campaign_id: str) -> dict:
        self._require_campaign(campaign_id)
        return {
            "game_time": {"day": 1, "hour": 9, "minute": 0},
            "events": [
                {
                    "title": "Concierge callback",
                    "game_day": 1,
                    "hour": 11,
                    "minute": 30,
                    "scope": "local",
                }
            ],
        }

    async def get_roster(self, campaign_id: str) -> dict:
        campaign = self._require_campaign(campaign_id)
        rows = []
        for actor_id, row in sorted(self._players[campaign_id].items()):
            state = row.get("state", {}) if isinstance(row, dict) else {}
            rows.append(
                {
                    "slug": actor_id,
                    "name": state.get("character_name") or actor_id.replace("-", " ").title(),
                    "location": state.get("location", "Lobby"),
                    "status": state.get("current_status") or "active",
                    "player": True,
                }
            )
        for slug, payload in sorted(self._roster_npcs[campaign_id].items()):
            rows.append(
                {
                    "slug": slug,
                    "name": payload.get("name") or slug,
                    "location": payload.get("location") or "unknown",
                    "status": payload.get("current_status") or "active",
                    "player": False,
                }
            )
        if not rows:
            rows.append(
                {
                    "slug": campaign.actor_id,
                    "name": campaign.actor_id.replace("-", " ").title(),
                    "location": "Lobby",
                    "status": "active",
                    "player": True,
                }
            )
        return {"characters": rows}

    async def upsert_roster_character(
        self,
        campaign_id: str,
        *,
        slug: str,
        name: str | None = None,
        location: str | None = None,
        status: str | None = None,
        player: bool = False,
        fields: dict | None = None,
    ) -> dict:
        self._require_campaign(campaign_id)
        slug_clean = str(slug or "").strip()
        if not slug_clean:
            raise ValueError("slug is required")
        fields_dict = fields if isinstance(fields, dict) else {}

        is_player = bool(player) or slug_clean in self._players[campaign_id]
        if is_player:
            prow = self._ensure_player(campaign_id, slug_clean)
            pstate = prow.get("state", {})
            if not isinstance(pstate, dict):
                pstate = {}
                prow["state"] = pstate
            if isinstance(name, str) and name.strip():
                pstate["character_name"] = name.strip()
            if isinstance(location, str) and location.strip():
                pstate["location"] = location.strip()
            if isinstance(status, str) and status.strip():
                pstate["current_status"] = status.strip()
            for key, value in fields_dict.items():
                if key in {"name", "slug"}:
                    continue
                pstate[key] = value
            return {
                "ok": True,
                "character": {
                    "slug": slug_clean,
                    "name": pstate.get("character_name") or slug_clean,
                    "location": pstate.get("location") or "unknown",
                    "status": pstate.get("current_status") or "active",
                    "player": True,
                },
            }

        current = self._roster_npcs[campaign_id].get(slug_clean, {})
        if not isinstance(current, dict):
            current = {}
        updated = dict(current)
        updated.update(fields_dict)
        if isinstance(name, str) and name.strip():
            updated["name"] = name.strip()
        if isinstance(location, str) and location.strip():
            updated["location"] = location.strip()
        if isinstance(status, str) and status.strip():
            updated["current_status"] = status.strip()
        self._roster_npcs[campaign_id][slug_clean] = updated
        return {
            "ok": True,
            "character": {
                "slug": slug_clean,
                "name": updated.get("name") or slug_clean,
                "location": updated.get("location") or "unknown",
                "status": updated.get("current_status") or "active",
                "player": False,
            },
        }

    async def remove_roster_character(self, campaign_id: str, slug: str, *, player: bool = False) -> dict:
        campaign = self._require_campaign(campaign_id)
        slug_clean = str(slug or "").strip()
        if not slug_clean:
            raise ValueError("slug is required")
        if slug_clean == campaign.actor_id:
            return {"ok": False, "removed": False, "slug": slug_clean, "message": "Cannot remove lead actor."}

        if bool(player):
            removed = self._players[campaign_id].pop(slug_clean, None)
            return {"ok": removed is not None, "removed": removed is not None, "slug": slug_clean, "player": True}

        removed_npc = self._roster_npcs[campaign_id].pop(slug_clean, None)
        if removed_npc is not None:
            return {"ok": True, "removed": True, "slug": slug_clean, "player": False}
        if slug_clean in self._players[campaign_id]:
            return {
                "ok": False,
                "removed": False,
                "slug": slug_clean,
                "player": True,
                "message": "Target is a player. Set player=true to remove player entries.",
            }
        return {"ok": False, "removed": False, "slug": slug_clean, "player": False}

    async def get_player_state(self, campaign_id: str, actor_id: str) -> dict:
        self._require_campaign(campaign_id)
        player = self._players[campaign_id].get(actor_id)
        if player is None:
            raise KeyError(f"Unknown player in campaign: {actor_id}")
        state = player.get("state", {})
        if not isinstance(state, dict):
            state = {}
        inventory = state.get("inventory", [])
        if not isinstance(inventory, list):
            inventory = []
        return {
            "actor_id": actor_id,
            "level": int(player.get("level", 1)),
            "xp": int(player.get("xp", 0)),
            "last_active_at": player.get("last_active_at"),
            "state": state,
            "inventory": inventory,
        }

    async def get_media(self, campaign_id: str, actor_id: str | None = None) -> dict:
        self._require_campaign(campaign_id)
        scene_prompts = self._media[campaign_id].get("scene_prompts", [])
        if actor_id:
            scene_prompts = [row for row in scene_prompts if row.get("actor_id") == actor_id]
        scene_prompts = scene_prompts[-20:]

        avatars = []
        for aid, player in self._players[campaign_id].items():
            if actor_id and aid != actor_id:
                continue
            state = player.get("state", {}) if isinstance(player, dict) else {}
            avatars.append(
                {
                    "actor_id": aid,
                    "avatar_url": state.get("avatar_url"),
                    "pending_avatar_url": state.get("pending_avatar_url"),
                    "pending_avatar_prompt": state.get("pending_avatar_prompt"),
                }
            )

        latest_prompt = scene_prompts[-1] if scene_prompts else {}
        return {
            "scene": {
                "latest_prompt": latest_prompt.get("prompt"),
                "latest_turn_id": latest_prompt.get("turn_id"),
                "latest_at": latest_prompt.get("created_at"),
                "request_count": len(scene_prompts),
                "requests": scene_prompts,
            },
            "avatars": avatars,
        }

    async def accept_pending_avatar(self, campaign_id: str, actor_id: str) -> dict:
        self._require_campaign(campaign_id)
        player = self._players[campaign_id].get(actor_id)
        if player is None:
            raise KeyError(f"Unknown player in campaign: {actor_id}")
        state = player.get("state", {})
        if not isinstance(state, dict):
            state = {}
            player["state"] = state
        pending = state.get("pending_avatar_url")
        if not isinstance(pending, str) or not pending.strip():
            return {"ok": False, "message": "No pending avatar to accept.", "actor_id": actor_id}
        state["avatar_url"] = pending.strip()
        state.pop("pending_avatar_url", None)
        state.pop("pending_avatar_prompt", None)
        state.pop("pending_avatar_generated_at", None)
        return {"ok": True, "message": f"Avatar accepted: {state.get('avatar_url')}", "actor_id": actor_id}

    async def decline_pending_avatar(self, campaign_id: str, actor_id: str) -> dict:
        self._require_campaign(campaign_id)
        player = self._players[campaign_id].get(actor_id)
        if player is None:
            raise KeyError(f"Unknown player in campaign: {actor_id}")
        state = player.get("state", {})
        if not isinstance(state, dict):
            state = {}
            player["state"] = state
        had_pending = bool(state.get("pending_avatar_url"))
        state.pop("pending_avatar_url", None)
        state.pop("pending_avatar_prompt", None)
        state.pop("pending_avatar_generated_at", None)
        if had_pending:
            return {"ok": True, "message": "Pending avatar discarded.", "actor_id": actor_id}
        return {"ok": False, "message": "No pending avatar to discard.", "actor_id": actor_id}

    async def memory_search(self, campaign_id: str, queries: list[str], category: str | None) -> dict:
        self._require_campaign(campaign_id)
        hits = []
        lowered = [q.lower() for q in queries]
        for row in self._memory[campaign_id]:
            if category and row.get("category") != category:
                continue
            hay = row.get("memory", "").lower()
            if not lowered or any(q in hay for q in lowered):
                hits.append(row)
        return {"hits": hits[:10]}

    async def memory_terms(self, campaign_id: str, wildcard: str) -> dict:
        self._require_campaign(campaign_id)
        terms = sorted({row.get("term") for row in self._memory[campaign_id] if row.get("term")})
        if wildcard and wildcard != "*":
            terms = [t for t in terms if t and fnmatch(t, wildcard)]
        return {"terms": terms}

    async def memory_turn(self, campaign_id: str, turn_id: int) -> dict:
        self._require_campaign(campaign_id)
        for row in self._turns[campaign_id]:
            if row["id"] == turn_id:
                return {"turn": row}
        return {"turn": None}

    async def memory_store(self, campaign_id: str, payload: MemoryStoreRequest) -> dict:
        self._require_campaign(campaign_id)
        row = {
            "id": len(self._memory[campaign_id]) + 1,
            "category": payload.category,
            "term": payload.term,
            "memory": payload.memory,
            "created_at": datetime.now(UTC).isoformat(),
        }
        self._memory[campaign_id].append(row)
        return {"stored": True, "entry": row}

    async def sms_list(self, campaign_id: str, wildcard: str) -> dict:
        self._require_campaign(campaign_id)
        threads = sorted(self._sms[campaign_id].keys())
        if wildcard and wildcard != "*":
            threads = [thread for thread in threads if fnmatch(thread, wildcard)]
        return {"threads": threads}

    async def sms_read(self, campaign_id: str, thread: str, limit: int) -> dict:
        self._require_campaign(campaign_id)
        msgs = self._sms[campaign_id].get(thread, [])
        return {"thread": thread, "messages": [m.model_dump() for m in msgs[-limit:]]}

    async def sms_write(self, campaign_id: str, thread: str, sender: str, recipient: str, message: str) -> dict:
        self._require_campaign(campaign_id)
        msg = SmsMessage(sender=sender, recipient=recipient, message=message, created_at=datetime.now(UTC))
        self._sms[campaign_id][thread].append(msg)
        return {"stored": True, "thread": thread, "message": msg.model_dump()}

    async def debug_snapshot(self, campaign_id: str) -> dict:
        self._require_campaign(campaign_id)
        return {
            "sessions": list(self._sessions[campaign_id].values()),
            "turns": self._turns[campaign_id][-30:],
            "players": self._players[campaign_id],
            "media": self._media[campaign_id],
            "memory": self._memory[campaign_id][-30:],
            "sms": {
                thread: [msg.model_dump() for msg in rows[-20:]]
                for thread, rows in self._sms[campaign_id].items()
            },
        }
