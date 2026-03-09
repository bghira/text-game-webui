from __future__ import annotations

from datetime import datetime
from typing import Any

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
    session_id: str | None = None


class SessionCreateRequest(BaseModel):
    surface: str
    surface_key: str
    surface_guild_id: str | None = None
    surface_channel_id: str | None = None
    surface_thread_id: str | None = None
    enabled: bool = True
    metadata: dict = Field(default_factory=dict)


class SessionUpdateRequest(BaseModel):
    enabled: bool | None = None
    metadata: dict | None = None


class AvatarActionRequest(BaseModel):
    actor_id: str


class RosterUpsertRequest(BaseModel):
    slug: str
    name: str | None = None
    location: str | None = None
    status: str | None = None
    player: bool = False
    fields: dict = Field(default_factory=dict)


class RosterRemoveRequest(BaseModel):
    slug: str
    player: bool = False


class TurnResult(BaseModel):
    actor_id: str | None = None
    session_id: str | None = None
    narration: str
    state_update: dict = Field(default_factory=dict)
    player_state_update: dict = Field(default_factory=dict)
    summary_update: str | None = None
    xp_awarded: int = 0
    image_prompt: str | None = None
    turn_visibility: dict = Field(default_factory=dict)
    notices: list[str] = Field(default_factory=list)


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


class LLMSettingsUpdate(BaseModel):
    completion_mode: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    timeout_seconds: int | None = None
    keep_alive: str | None = None
    ollama_options: dict[str, Any] | None = None
