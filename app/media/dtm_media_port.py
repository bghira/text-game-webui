"""MediaGenerationPort implementation that routes to discord-tron-master's GPU cluster.

When ``image_backend=dtm``, the webui sends image generation requests to DTM
via its REST API.  DTM enqueues the job on its GPU worker pool, and when the
worker finishes it POSTs the result back to the webui's
``/api/internal/campaigns/{id}/media/deliver`` callback endpoint.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx

log = logging.getLogger(__name__)

# Health-check result is cached for this many seconds.
_HEALTH_TTL = 10.0


class DtmMediaPort:
    """Implements ``MediaGenerationPort`` by delegating to DTM over HTTP."""

    def __init__(
        self,
        *,
        dtm_api_url: str,
        dtm_secret: str,
        webui_callback_base: str,
    ) -> None:
        # e.g. "https://localhost:5000"
        self._api_url = dtm_api_url.rstrip("/")
        self._secret = dtm_secret
        # e.g. "http://127.0.0.1:8080" — used to build the callback URL
        self._callback_base = webui_callback_base.rstrip("/")

        self._healthy = False
        self._health_ts: float = 0.0

    # ------------------------------------------------------------------
    # MediaGenerationPort protocol
    # ------------------------------------------------------------------

    def gpu_worker_available(self) -> bool:
        now = time.monotonic()
        if now - self._health_ts < _HEALTH_TTL:
            return self._healthy
        # Optimistic: assume DTM is up unless we've recently failed.
        return True

    async def enqueue_scene_generation(
        self,
        *,
        actor_id: str,
        prompt: str,
        model: str,
        reference_images: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        channel_id: str | None = None,
    ) -> bool:
        return await self._enqueue(
            ref_type="scene",
            actor_id=actor_id,
            prompt=prompt,
            model=model,
            reference_images=reference_images,
            metadata=metadata,
        )

    async def enqueue_avatar_generation(
        self,
        *,
        actor_id: str,
        prompt: str,
        model: str,
        metadata: dict[str, Any] | None = None,
        channel_id: str | None = None,
    ) -> bool:
        return await self._enqueue(
            ref_type="avatar",
            actor_id=actor_id,
            prompt=prompt,
            model=model,
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _enqueue(
        self,
        *,
        ref_type: str,
        actor_id: str,
        prompt: str,
        model: str,
        reference_images: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        meta = dict(metadata or {})
        campaign_id = meta.get("campaign_id") or meta.get("zork_campaign_id")
        room_key = meta.get("room_key") or meta.get("zork_room_key")
        webui_job_id = meta.get("webui_job_id")

        callback_url = ""
        if campaign_id:
            callback_url = (
                f"{self._callback_base}/api/internal/campaigns"
                f"/{campaign_id}/media/deliver"
            )

        payload = {
            "prompt": prompt,
            "model": model or "flux",
            "ref_type": ref_type,
            "actor_id": actor_id,
            "campaign_id": str(campaign_id) if campaign_id else None,
            "room_key": room_key,
            "callback_url": callback_url,
            "callback_secret": self._secret,
            "job_id": webui_job_id,
            "reference_images": reference_images,
            # Forward the full metadata so DTM can set zork flags correctly.
            "metadata": meta,
        }

        url = f"{self._api_url}/api/zork/image/generate"
        try:
            async with httpx.AsyncClient(timeout=15, verify=False) as client:
                resp = await client.post(
                    url,
                    json=payload,
                    headers={"X-DTM-Link-Secret": self._secret},
                )
                resp.raise_for_status()
                self._healthy = True
                self._health_ts = time.monotonic()
                return True
        except Exception as exc:
            log.warning("DTM image enqueue failed (%s): %s", url, exc)
            self._healthy = False
            self._health_ts = time.monotonic()
            return False
