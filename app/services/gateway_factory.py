from __future__ import annotations

from app.settings import Settings

from .engine_gateway import EngineGateway, InMemoryEngineGateway


def build_gateway(settings: Settings) -> tuple[EngineGateway, str]:
    backend = (settings.gateway_backend or "inmemory").strip().lower()

    if backend == "inmemory":
        return InMemoryEngineGateway(), backend

    if backend == "tge":
        from .tge_gateway import TextGameEngineGateway

        return TextGameEngineGateway(settings), backend

    raise ValueError(f"Unsupported gateway backend: {backend}")
