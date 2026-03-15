"""Tests for image settings, daemon control, and generation endpoints."""
from __future__ import annotations

import asyncio
import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Settings endpoints
# ---------------------------------------------------------------------------


def test_get_image_settings(client):
    res = client.get("/api/settings/image")
    assert res.status_code == 200
    body = res.json()
    assert body["image_backend"] == "none"
    assert body["diffusers_dtype"] == "bf16"
    assert body["diffusers_quantization"] == "none"
    assert "image_cache_max_entries" in body
    assert body["daemon_state"] is None


def test_update_image_settings(client):
    res = client.post(
        "/api/settings/image",
        json={"image_width": 512, "image_height": 512},
    )
    assert res.status_code == 200
    body = res.json()
    assert set(body["updated"]) == {"image_width", "image_height"}
    assert body["restart_required"] is False

    # Verify values persisted in memory
    check = client.get("/api/settings/image")
    assert check.json()["image_width"] == 512
    assert check.json()["image_height"] == 512


def test_update_image_settings_restart_required(client):
    res = client.post(
        "/api/settings/image",
        json={"diffusers_host": "192.168.1.100"},
    )
    assert res.status_code == 200
    assert res.json()["restart_required"] is True


def test_update_image_settings_empty_body(client):
    res = client.post("/api/settings/image", json={})
    assert res.status_code == 400
    assert "No settings" in res.json()["detail"]


def test_update_image_settings_blank_strings_ignored(client):
    res = client.post("/api/settings/image", json={"diffusers_model": "   "})
    assert res.status_code == 400  # nothing updated


# ---------------------------------------------------------------------------
# Daemon control (no daemon configured in inmemory mode)
# ---------------------------------------------------------------------------


def test_daemon_status_not_configured(client):
    res = client.get("/api/image/daemon/status")
    assert res.status_code == 200
    assert res.json()["state"] == "not_configured"


def test_daemon_start_not_configured(client):
    res = client.post("/api/image/daemon/start")
    assert res.status_code == 400


def test_daemon_stop_not_configured(client):
    res = client.post("/api/image/daemon/stop")
    assert res.status_code == 400


def test_daemon_logs_not_configured(client):
    res = client.get("/api/image/daemon/logs")
    assert res.status_code == 200
    assert res.json()["logs"] == []


# ---------------------------------------------------------------------------
# Generate/status endpoints (no backend configured)
# ---------------------------------------------------------------------------


def test_generate_no_backend(client):
    res = client.post(
        "/api/image/generate",
        json={"prompt": "a castle on a hill"},
    )
    assert res.status_code == 400
    assert "No image backend" in res.json()["detail"]


def test_status_no_backend(client):
    res = client.get("/api/image/status/fake-job-id")
    assert res.status_code == 400


def test_recent_images_empty(client):
    res = client.get("/api/image/recent")
    assert res.status_code == 200
    assert res.json()["images"] == []


# ---------------------------------------------------------------------------
# Diffusers generate/status flow (mocked client)
# ---------------------------------------------------------------------------


