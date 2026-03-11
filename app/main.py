from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.routes import router as api_router
from app.api.ws import router as ws_router
from app.realtime.hub import RealtimeHub
from app.services.gateway_factory import build_gateway
from app.settings import Settings
from app.ui.routes import router as ui_router


def create_app() -> FastAPI:
    app_dir = Path(__file__).resolve().parent
    settings = Settings()
    gateway, backend = build_gateway(settings)

    app = FastAPI(title=settings.app_name, debug=settings.debug)
    app.state.settings = settings
    app.state.gateway = gateway
    app.state.gateway_backend = backend
    app.state.realtime = RealtimeHub()
    app.state.templates = Jinja2Templates(directory=str(app_dir / "templates"))

    app.mount("/static", StaticFiles(directory=str(app_dir / "static")), name="static")
    app.include_router(api_router)
    app.include_router(ws_router)
    app.include_router(ui_router)
    return app


app = create_app()
