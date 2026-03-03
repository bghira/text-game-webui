from __future__ import annotations

from pydantic import BaseModel


class Settings(BaseModel):
    app_name: str = "text-game-webui"
    debug: bool = True
    host: str = "0.0.0.0"
    port: int = 8080
    attention_window_seconds: int = 600