def test_generate_diffusers_flow(client):
    settings = client.app.state.settings
    settings.image_backend = "diffusers"

    mock_client = AsyncMock()
    mock_client.generate.return_value = {"job_id": "test-job-1", "status": "pending"}
    client.app.state.diffusers_client = mock_client

    res = client.post(
        "/api/image/generate",
        json={"prompt": "a dragon", "width": 768, "height": 768, "steps": 10},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["job_id"] == "test-job-1"

    # Verify the client was called with correct args (not falsy defaults)
    call_kwargs = mock_client.generate.call_args.kwargs
    assert call_kwargs["width"] == 768
    assert call_kwargs["height"] == 768
    assert call_kwargs["steps"] == 10

    # Clean up
    settings.image_backend = "none"
    client.app.state.diffusers_client = None


def test_status_diffusers_completed(client):
    settings = client.app.state.settings
    settings.image_backend = "diffusers"

    # Create a minimal 1x1 white PNG for cache storage
    import struct, zlib

    def _make_tiny_png() -> bytes:
        raw = b"\x00\xff\xff\xff"
        compressed = zlib.compress(raw)
        ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
        chunks = b""
        for ctype, cdata in [(b"IHDR", ihdr), (b"IDAT", compressed), (b"IEND", b"")]:
            chunk = struct.pack(">I", len(cdata)) + ctype + cdata
            crc = zlib.crc32(ctype + cdata) & 0xFFFFFFFF
            chunks += chunk + struct.pack(">I", crc)
        return b"\x89PNG\r\n\x1a\n" + chunks

    png_b64 = base64.b64encode(_make_tiny_png()).decode()

    mock_client = AsyncMock()
    mock_client.poll_status.return_value = {
        "status": "completed",
        "images": [png_b64],
    }
    client.app.state.diffusers_client = mock_client

    res = client.get("/api/image/status/test-job-1")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "completed"
    assert "image_url" in body
    assert body["image_url"].startswith("/generated/")
    assert "image_id" in body

    # Clean up
    settings.image_backend = "none"
    client.app.state.diffusers_client = None


# ---------------------------------------------------------------------------
# ComfyUI generate/status flow (mocked client)
# ---------------------------------------------------------------------------


def test_generate_comfyui_flow(client):
    settings = client.app.state.settings
    settings.image_backend = "comfyui"

    mock_client = AsyncMock()
    mock_client.queue_prompt.return_value = "comfy-prompt-1"
    client.app.state.comfyui_client = mock_client

    res = client.post(
        "/api/image/generate",
        json={"prompt": "a castle", "guidance_scale": 7.5},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["job_id"] == "comfy-prompt-1"
    assert body["backend"] == "comfyui"

    # Verify guidance_scale was passed as cfg
    call_kwargs = mock_client.queue_prompt.call_args.kwargs
    assert call_kwargs["cfg"] == 7.5

    # Clean up
    settings.image_backend = "none"
    client.app.state.comfyui_client = None


def test_status_comfyui_pending(client):
    settings = client.app.state.settings
    settings.image_backend = "comfyui"

    mock_client = AsyncMock()
    mock_client.get_history.return_value = {}
    client.app.state.comfyui_client = mock_client

    res = client.get("/api/image/status/comfy-prompt-1")
    assert res.status_code == 200
    assert res.json()["status"] == "pending"

    # Clean up
    settings.image_backend = "none"
    client.app.state.comfyui_client = None


# ---------------------------------------------------------------------------
# GPU stats endpoint
# ---------------------------------------------------------------------------


def test_gpu_stats_unavailable_when_not_ollama(client):
    """GPU stats returns available=false when completion mode is not ollama."""
    settings = client.app.state.settings
    original_mode = settings.tge_completion_mode
    settings.tge_completion_mode = "deterministic"

    # Clear server-side cache so we get a fresh result
    from app.api import routes as _routes
    _routes._gpu_cache.clear()
    _routes._gpu_cache_ts = 0.0

    res = client.get("/api/gpu-stats")
    assert res.status_code == 200
    body = res.json()
    assert body["available"] is False

    # Clean up
    settings.tge_completion_mode = original_mode


# ---------------------------------------------------------------------------
# GPU orchestrator
# ---------------------------------------------------------------------------


def test_gpu_orchestrator_sequence():
    """Verify before/after_image_generation call Ollama and diffusers in order."""
    from app.media.gpu_orchestrator import GpuOrchestrator

    mock_diffusers = AsyncMock()
    mock_diffusers.unload.return_value = {"status": "unloaded"}

    orchestrator = GpuOrchestrator(
        ollama_base_url="http://127.0.0.1:11434",
        ollama_model="test-model",
        ollama_keep_alive="30m",
        image_backend="diffusers",
        diffusers_client=mock_diffusers,
    )

    call_log: list[str] = []

    def mock_post_generate(body: dict) -> None:
        if body.get("keep_alive") == 0:
            call_log.append("evict")
        elif body.get("prompt") == "":
            call_log.append("reload")

    def mock_ps() -> list:
        # Return empty immediately so polling exits fast
        return []

    orchestrator._ollama_post_generate = mock_post_generate  # type: ignore[assignment]
    orchestrator._ollama_ps = mock_ps  # type: ignore[assignment]

    # Run the full sequence
    asyncio.run(orchestrator.before_image_generation())
    asyncio.run(orchestrator.after_image_generation())

    assert call_log == ["evict", "reload"]
    mock_diffusers.unload.assert_awaited_once()


def test_gpu_orchestrator_comfyui_skips_unload():
    """ComfyUI path should skip the diffusers unload step."""
    from app.media.gpu_orchestrator import GpuOrchestrator

    orchestrator = GpuOrchestrator(
        ollama_base_url="http://127.0.0.1:11434",
        ollama_model="test-model",
        ollama_keep_alive="30m",
        image_backend="comfyui",
        diffusers_client=None,
    )

    call_log: list[str] = []

    def mock_post_generate(body: dict) -> None:
        if body.get("keep_alive") == 0:
            call_log.append("evict")
        elif body.get("prompt") == "":
            call_log.append("reload")

    def mock_ps() -> list:
        return []

    orchestrator._ollama_post_generate = mock_post_generate  # type: ignore[assignment]
    orchestrator._ollama_ps = mock_ps  # type: ignore[assignment]

    asyncio.run(orchestrator.before_image_generation())
    asyncio.run(orchestrator.after_image_generation())

    # Should have evict and reload but no diffusers unload
    assert call_log == ["evict", "reload"]


def test_gpu_orchestrator_url_stripping():
    """Verify /v1 suffix is stripped from the Ollama base URL."""
    from app.media.gpu_orchestrator import GpuOrchestrator

    orch = GpuOrchestrator(
        ollama_base_url="http://127.0.0.1:11434/v1",
        ollama_model="m",
        ollama_keep_alive="30m",
        image_backend="diffusers",
    )
    assert orch._ollama_base == "http://127.0.0.1:11434"
