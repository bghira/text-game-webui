from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["ui"])


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return request.app.state.templates.TemplateResponse(
        request,
        "index.html",
        {
            "app_name": request.app.title,
            "features": request.app.state.features,
        },
    )


@router.get("/partials/feature-list", response_class=HTMLResponse)
async def feature_list_partial(request: Request):
    return request.app.state.templates.TemplateResponse(
        request,
        "partials/feature_list.html",
        {"features": request.app.state.features},
    )
