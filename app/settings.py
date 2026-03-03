from __future__ import annotations

import os
from pydantic import BaseModel, Field


class Settings(BaseModel):
    app_name: str = Field(default_factory=lambda: os.getenv("TEXT_GAME_WEBUI_APP_NAME", "text-game-webui"))
    debug: bool = Field(default_factory=lambda: os.getenv("TEXT_GAME_WEBUI_DEBUG", "1") in {"1", "true", "True"})
    host: str = Field(default_factory=lambda: os.getenv("TEXT_GAME_WEBUI_HOST", "0.0.0.0"))
    port: int = Field(default_factory=lambda: int(os.getenv("TEXT_GAME_WEBUI_PORT", "8080")))
    attention_window_seconds: int = Field(
        default_factory=lambda: int(os.getenv("TEXT_GAME_WEBUI_ATTENTION_WINDOW_SECONDS", "600"))
    )

    gateway_backend: str = Field(default_factory=lambda: os.getenv("TEXT_GAME_WEBUI_GATEWAY_BACKEND", "inmemory"))
    tge_database_url: str = Field(
        default_factory=lambda: os.getenv(
            "TEXT_GAME_WEBUI_TGE_DATABASE_URL",
            "sqlite+pysqlite:///./text-game-webui.db",
        )
    )
    tge_completion_mode: str = Field(
        default_factory=lambda: os.getenv("TEXT_GAME_WEBUI_TGE_COMPLETION_MODE", "deterministic")
    )
    tge_llm_base_url: str = Field(
        default_factory=lambda: os.getenv("TEXT_GAME_WEBUI_TGE_LLM_BASE_URL", "http://127.0.0.1:1234/v1")
    )
    tge_llm_api_key: str = Field(default_factory=lambda: os.getenv("TEXT_GAME_WEBUI_TGE_LLM_API_KEY", "sk-local"))
    tge_llm_model: str = Field(default_factory=lambda: os.getenv("TEXT_GAME_WEBUI_TGE_LLM_MODEL", "local-model"))
    tge_llm_timeout_seconds: int = Field(
        default_factory=lambda: int(os.getenv("TEXT_GAME_WEBUI_TGE_LLM_TIMEOUT_SECONDS", "90"))
    )
    tge_llm_temperature: float = Field(
        default_factory=lambda: float(os.getenv("TEXT_GAME_WEBUI_TGE_LLM_TEMPERATURE", "0.8"))
    )
    tge_llm_max_tokens: int = Field(
        default_factory=lambda: int(os.getenv("TEXT_GAME_WEBUI_TGE_LLM_MAX_TOKENS", "3200"))
    )
    tge_runtime_probe_llm: bool = Field(
        default_factory=lambda: os.getenv("TEXT_GAME_WEBUI_TGE_RUNTIME_PROBE_LLM", "0") in {"1", "true", "True"}
    )
    tge_runtime_probe_timeout_seconds: int = Field(
        default_factory=lambda: int(os.getenv("TEXT_GAME_WEBUI_TGE_RUNTIME_PROBE_TIMEOUT_SECONDS", "8"))
    )
