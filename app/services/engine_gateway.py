from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from fnmatch import fnmatch
from typing import Protocol
from uuid import uuid4

from .schemas import CampaignSummary, MemoryStoreRequest, SmsMessage, TurnRequest, TurnResult


FEATURES = [
    "campaigns",
    "turns",
    "map",
    "calendar",
    "roster",
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
    async def submit_turn(self, campaign_id: str, request: TurnRequest) -> TurnResult: ...
    async def get_map(self, campaign_id: str, actor_id: str) -> str: ...
    async def get_calendar(self, campaign_id: str) -> dict: ...
    async def get_roster(self, campaign_id: str) -> dict: ...
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
        self._turns: dict[str, list[dict]] = defaultdict(list)
        self._memory: dict[str, list[dict]] = defaultdict(list)
        self._sms: dict[str, dict[str, list[SmsMessage]]] = defaultdict(lambda: defaultdict(list))

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
            created_at=datetime.utcnow(),
        )
        self._campaigns[campaign.id] = campaign
        return campaign

    async def submit_turn(self, campaign_id: str, request: TurnRequest) -> TurnResult:
        self._require_campaign(campaign_id)
        turn_id = len(self._turns[campaign_id]) + 1
        created_at = datetime.utcnow()
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

        return TurnResult(
            narration=f"TURN {turn_id}: {request.actor_id} -> {request.action}",
            player_state_update={"room_summary": "You are in a scaffolded test chamber."},
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
        return {
            "characters": [
                {
                    "slug": campaign.actor_id,
                    "name": campaign.actor_id.replace("-", " ").title(),
                    "location": "Lobby",
                    "status": "active",
                }
            ]
        }

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
            "created_at": datetime.utcnow().isoformat(),
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
        msg = SmsMessage(sender=sender, recipient=recipient, message=message, created_at=datetime.utcnow())
        self._sms[campaign_id][thread].append(msg)
        return {"stored": True, "thread": thread, "message": msg.model_dump()}

    async def debug_snapshot(self, campaign_id: str) -> dict:
        self._require_campaign(campaign_id)
        return {
            "turns": self._turns[campaign_id][-30:],
            "memory": self._memory[campaign_id][-30:],
            "sms": {
                thread: [msg.model_dump() for msg in rows[-20:]]
                for thread, rows in self._sms[campaign_id].items()
            },
        }
