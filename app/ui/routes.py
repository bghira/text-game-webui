from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["ui"])


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    settings = request.app.state.settings
    return request.app.state.templates.TemplateResponse(
        request,
        "index.html",
        {
            "app_name": request.app.title,
            "theme": getattr(settings, "theme", "light"),
        },
    )
