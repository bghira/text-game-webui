from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app.media.comfyui_client import ComfyUIClient
from app.media.diffusers_client import DiffusersClient
from app.media.gpu_orchestrator import GpuOrchestrator
from app.media.image_cache import ImageCache

log = logging.getLogger(__name__)

# Health-check result is cached for this many seconds so that the
# synchronous ``gpu_worker_available()`` call doesn't block.
_HEALTH_TTL = 5.0


class LocalMediaPort:
    """Implements the ``MediaGenerationPort`` protocol from text-game-engine.

    Routes image generation to either a local DiffusersClient or an external
    ComfyUIClient, stores results in ImageCache, and publishes them via
    the RealtimeHub WebSocket bus.
    """

    def __init__(
        self,
        *,
        backend: str,
        diffusers_client: DiffusersClient | None,
        comfyui_client: ComfyUIClient | None,
        image_cache: ImageCache,
        realtime_hub: Any,  # app.realtime.hub.RealtimeHub
        settings: Any,  # app.settings.Settings
        gpu_orchestrator: GpuOrchestrator | None = None,
    ) -> None:
        self._backend = backend
        self._diffusers = diffusers_client
        self._comfyui = comfyui_client
        self._cache = image_cache
        self._hub = realtime_hub
        self._settings = settings
        self._orchestrator = gpu_orchestrator

        # Cached health result (updated asynchronously)
        self._healthy = False
        self._health_ts: float = 0.0

    # ------------------------------------------------------------------
    # MediaGenerationPort protocol
    # ------------------------------------------------------------------

    def gpu_worker_available(self) -> bool:
        now = time.monotonic()
        if now - self._health_ts < _HEALTH_TTL:
            return self._healthy
        # Kick off a background refresh (non-blocking for the sync caller)
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._refresh_health())
        except RuntimeError:
            pass
        return self._healthy

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
        asyncio.create_task(
            self._generate_and_publish(
                actor_id=actor_id,
                prompt=prompt,
                model=model,
                ref_type="scene",
                metadata=metadata,
                channel_id=channel_id,
            )
        )
        return True

    async def enqueue_avatar_generation(
        self,
        *,
        actor_id: str,
        prompt: str,
        model: str,
        metadata: dict[str, Any] | None = None,
        channel_id: str | None = None,
    ) -> bool:
        asyncio.create_task(
            self._generate_and_publish(
                actor_id=actor_id,
                prompt=prompt,
                model=model,
                ref_type="avatar",
                metadata=metadata,
                channel_id=channel_id,
            )
        )
        return True

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _refresh_health(self) -> None:
        try:
            if self._backend == "diffusers" and self._diffusers:
                self._healthy = await self._diffusers.health()
            elif self._backend == "comfyui" and self._comfyui:
                self._healthy = await self._comfyui.health()
            else:
                self._healthy = False
        except Exception:
            self._healthy = False
        self._health_ts = time.monotonic()

    async def _generate_and_publish(
        self,
        *,
        actor_id: str,
        prompt: str,
        model: str,
        ref_type: str,
        metadata: dict[str, Any] | None,
        channel_id: str | None,
    ) -> None:
        campaign_id = (metadata or {}).get("campaign_id")
        room_key = (metadata or {}).get("room_key")

        if self._orchestrator:
            await self._orchestrator.before_image_generation()
        try:
            if self._backend == "diffusers":
                entry = await self._generate_diffusers(
                    prompt=prompt,
                    model=model,
                    campaign_id=campaign_id,
                    room_key=room_key,
                    ref_type=ref_type,
                )
            elif self._backend == "comfyui":
                entry = await self._generate_comfyui(
                    prompt=prompt,
                    model=model,
                    campaign_id=campaign_id,
                    room_key=room_key,
                    ref_type=ref_type,
                )
            else:
                log.warning("No image backend configured")
                return

            if entry is None:
                return

            image_url = ImageCache.url_for(entry)

            # Publish via RealtimeHub
            if campaign_id and self._hub:
                payload = {
                    "type": "media",
                    "campaign_id": str(campaign_id),
                    "payload": {
                        "action": f"{ref_type}_generated",
                        "actor_id": actor_id,
                        "image_url": image_url,
                        "image_id": entry.image_id,
                        "prompt": prompt,
                    },
                }
                await self._hub.publish(str(campaign_id), payload)

            log.info(
                "Image generated: type=%s actor=%s url=%s",
                ref_type, actor_id, image_url,
            )
        except Exception:
            log.exception("Image generation failed for actor=%s", actor_id)
        finally:
            if self._orchestrator:
                await self._orchestrator.after_image_generation()

    async def _generate_diffusers(
        self,
        *,
        prompt: str,
        model: str,
        campaign_id: str | None,
        room_key: str | None,
        ref_type: str,
    ):
        if not self._diffusers:
            return None

        s = self._settings
        result = await self._diffusers.generate(
            prompt=prompt,
            model_id=model or s.diffusers_model,
            width=s.image_width,
            height=s.image_height,
            steps=s.image_steps,
            guidance_scale=s.image_guidance_scale,
        )
        job_id = result.get("job_id")
        if not job_id:
            log.error("Diffusers generate returned no job_id: %s", result)
            return None

        status = await self._diffusers.poll_until_complete(job_id)
        if status.get("status") != "completed":
            log.error("Diffusers job %s did not complete: %s", job_id, status)
            return None

        images = status.get("images", [])
        if not images:
            log.error("Diffusers job %s completed with no images", job_id)
            return None

        return self._cache.store_from_base64(
            base64_png=images[0],
            prompt=prompt,
            campaign_id=campaign_id,
            room_key=room_key,
            ref_type=ref_type,
        )

    async def _generate_comfyui(
        self,
        *,
        prompt: str,
        model: str,
        campaign_id: str | None,
        room_key: str | None,
        ref_type: str,
    ):
        if not self._comfyui:
            return None

        s = self._settings
        prompt_id = await self._comfyui.queue_prompt(
            prompt=prompt,
            width=s.image_width,
            height=s.image_height,
            steps=s.image_steps,
            cfg=s.image_guidance_scale,
            seed=-1,
            model=model or s.diffusers_model,
        )

        result = await self._comfyui.poll_until_complete(prompt_id)
        if "outputs" not in result:
            log.error("ComfyUI prompt %s did not complete: %s", prompt_id, result)
            return None

        # Find the first output image
        for _node_id, node_out in result.get("outputs", {}).items():
            images = node_out.get("images", [])
            if images:
                img_info = images[0]
                png_bytes = await self._comfyui.download_image(
                    filename=img_info["filename"],
                    subfolder=img_info.get("subfolder", ""),
                    type_=img_info.get("type", "output"),
                )
                return self._cache.store(
                    png_bytes=png_bytes,
                    prompt=prompt,
                    campaign_id=campaign_id,
                    room_key=room_key,
                    ref_type=ref_type,
                )

        log.error("ComfyUI prompt %s completed with no images", prompt_id)
        return None
