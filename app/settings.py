from __future__ import annotations

import json
import os
import re
import sqlite3
from pydantic import BaseModel, Field, field_validator


# Keys that can be persisted to the webui_kv table.
_PERSISTABLE_KEYS = frozenset({
    "theme",
    "tge_completion_mode",
    "tge_llm_base_url",
    "tge_llm_api_key",
    "tge_llm_model",
    "tge_llm_temperature",
    "tge_llm_max_tokens",
    "tge_llm_timeout_seconds",
    "tge_ollama_keep_alive",
    "tge_ollama_options_json",
    # Image generation settings
    "image_backend",
    "diffusers_host",
    "diffusers_port",
    "diffusers_model",
    "diffusers_device",
    "diffusers_dtype",
    "diffusers_offload",
    "diffusers_quantization",
    "diffusers_vae_tiling",
    "diffusers_autostart",
    "comfyui_url",
    "comfyui_workflow_json",
    "image_width",
    "image_height",
    "image_steps",
    "image_guidance_scale",
    "image_cache_max_entries",
})

_SYNC_LOCKED_TGE_KEYS = frozenset({
    "tge_completion_mode",
    "tge_llm_base_url",
    "tge_llm_api_key",
    "tge_llm_model",
    "tge_llm_temperature",
    "tge_llm_max_tokens",
    "tge_llm_timeout_seconds",
    "tge_ollama_keep_alive",
    "tge_ollama_options_json",
})


def _sqlite_path_from_url(database_url: str) -> str | None:
    """Extract the filesystem path from a SQLAlchemy SQLite URL."""
    m = re.match(r"sqlite(?:\+\w+)?:///(.+)", database_url)
    return m.group(1) if m else None


def _ensure_kv_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS webui_kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    conn.commit()


def load_persisted_settings(settings: Settings) -> None:
    """Override settings with values persisted in the webui_kv table."""
    db_path = _sqlite_path_from_url(settings.tge_database_url)
    if not db_path:
        return
    try:
        conn = sqlite3.connect(db_path)
        _ensure_kv_table(conn)
        rows = conn.execute("SELECT key, value FROM webui_kv").fetchall()
        conn.close()
    except Exception:
        return
    for key, value in rows:
        if key not in _PERSISTABLE_KEYS:
            continue
        if settings.tge_sync_with_dtm and key in _SYNC_LOCKED_TGE_KEYS:
            continue
        field_info = Settings.model_fields.get(key)
        if field_info is None:
            continue
        try:
            annotation = field_info.annotation
            # Resolve the actual type, handling Optional / defaults
            if annotation is float:
                setattr(settings, key, float(value))
            elif annotation is int:
                setattr(settings, key, int(value))
            elif annotation is bool:
                setattr(settings, key, value in {"1", "true", "True"})
            else:
                setattr(settings, key, value)
        except (ValueError, TypeError):
            continue


def persist_settings(settings: Settings) -> None:
    """Write persistable settings to the webui_kv table."""
    db_path = _sqlite_path_from_url(settings.tge_database_url)
    if not db_path:
        return
    try:
        conn = sqlite3.connect(db_path)
        _ensure_kv_table(conn)
        for key in _PERSISTABLE_KEYS:
            if settings.tge_sync_with_dtm and key in _SYNC_LOCKED_TGE_KEYS:
                continue
            value = getattr(settings, key, None)
            if value is None:
                continue
            conn.execute(
                "INSERT INTO webui_kv (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)),
            )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _default_tge_model() -> str:
    explicit = str(os.getenv("TEXT_GAME_WEBUI_TGE_LLM_MODEL", "")).strip()
    if explicit:
        return explicit
    mode = str(os.getenv("TEXT_GAME_WEBUI_TGE_COMPLETION_MODE", "ollama") or "").strip().lower()
    if mode == "zai":
        return "glm-5.1"
    return "local-model"


