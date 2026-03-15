from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

_POLL_INTERVAL = 0.5  # seconds between /api/ps polls
_POLL_TIMEOUT = 15.0  # max seconds to wait for Ollama to release VRAM


class GpuOrchestrator:
    """Coordinates GPU VRAM between Ollama (LLM) and an image generation backend.

    Before image generation: evicts the Ollama model from VRAM.
    After image generation: unloads the image model (diffusers only) and reloads Ollama.
    """

    def __init__(
        self,
        *,
        ollama_base_url: str,
        ollama_model: str,
        ollama_keep_alive: str,
        image_backend: str,
        diffusers_client=None,
    ) -> None:
        # Strip known path suffixes to get the Ollama root URL.
        base = ollama_base_url.rstrip("/")
        for suffix in ("/v1", "/api"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
                break
        self._ollama_base = base
        self._ollama_model = ollama_model
        self._ollama_keep_alive = ollama_keep_alive
        self._image_backend = image_backend
        self._diffusers_client = diffusers_client
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def before_image_generation(self) -> None:
        """Evict the Ollama model from VRAM before image generation."""
        async with self._lock:
            await self._evict_ollama()

    async def after_image_generation(self) -> None:
        """Unload image model (diffusers) and reload Ollama after generation."""
        async with self._lock:
            await self._unload_image_model()
            await self._reload_ollama()

    # ------------------------------------------------------------------
    # Internal: Ollama eviction
    # ------------------------------------------------------------------

    def _ollama_post_generate(self, body: dict) -> None:
        """Blocking POST to Ollama /api/generate."""
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            f"{self._ollama_base}/api/generate",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp.read()
        except (urllib.error.URLError, OSError) as exc:
            log.warning("Ollama /api/generate request failed: %s", exc)

    def _ollama_ps(self) -> list:
        """Blocking GET to Ollama /api/ps. Returns the models list."""
        try:
            req = urllib.request.Request(
                f"{self._ollama_base}/api/ps", method="GET"
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
            return data.get("models", [])
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            log.warning("Ollama /api/ps request failed: %s", exc)
            return []

    async def _evict_ollama(self) -> None:
        """Send keep_alive=0 to Ollama and poll /api/ps until models list is empty."""
        log.info("GPU orchestrator: evicting Ollama model %s", self._ollama_model)
        try:
            await asyncio.to_thread(
                self._ollama_post_generate,
                {"model": self._ollama_model, "keep_alive": 0},
            )
        except Exception:
            log.warning("GPU orchestrator: failed to send evict request to Ollama", exc_info=True)
            return

        # Poll until VRAM is released
        import time
        deadline = time.monotonic() + _POLL_TIMEOUT
        while time.monotonic() < deadline:
            models = await asyncio.to_thread(self._ollama_ps)
            if not models:
                log.info("GPU orchestrator: Ollama VRAM released")
                return
            await asyncio.sleep(_POLL_INTERVAL)

        log.warning("GPU orchestrator: Ollama did not release VRAM within %ss", _POLL_TIMEOUT)

    # ------------------------------------------------------------------
    # Internal: image model unload
    # ------------------------------------------------------------------

    async def _unload_image_model(self) -> None:
        """Unload the image model from VRAM (diffusers only)."""
        if self._image_backend != "diffusers" or self._diffusers_client is None:
            return
        log.info("GPU orchestrator: unloading diffusers model")
        try:
            await self._diffusers_client.unload()
        except Exception:
            log.warning("GPU orchestrator: failed to unload diffusers model", exc_info=True)

    # ------------------------------------------------------------------
    # Internal: Ollama reload
    # ------------------------------------------------------------------

    async def _reload_ollama(self) -> None:
        """Reload the Ollama model into VRAM with configured keep_alive."""
        log.info("GPU orchestrator: reloading Ollama model %s", self._ollama_model)
        try:
            await asyncio.to_thread(
                self._ollama_post_generate,
                {
                    "model": self._ollama_model,
                    "prompt": "",
                    "keep_alive": self._ollama_keep_alive,
                },
            )
        except Exception:
            log.warning("GPU orchestrator: failed to reload Ollama model", exc_info=True)
