from __future__ import annotations

import json
import os
import re
import sqlite3
from pydantic import BaseModel, Field


# Keys that can be persisted to the webui_kv table.
_PERSISTABLE_KEYS = frozenset({
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


class Settings(BaseModel):
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
    tge_ollama_keep_alive: str = Field(
        default_factory=lambda: os.getenv("TEXT_GAME_WEBUI_TGE_OLLAMA_KEEP_ALIVE", "30m")
    )
    tge_ollama_options_json: str = Field(
        default_factory=lambda: os.getenv("TEXT_GAME_WEBUI_TGE_OLLAMA_OPTIONS_JSON", "{}")
    )
    tge_runtime_probe_llm: bool = Field(
        default_factory=lambda: os.getenv("TEXT_GAME_WEBUI_TGE_RUNTIME_PROBE_LLM", "0") in {"1", "true", "True"}
    )
    tge_runtime_probe_timeout_seconds: int = Field(
        default_factory=lambda: int(os.getenv("TEXT_GAME_WEBUI_TGE_RUNTIME_PROBE_TIMEOUT_SECONDS", "8"))
    )