class Settings(BaseModel):
    theme: str = Field(default_factory=lambda: os.getenv("TEXT_GAME_WEBUI_THEME", "light"))
    app_name: str = Field(default_factory=lambda: os.getenv("TEXT_GAME_WEBUI_APP_NAME", "text-game-webui"))
    debug: bool = Field(default_factory=lambda: os.getenv("TEXT_GAME_WEBUI_DEBUG", "1") in {"1", "true", "True"})
    host: str = Field(default_factory=lambda: os.getenv("TEXT_GAME_WEBUI_HOST", "0.0.0.0"))
    port: int = Field(default_factory=lambda: int(os.getenv("TEXT_GAME_WEBUI_PORT", "8080")))
    attention_window_seconds: int = Field(
        default_factory=lambda: int(os.getenv("TEXT_GAME_WEBUI_ATTENTION_WINDOW_SECONDS", "600"))
    )

    gateway_backend: str = Field(default_factory=lambda: os.getenv("TEXT_GAME_WEBUI_GATEWAY_BACKEND", "tge"))
    tge_database_url: str = Field(
        default_factory=lambda: os.getenv(
            "TEXT_GAME_WEBUI_TGE_DATABASE_URL",
            "sqlite+pysqlite:///./text-game-webui.db",
        )
    )
    tge_completion_mode: str = Field(
        default_factory=lambda: os.getenv("TEXT_GAME_WEBUI_TGE_COMPLETION_MODE", "ollama")
    )
    tge_llm_base_url: str = Field(
        default_factory=lambda: os.getenv("TEXT_GAME_WEBUI_TGE_LLM_BASE_URL", "http://127.0.0.1:11434")
    )
    tge_llm_api_key: str = Field(default_factory=lambda: os.getenv("TEXT_GAME_WEBUI_TGE_LLM_API_KEY", "sk-local"))
    tge_llm_model: str = Field(default_factory=_default_tge_model)
    tge_llm_timeout_seconds: int = Field(
        default_factory=lambda: int(os.getenv("TEXT_GAME_WEBUI_TGE_LLM_TIMEOUT_SECONDS", "90"))
    )
    tge_llm_temperature: float = Field(
        default_factory=lambda: float(os.getenv("TEXT_GAME_WEBUI_TGE_LLM_TEMPERATURE", "0.8"))
    )
    tge_llm_max_tokens: int = Field(
        default_factory=lambda: int(os.getenv("TEXT_GAME_WEBUI_TGE_LLM_MAX_TOKENS", "3200"))
    )
    tge_ollama_keep_alive: str = Field(
        default_factory=lambda: os.getenv("TEXT_GAME_WEBUI_TGE_OLLAMA_KEEP_ALIVE", "30m")
    )
    tge_ollama_options_json: str = Field(
        default_factory=lambda: os.getenv("TEXT_GAME_WEBUI_TGE_OLLAMA_OPTIONS_JSON", "{}")
    )
    tge_runtime_probe_llm: bool = Field(
        default_factory=lambda: os.getenv("TEXT_GAME_WEBUI_TGE_RUNTIME_PROBE_LLM", "0") in {"1", "true", "True"}
    )
    tge_sync_with_dtm: bool = Field(
        default_factory=lambda: os.getenv("TEXT_GAME_WEBUI_TGE_SYNC_WITH_DTM", "0") in {"1", "true", "True"}
    )
    tge_runtime_probe_timeout_seconds: int = Field(
        default_factory=lambda: int(os.getenv("TEXT_GAME_WEBUI_TGE_RUNTIME_PROBE_TIMEOUT_SECONDS", "8"))
    )
    dtm_link_auth_enabled: bool = Field(
        default_factory=lambda: os.getenv("TEXT_GAME_WEBUI_DTM_LINK_AUTH", "0") in {"1", "true", "True"}
    )
    dtm_link_secret: str = Field(
        default_factory=lambda: os.getenv("TEXT_GAME_WEBUI_DTM_LINK_SECRET", "")
    )
    dtm_command_prefix: str = Field(
        default_factory=lambda: os.getenv("TEXT_GAME_WEBUI_DTM_COMMAND_PREFIX", "+")
    )

    # -- Image generation settings ------------------------------------------
    image_backend: str = Field(
        default_factory=lambda: os.getenv("TEXT_GAME_WEBUI_IMAGE_BACKEND", "none")
    )  # none | diffusers | comfyui
    diffusers_host: str = Field(
        default_factory=lambda: os.getenv("TEXT_GAME_WEBUI_DIFFUSERS_HOST", "127.0.0.1")
    )
    diffusers_port: int = Field(
        default_factory=lambda: int(os.getenv("TEXT_GAME_WEBUI_DIFFUSERS_PORT", "8189"))
    )
    diffusers_model: str = Field(
        default_factory=lambda: os.getenv(
            "TEXT_GAME_WEBUI_DIFFUSERS_MODEL", "black-forest-labs/FLUX.2-klein-4b"
        )
    )
    diffusers_device: str = Field(
        default_factory=lambda: os.getenv("TEXT_GAME_WEBUI_DIFFUSERS_DEVICE", "cuda")
    )
    diffusers_dtype: str = Field(
        default_factory=lambda: os.getenv("TEXT_GAME_WEBUI_DIFFUSERS_DTYPE", "bf16")
    )
    diffusers_offload: str = Field(
        default_factory=lambda: os.getenv("TEXT_GAME_WEBUI_DIFFUSERS_OFFLOAD", "none")
    )
    diffusers_quantization: str = Field(
        default_factory=lambda: os.getenv("TEXT_GAME_WEBUI_DIFFUSERS_QUANTIZATION", "none")
    )
    diffusers_vae_tiling: bool = Field(
        default_factory=lambda: os.getenv("TEXT_GAME_WEBUI_DIFFUSERS_VAE_TILING", "1") in {"1", "true", "True"}
    )
    diffusers_autostart: bool = Field(
        default_factory=lambda: os.getenv("TEXT_GAME_WEBUI_DIFFUSERS_AUTOSTART", "0") in {"1", "true", "True"}
    )
    comfyui_url: str = Field(
        default_factory=lambda: os.getenv("TEXT_GAME_WEBUI_COMFYUI_URL", "http://127.0.0.1:8188")
    )
    comfyui_workflow_json: str = Field(
        default_factory=lambda: os.getenv("TEXT_GAME_WEBUI_COMFYUI_WORKFLOW_JSON", "")
    )
    image_width: int = Field(
        default_factory=lambda: int(os.getenv("TEXT_GAME_WEBUI_IMAGE_WIDTH", "1024"))
    )
    image_height: int = Field(
        default_factory=lambda: int(os.getenv("TEXT_GAME_WEBUI_IMAGE_HEIGHT", "1024"))
    )
    image_steps: int = Field(
        default_factory=lambda: int(os.getenv("TEXT_GAME_WEBUI_IMAGE_STEPS", "20"))
    )
    image_guidance_scale: float = Field(
        default_factory=lambda: float(os.getenv("TEXT_GAME_WEBUI_IMAGE_GUIDANCE_SCALE", "3.5"))
    )
    image_cache_max_entries: int = Field(
        default_factory=lambda: int(os.getenv("TEXT_GAME_WEBUI_IMAGE_CACHE_MAX_ENTRIES", "50"))
    )

    # -- Validators --------------------------------------------------------

    _DTYPE_ALIASES: dict[str, str] = {"fp16": "f16", "fp32": "f32"}
    _VALID_DTYPES: set[str] = {"f16", "bf16", "f32"}
    _VALID_QUANTIZATIONS: set[str] = {"none", "int8", "int4"}

    @field_validator("diffusers_dtype", mode="before")
    @classmethod
    def _normalize_dtype(cls, v: str) -> str:
        v = cls._DTYPE_ALIASES.get(v, v)
        if v not in cls._VALID_DTYPES:
            raise ValueError(f"diffusers_dtype must be one of {cls._VALID_DTYPES}, got {v!r}")
        return v

    @field_validator("diffusers_quantization", mode="before")
    @classmethod
    def _normalize_quantization(cls, v: str) -> str:
        # Strip common "q" prefix aliases
        normalized = v.lower().removeprefix("q")
        if normalized not in cls._VALID_QUANTIZATIONS:
            raise ValueError(
                f"diffusers_quantization must be one of {cls._VALID_QUANTIZATIONS}, got {v!r}"
            )
        return normalized
