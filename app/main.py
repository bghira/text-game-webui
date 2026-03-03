from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.routes import router as api_router
from app.api.ws import router as ws_router
from app.realtime.hub import RealtimeHub
from app.services.engine_gateway import FEATURES, InMemoryEngineGateway
from app.settings import Settings
from app.ui.routes import router as ui_router


def create_app() -> FastAPI:
    settings = Settings()
    app = FastAPI(title=settings.app_name, debug=settings.debug)
    app.state.settings = settings
    app.state.gateway = InMemoryEngineGateway()
    app.state.realtime = RealtimeHub()
    app.state.features = FEATURES
    app.state.templates = Jinja2Templates(directory="app/templates")

    app.mount("/static", StaticFiles(directory="app/static"), name="static")
    app.include_router(api_router)
    app.include_router(ws_router)
    app.include_router(ui_router)
    return app


app = create_app()
