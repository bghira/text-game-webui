from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.request

log = logging.getLogger(__name__)


class DiffusersClient:
    """HTTP client for the vendored diffusers_server subprocess."""

    def __init__(self, base_url: str) -> None:
        self._base = base_url.rstrip("/")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _post(self, path: str, body: dict) -> dict:
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            f"{self._base}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())

    def _get(self, path: str) -> dict:
        with urllib.request.urlopen(f"{self._base}{path}", timeout=30) as resp:
            return json.loads(resp.read())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def health(self) -> bool:
        try:
            result = await asyncio.to_thread(self._get, "/health")
            return result.get("status") == "ok"
        except Exception:
            return False

    async def system_stats(self) -> dict:
        return await asyncio.to_thread(self._get, "/system_stats")

    async def generate(
        self,
        *,
        prompt: str,
        model_id: str | None = None,
        mode: str = "text_to_image",
        width: int = 1024,
        height: int = 1024,
        steps: int = 20,
        guidance_scale: float = 3.5,
        seed: int = -1,
        **extra: object,
    ) -> dict:
        body: dict = {
            "prompt": prompt,
            "mode": mode,
            "width": width,
            "height": height,
            "num_inference_steps": steps,
            "guidance_scale": guidance_scale,
            "seed": seed,
        }
        if model_id:
            body["model_id"] = model_id
        body.update(extra)
        return await asyncio.to_thread(self._post, "/generate", body)

    async def poll_status(self, job_id: str) -> dict:
        return await asyncio.to_thread(self._get, f"/status/{job_id}")

    async def poll_until_complete(
        self,
        job_id: str,
        *,
        timeout: float = 300,
        interval: float = 1.0,
    ) -> dict:
        import time

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = await self.poll_status(job_id)
            state = status.get("status", "")
            if state in ("completed", "failed", "interrupted"):
                return status
            await asyncio.sleep(interval)
        return {"status": "timeout", "error": f"Timed out after {timeout}s"}

    async def interrupt(self) -> dict:
        return await asyncio.to_thread(self._post, "/interrupt", {})
