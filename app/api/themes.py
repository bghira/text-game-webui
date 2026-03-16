"""Theme API routes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

router = APIRouter(prefix="/api/themes", tags=["themes"])


def _svc(request: Request):
    return request.app.state.theme_service


@router.get("")
async def list_themes(request: Request):
    return _svc(request).list_for_ui()


@router.get("/{theme_id}")
async def get_theme(request: Request, theme_id: str):
    theme = _svc(request).get_theme(theme_id)
    if not theme:
        raise HTTPException(404, "Theme not found")
    return {
        "id": theme.id,
        "name": theme.name,
        "description": theme.description,
        "author": theme.author,
        "source": theme.source,
    }


@router.get("/{theme_id}/theme.css")
async def get_theme_css(request: Request, theme_id: str):
    theme = _svc(request).get_theme(theme_id)
    if not theme or not theme.css_path or not theme.css_path.exists():
        raise HTTPException(404, "Theme CSS not found")
    # Built-in themes are served directly from static; custom themes via FileResponse
    if theme.source == "builtin":
        raise HTTPException(404, "Built-in theme CSS served via static assets")
    return FileResponse(theme.css_path, media_type="text/css")


@router.get("/{theme_id}/manifest")
async def get_theme_manifest(request: Request, theme_id: str):
    theme = _svc(request).get_theme(theme_id)
    if not theme:
        raise HTTPException(404, "Theme not found")
    return {
        "id": theme.id,
        "images": list(theme.assets.images.keys()),
        "sounds": list(theme.assets.sounds.keys()),
    }


@router.get("/{theme_id}/assets/images/{name}")
async def get_image_asset(request: Request, theme_id: str, name: str):
    path = _svc(request).get_asset_path(theme_id, "images", name)
    if not path or not path.exists():
        raise HTTPException(404, "Asset not found")
    return FileResponse(path)


@router.get("/{theme_id}/assets/sounds/{name}")
async def get_sound_asset(request: Request, theme_id: str, name: str):
    path = _svc(request).get_asset_path(theme_id, "sounds", name)
    if not path or not path.exists():
        raise HTTPException(404, "Asset not found")
    return FileResponse(path)


@router.post("/refresh")
async def refresh_themes(request: Request):
    _svc(request).invalidate_cache()
    return _svc(request).list_for_ui()


# -- Theme setting endpoints (under /api/settings/theme) --

settings_router = APIRouter(prefix="/api/settings", tags=["settings"])


@settings_router.get("/theme")
async def get_theme_setting(request: Request):
    settings = request.app.state.settings
    return {"theme": getattr(settings, "theme", "light")}


@settings_router.post("/theme")
async def set_theme_setting(request: Request):
    body = await request.json()
    theme_id = body.get("theme", "light")
    svc = _svc(request)
    if not svc.is_valid_theme(theme_id):
        raise HTTPException(400, f"Unknown theme: {theme_id}")
    settings = request.app.state.settings
    settings.theme = theme_id
    from app.settings import persist_settings
    persist_settings(settings)
    return {"theme": theme_id}
