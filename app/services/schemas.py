from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field


class CampaignSummary(BaseModel):
    id: str
    namespace: str
    name: str
    actor_id: str
    created_at: datetime


class TurnRequest(BaseModel):
    actor_id: str
    action: str


class TurnResult(BaseModel):
    narration: str
    state_update: dict = Field(default_factory=dict)
    player_state_update: dict = Field(default_factory=dict)
    summary_update: str | None = None
    xp_awarded: int = 0
    image_prompt: str | None = None


class MemorySearchRequest(BaseModel):
    queries: list[str] = Field(default_factory=list)
    category: str | None = None


class MemoryTermsRequest(BaseModel):
    wildcard: str = "*"


class MemoryTurnRequest(BaseModel):
    turn_id: int


class MemoryStoreRequest(BaseModel):
    category: str
    term: str | None = None
    memory: str


class SmsListRequest(BaseModel):
    wildcard: str = "*"


class SmsReadRequest(BaseModel):
    thread: str
    limit: int = 20


class SmsWriteRequest(BaseModel):
    thread: str
    sender: str
    recipient: str
    message: str


class SmsMessage(BaseModel):
    sender: str
    recipient: str
    message: str
    created_at: datetime
