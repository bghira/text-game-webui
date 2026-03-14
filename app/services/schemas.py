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
    reasoning: str | None = None
    dice_result: dict | None = None
    turn_visibility: dict = Field(default_factory=dict)
    notices: list[str] = Field(default_factory=list)
    active_puzzle: dict | None = None
    active_minigame: dict | None = None


class PuzzleAnswerRequest(BaseModel):
    answer: str


class MinigameMoveRequest(BaseModel):
    move: str


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
    viewer_actor_id: str | None = None


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


class CampaignFlagsUpdate(BaseModel):
    guardrails: bool | None = None
    on_rails: bool | None = None
    timed_events: bool | None = None
    difficulty: str | None = None
    speed_multiplier: float | None = None


class SourceMaterialIngest(BaseModel):
    text: str
    document_label: str | None = None
    format: str | None = None
    replace_document: bool = True


class CampaignRuleUpdate(BaseModel):
    key: str
    value: str
    upsert: bool = False


class AttributeSetRequest(BaseModel):
    actor_id: str
    attribute: str
    value: int


class LevelUpRequest(BaseModel):
    actor_id: str


class PersonaUpdateRequest(BaseModel):
    persona: str


class SetupStartRequest(BaseModel):
    actor_id: str | None = None
    on_rails: bool = False
    attachment_text: str | None = None


class SetupMessageRequest(BaseModel):
    actor_id: str
    message: str


class SourceMaterialSearchRequest(BaseModel):
    query: str
    document_key: str | None = None
    top_k: int = 5


class SourceMaterialDigestIngest(BaseModel):
    text: str
    document_label: str
    format: str | None = None
    replace_document: bool = True


class CharacterPortraitRequest(BaseModel):
    character_slug: str
    image_url: str


class ScheduledSmsRequest(BaseModel):
    thread: str
    sender: str
    recipient: str
    message: str
    delay_seconds: int


class ImageSettingsUpdate(BaseModel):
    image_backend: str | None = None
    diffusers_host: str | None = None
    diffusers_port: int | None = None
    diffusers_model: str | None = None
    diffusers_device: str | None = None
    diffusers_dtype: str | None = None
    diffusers_offload: str | None = None
    diffusers_quantization: str | None = None
    diffusers_vae_tiling: bool | None = None
    diffusers_autostart: bool | None = None
    comfyui_url: str | None = None
    comfyui_workflow_json: str | None = None
    image_width: int | None = None
    image_height: int | None = None
    image_steps: int | None = None
    image_guidance_scale: float | None = None
    image_cache_max_memory: int | None = None


class ImageGenerateRequest(BaseModel):
    prompt: str
    model_id: str | None = None
    width: int | None = None
    height: int | None = None
    steps: int | None = None
    guidance_scale: float | None = None
    seed: int = -1
