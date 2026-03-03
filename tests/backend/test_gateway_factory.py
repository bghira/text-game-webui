from __future__ import annotations

import pytest

from app.services.engine_gateway import InMemoryEngineGateway
from app.services.gateway_factory import build_gateway
from app.settings import Settings


def test_gateway_factory_defaults_to_inmemory():
    gateway, backend = build_gateway(Settings(gateway_backend="inmemory"))
    assert backend == "inmemory"
    assert isinstance(gateway, InMemoryEngineGateway)


def test_gateway_factory_rejects_unknown_backend():
    with pytest.raises(ValueError):
        build_gateway(Settings(gateway_backend="unknown"))
