from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.routes import router as api_router
from app.api.themes import router as themes_router, settings_router as theme_settings_router
from app.api.ws import router as ws_router
from app.media.image_cache import ImageCache
from app.realtime.hub import RealtimeHub
from app.services.gateway_factory import build_gateway
from app.services.theme_service import ThemeService
from app.settings import Settings, load_persisted_settings
from app.ui.routes import router as ui_router

log = logging.getLogger(__name__)


def _init_media(app: FastAPI, settings: Settings, app_dir: Path) -> None:
    """Wire up the image-generation subsystem based on settings."""
    generated_dir = app_dir / "static" / "generated"
    image_cache = ImageCache(generated_dir, max_entries=settings.image_cache_max_entries)
    app.state.image_cache = image_cache

    # Mount /generated/ so PNGs are served directly
    app.mount(
        "/generated",
        StaticFiles(directory=str(generated_dir)),
        name="generated",
    )

    backend = (settings.image_backend or "none").strip().lower()
    daemon = None
    diffusers_client = None
    comfyui_client = None

    if backend == "diffusers":
        from app.media.diffusers_daemon import DiffusersDaemon
        from app.media.diffusers_client import DiffusersClient

        daemon = DiffusersDaemon(
            host=settings.diffusers_host,
            port=settings.diffusers_port,
            model=settings.diffusers_model,
            device=settings.diffusers_device,
            dtype=settings.diffusers_dtype,
            offload=settings.diffusers_offload,
            quantization=settings.diffusers_quantization,
            vae_tiling=settings.diffusers_vae_tiling,
        )
        diffusers_client = DiffusersClient(daemon.base_url)

    elif backend == "comfyui":
        from app.media.comfyui_client import ComfyUIClient

        workflow = None
        if settings.comfyui_workflow_json:
            try:
                # Could be inline JSON or a file path
                raw = settings.comfyui_workflow_json.strip()
                if raw.startswith("{"):
                    workflow = json.loads(raw)
                else:
                    workflow = json.loads(Path(raw).read_text())
            except Exception as exc:
                log.warning("Failed to load custom ComfyUI workflow: %s", exc)
        comfyui_client = ComfyUIClient(settings.comfyui_url, workflow_template=workflow)

    app.state.diffusers_daemon = daemon
    app.state.diffusers_client = diffusers_client
    app.state.comfyui_client = comfyui_client

    # Create GPU orchestrator if Ollama + image backend share a GPU
    gpu_orchestrator = None
    if (
        settings.tge_completion_mode == "ollama"
        and backend in ("diffusers", "comfyui")
    ):
        from app.media.gpu_orchestrator import GpuOrchestrator

        gpu_orchestrator = GpuOrchestrator(
            ollama_base_url=settings.tge_llm_base_url,
            ollama_model=settings.tge_llm_model,
            ollama_keep_alive=settings.tge_ollama_keep_alive,
            image_backend=backend,
            diffusers_client=diffusers_client,
        )
        log.info("GPU orchestrator created (ollama + %s)", backend)

    app.state.gpu_orchestrator = gpu_orchestrator
    app.state.gpu_orchestrated_jobs: set = set()

    # Create and inject LocalMediaPort if a backend is configured
    if backend in ("diffusers", "comfyui"):
        from app.media.media_port import LocalMediaPort

        media_port = LocalMediaPort(
            backend=backend,
            diffusers_client=diffusers_client,
            comfyui_client=comfyui_client,
            image_cache=image_cache,
            realtime_hub=app.state.realtime,
            settings=settings,
            gpu_orchestrator=gpu_orchestrator,
        )
        app.state.media_port = media_port

        # Inject into the TGE gateway if applicable
        gateway = app.state.gateway
        if hasattr(gateway, "set_media_port"):
            gateway.set_media_port(media_port)
            log.info("Media port injected into gateway (backend=%s)", backend)
    else:
        app.state.media_port = None

    # Auto-start daemon if configured
    if daemon and settings.diffusers_autostart:

        async def _autostart() -> None:
            log.info("Auto-starting diffusers daemon")
            await daemon.start()

        @app.on_event("startup")
        async def _on_startup() -> None:
            await _autostart()


class WebNotificationPort:
    """Implements NotificationPort by publishing DM events through the RealtimeHub."""

    def __init__(self, realtime_hub: RealtimeHub) -> None:
        self._hub = realtime_hub

    async def send_dm(self, actor_id: str, message: str) -> None:
        # Snapshot campaign IDs to avoid iterating a live dict
        for campaign_id in self._hub.campaigns_for_actor(actor_id):
            await self._hub.publish_to_actor(
                campaign_id,
                actor_id,
                {
                    "type": "dm_notification",
                    "actor_id": actor_id,
                    "payload": {
                        "message": message,
                        "actor_id": actor_id,
                        "refresh_sms_threads": True,
                    },
                },
            )

    async def send_channel_message(
        self,
        *,
        campaign_id: str,
        message: str,
    ) -> None:
        # Channel messages broadcast to all subscribers of the campaign
        await self._hub.publish(
            campaign_id,
            {
                "type": "channel_notification",
                "payload": {"message": message},
            },
        )


class WebTimerEffectsPort:
    """Implements TimerEffectsPort by publishing events through the RealtimeHub."""

    def __init__(self, realtime_hub: RealtimeHub) -> None:
        self._hub = realtime_hub

    async def edit_timer_line(
        self,
        channel_id: str,
        message_id: str,
        replacement: str,
    ) -> None:
        # No editable messages in the web UI — ignore.
        pass

    async def emit_timed_event(
        self,
        campaign_id: str,
        channel_id: str,
        actor_id: str | None,
        narration: str,
    ) -> None:
        await self._hub.publish(
            campaign_id,
            {
                "type": "timed_event",
                "actor_id": actor_id,
                "payload": {
                    "narration": narration,
                    "actor_id": actor_id,
                },
            },
        )


def create_app() -> FastAPI:
    app_dir = Path(__file__).resolve().parent
    settings = Settings()
    load_persisted_settings(settings)
    gateway, backend = build_gateway(settings)

    app = FastAPI(title=settings.app_name, debug=settings.debug)
    app.state.settings = settings
    app.state.gateway = gateway
    app.state.gateway_backend = backend
    app.state.realtime = RealtimeHub()
    app.state.templates = Jinja2Templates(directory=str(app_dir / "templates"))
    app.state.theme_service = ThemeService()

    app.mount("/static", StaticFiles(directory=str(app_dir / "static")), name="static")
    app.mount("/media", StaticFiles(directory=str(app_dir / "media")), name="media")

    # Initialize media subsystem (mounts /generated/ and wires media_port)
    _init_media(app, settings, app_dir)

    # Wire up timer effects port so timed event results are pushed via WebSocket
    if hasattr(gateway, "set_timer_effects_port"):
        timer_port = WebTimerEffectsPort(app.state.realtime)
        gateway.set_timer_effects_port(timer_port)
        log.info("Timer effects port injected into gateway")

    # Wire up notification port so DM/SMS notifications push via WebSocket
    if hasattr(gateway, "set_notification_port"):
        notification_port = WebNotificationPort(app.state.realtime)
        gateway.set_notification_port(notification_port)
        log.info("Notification port injected into gateway")

    app.include_router(api_router)
    app.include_router(themes_router)
    app.include_router(theme_settings_router)
    app.include_router(ws_router)
    app.include_router(ui_router)
    return app


app = create_app()
