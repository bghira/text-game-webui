from __future__ import annotations

import asyncio
import json
import os
import platform
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import time
from datetime import UTC, datetime
from typing import NoReturn
from urllib import request as urllib_request
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.services.dtm_link_auth import (
    LINK_CONFIRM_HEADER,
    LINK_PENDING_COOKIE,
    LINK_SESSION_COOKIE,
    confirm_pending_link,
    dtm_link_enabled,
    get_linked_actor_from_request,
    get_or_create_pending_link,
    issue_session_cookie_value,
)
from app.services.engine_gateway import FEATURES, EngineGateway
from app.services.schemas import (
    AttributeSetRequest,
    AvatarActionRequest,
    AvatarGenerateRequest,
    CalendarVisibilityUpdateRequest,
    CampaignRuleUpdate,
    CampaignFlagsUpdate,
    CharacterPortraitRequest,
    ImageGenerateRequest,
    ImageSettingsUpdate,
    LLMSettingsUpdate,
    LevelUpRequest,
    MinigameMoveRequest,
    MemorySearchRequest,
    MemoryStoreRequest,
    MemoryTermsRequest,
    MemoryTurnRequest,
    PlayerNameUpdateRequest,
    PersonaUpdateRequest,
    PuzzleAnswerRequest,
    RosterRemoveRequest,
    ScheduledSmsRequest,
    SetupMessageRequest,
    SetupStartRequest,
    RosterUpsertRequest,
    SessionCreateRequest,
    SessionUpdateRequest,
    SmsListRequest,
    SmsReadRequest,
    SmsWriteRequest,
    SourceMaterialDigestIngest,
    SourceMaterialIngest,
    SourceMaterialSearchRequest,
    TurnEditRequest,
    TurnRequest,
)

try:
    import torch
except Exception:  # pragma: no cover - optional dependency
    torch = None

router = APIRouter(prefix="/api", tags=["api"])


class CampaignCreateRequest(BaseModel):
    namespace: str = "default"
    name: str
    actor_id: str


class DtmLinkConfirmRequest(BaseModel):
    code: str
    actor_id: str
    display_name: str = ""


class InternalTurnRefreshRequest(BaseModel):
    actor_id: str | None = None
    session_id: str | None = None


def get_gateway(request: Request) -> EngineGateway:
    return request.app.state.gateway


def _not_found(err: KeyError) -> NoReturn:
    raise HTTPException(status_code=404, detail=str(err)) from err


def _bad_request(err: ValueError) -> NoReturn:
    raise HTTPException(status_code=400, detail=str(err)) from err


def _linked_actor_id(request: Request) -> str | None:
    actor_id = str(getattr(request.state, "linked_actor_id", "") or "").strip()
    return actor_id or None


def _linked_display_name(request: Request) -> str:
    return str(getattr(request.state, "linked_display_name", "") or "").strip()


def _coerced_actor_id(request: Request, provided: str | None = None) -> str:
    return _linked_actor_id(request) or str(provided or "").strip()


def _coerced_mentioned_actor_ids(payload: TurnRequest) -> list[str]:
    actor_id = str(payload.actor_id or "").strip()
    seen: set[str] = set()
    rows: list[str] = []
    for raw in list(payload.mentioned_actor_ids or []):
        target_actor_id = str(raw or "").strip()
        if not target_actor_id or target_actor_id == actor_id or target_actor_id in seen:
            continue
        seen.add(target_actor_id)
        rows.append(target_actor_id)
    return rows


async def _publish_pending_mentions(
    request: Request,
    campaign_id: str,
    payload: TurnRequest,
) -> tuple[str | None, list[str]]:
    target_actor_ids = _coerced_mentioned_actor_ids(payload)
    if not target_actor_ids:
        return None, []
    pending_id = uuid4().hex
    for target_actor_id in target_actor_ids:
        try:
            await request.app.state.realtime.publish_to_actor(
                campaign_id,
                target_actor_id,
                {
                    "type": "pending_mention",
                    "actor_id": target_actor_id,
                    "payload": {
                        "pending_id": pending_id,
                        "source_actor_id": str(payload.actor_id or "").strip(),
                        "source_session_id": str(payload.session_id or "").strip() or None,
                        "action_text": str(payload.action or "").strip(),
                    },
                },
            )
        except Exception:
            pass
    return pending_id, target_actor_ids


async def _shared_pending_session_id(
    gateway: EngineGateway,
    campaign_id: str,
    payload: TurnRequest,
) -> str | None:
    source_session_id = str(payload.session_id or "").strip()
    if not source_session_id:
        return None
    try:
        sessions = await gateway.list_sessions(campaign_id)
    except Exception:
        return None
    for row in sessions:
        if str(row.get("id") or "").strip() != source_session_id:
            continue
        surface = str(row.get("surface") or "").strip().lower()
        enabled = row.get("enabled")
        if surface == "web_shared" and enabled is not False:
            return source_session_id
        return None
    return None


async def _publish_pending_shared_turn(
    request: Request,
    campaign_id: str,
    payload: TurnRequest,
    gateway: EngineGateway,
) -> tuple[str | None, list[str]]:
    shared_session_id = await _shared_pending_session_id(gateway, campaign_id, payload)
    if not shared_session_id:
        return None, []
    try:
        target_actor_ids = await gateway.shared_pending_target_actor_ids(
            campaign_id,
            str(payload.actor_id or "").strip(),
        )
    except Exception:
        target_actor_ids = []
    target_actor_ids = [
        actor_id
        for actor_id in target_actor_ids
        if actor_id and actor_id != str(payload.actor_id or "").strip()
    ]
    if not target_actor_ids:
        return None, []
    pending_id = uuid4().hex
    delivered_any = False
    for target_actor_id in target_actor_ids:
        try:
            await request.app.state.realtime.publish_to_actor(
                campaign_id,
                target_actor_id,
                {
                    "type": "pending_shared_turn",
                    "actor_id": target_actor_id,
                    "session_id": shared_session_id,
                    "payload": {
                        "pending_id": pending_id,
                        "source_actor_id": str(payload.actor_id or "").strip(),
                        "source_actor_name": _linked_display_name(request),
                        "source_session_id": str(payload.session_id or "").strip() or None,
                        "action_text": str(payload.action or "").strip(),
                    },
                },
            )
            delivered_any = True
        except Exception:
            pass
    return (pending_id, target_actor_ids) if delivered_any else (None, [])


async def _clear_pending_mentions(
    request: Request,
    campaign_id: str,
    pending_id: str | None,
    target_actor_ids: list[str],
) -> None:
    pending_text = str(pending_id or "").strip()
    if not pending_text or not target_actor_ids:
        return
    for target_actor_id in target_actor_ids:
        try:
            await request.app.state.realtime.publish_to_actor(
                campaign_id,
                target_actor_id,
                {
                    "type": "pending_mention_clear",
                    "actor_id": target_actor_id,
                    "payload": {
                        "pending_id": pending_text,
                    },
                },
            )
        except Exception:
            pass


async def _clear_pending_shared_turn(
    request: Request,
    campaign_id: str,
    pending_id: str | None,
    target_actor_ids: list[str],
) -> None:
    pending_text = str(pending_id or "").strip()
    if not pending_text or not target_actor_ids:
        return
    for target_actor_id in target_actor_ids:
        try:
            await request.app.state.realtime.publish_to_actor(
                campaign_id,
                target_actor_id,
                {
                    "type": "pending_shared_turn_clear",
                    "actor_id": target_actor_id,
                    "payload": {
                        "pending_id": pending_text,
                    },
                },
            )
        except Exception:
            pass


@router.get("/health")
async def health() -> dict:
    return {"ok": True}


@router.get("/runtime")
async def runtime(request: Request) -> dict:
    out = {"gateway_backend": request.app.state.gateway_backend}
    settings = request.app.state.settings
    if out["gateway_backend"] == "tge":
        out["tge_completion_mode"] = settings.tge_completion_mode
        out["tge_llm_model"] = settings.tge_llm_model
        out["tge_llm_base_url"] = settings.tge_llm_base_url
        out["tge_ollama_keep_alive"] = settings.tge_ollama_keep_alive
        out["tge_runtime_probe_llm_default"] = bool(settings.tge_runtime_probe_llm)
    out["streaming_supported"] = settings.tge_completion_mode != "deterministic"
    return out


@router.get("/runtime/checks")
async def runtime_checks(
    request: Request,
    probe_llm: bool | None = None,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    settings = request.app.state.settings
    should_probe = bool(settings.tge_runtime_probe_llm) if probe_llm is None else bool(probe_llm)
    checks = await gateway.runtime_checks(probe_llm=should_probe)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "probe_llm": should_probe,
        "checks": checks,
    }


@router.get("/diagnostics/bundle")
async def diagnostics_bundle(
    request: Request,
    campaign_id: str | None = None,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    runtime_info = await runtime(request)
    runtime_check_info = await runtime_checks(request, None, gateway)
    payload: dict[str, object] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "runtime": runtime_info,
        "runtime_checks": runtime_check_info,
        "features": FEATURES,
    }
    if campaign_id:
        try:
            payload["campaign_id"] = campaign_id
            payload["campaign_debug_snapshot"] = await gateway.debug_snapshot(campaign_id)
        except KeyError as err:
            _not_found(err)
    return payload


@router.get("/features")
async def features() -> dict:
    return {"features": FEATURES}


@router.get("/dtm-link/status")
async def dtm_link_status(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    linked = get_linked_actor_from_request(request)
    prefix = str(getattr(settings, "dtm_command_prefix", "+") or "+").strip() or "+"
    if not dtm_link_enabled(settings):
        return JSONResponse(
            {
                "enabled": False,
                "linked": False,
                "actor_id": None,
                "display_name": "",
                "link_code": None,
                "command": "",
            }
        )
    if linked is not None:
        response = JSONResponse(
            {
                "enabled": True,
                "linked": True,
                "actor_id": linked.actor_id,
                "display_name": linked.display_name,
                "link_code": None,
                "command": "",
            }
        )
        response.delete_cookie(LINK_PENDING_COOKIE, path="/")
        return response

    pending_cookie = request.cookies.get(LINK_PENDING_COOKIE)
    row = get_or_create_pending_link(request.app, pending_cookie)
    actor_id = str(row.get("actor_id") or "").strip()
    display_name = str(row.get("display_name") or "").strip()
    if actor_id:
        session_cookie = issue_session_cookie_value(
            settings,
            actor_id=actor_id,
            display_name=display_name,
        )
        response = JSONResponse(
            {
                "enabled": True,
                "linked": True,
                "actor_id": actor_id,
                "display_name": display_name,
                "link_code": None,
                "command": "",
            }
        )
        response.set_cookie(
            LINK_SESSION_COOKIE,
            session_cookie,
            httponly=True,
            samesite="lax",
            path="/",
            max_age=60 * 60 * 24 * 30,
        )
        response.delete_cookie(LINK_PENDING_COOKIE, path="/")
        return response

    code = str(row.get("code") or "").strip()
    response = JSONResponse(
        {
            "enabled": True,
            "linked": False,
            "actor_id": None,
            "display_name": "",
            "link_code": code,
            "command": f"{prefix}zork link-account {code}",
        }
    )
    response.set_cookie(
        LINK_PENDING_COOKIE,
        code,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=60 * 60 * 12,
    )
    return response


@router.post("/dtm-link/confirm")
async def dtm_link_confirm(payload: DtmLinkConfirmRequest, request: Request) -> dict:
    settings = request.app.state.settings
    if not dtm_link_enabled(settings):
        raise HTTPException(status_code=404, detail="Discord link auth is not enabled.")
    provided_secret = str(request.headers.get(LINK_CONFIRM_HEADER) or "").strip()
    expected_secret = str(getattr(settings, "dtm_link_secret", "") or "").strip()
    if not provided_secret or provided_secret != expected_secret:
        raise HTTPException(status_code=403, detail="Invalid link secret.")
    row = confirm_pending_link(
        request.app,
        code=payload.code,
        actor_id=payload.actor_id,
        display_name=payload.display_name,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown or expired link code.")
    return {
        "ok": True,
        "code": str(row.get("code") or ""),
        "actor_id": str(row.get("actor_id") or ""),
        "display_name": str(row.get("display_name") or ""),
    }


@router.post("/internal/campaigns/{campaign_id}/turns/refresh")
async def internal_turn_refresh(
    campaign_id: str,
    payload: InternalTurnRefreshRequest,
    request: Request,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    settings = request.app.state.settings
    provided_secret = str(request.headers.get(LINK_CONFIRM_HEADER) or "").strip()
    expected_secret = str(getattr(settings, "dtm_link_secret", "") or "").strip()
    if not provided_secret or provided_secret != expected_secret:
        raise HTTPException(status_code=403, detail="Invalid link secret.")
    try:
        await gateway.debug_snapshot(campaign_id)
    except KeyError as err:
        _not_found(err)
    await request.app.state.realtime.publish(
        campaign_id,
        {
            "type": "turn_refresh",
            "actor_id": str(payload.actor_id or "").strip() or None,
            "session_id": str(payload.session_id or "").strip() or None,
            "payload": {
                "actor_id": str(payload.actor_id or "").strip() or None,
                "session_id": str(payload.session_id or "").strip() or None,
                "source": "discord",
            },
        },
    )
    return {"ok": True}


@router.get("/campaigns")
async def list_campaigns(
    request: Request,
    namespace: str = "all",
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    linked_actor = _linked_actor_id(request)
    if dtm_link_enabled(request.app.state.settings) and linked_actor:
        rows = await gateway.list_campaigns_for_actor(linked_actor)
    else:
        rows = await gateway.list_campaigns(namespace)
    return {"campaigns": [row.model_dump() for row in rows]}


@router.post("/campaigns")
async def create_campaign(
    payload: CampaignCreateRequest,
    request: Request,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    actor_id = _linked_actor_id(request) or payload.actor_id
    namespace = payload.namespace
    if str(namespace or "").strip().lower() in {"", "*", "all"}:
        namespace = "default"
    row = await gateway.create_campaign(namespace, payload.name, actor_id)
    return {"campaign": row.model_dump()}


@router.get("/campaigns/{campaign_id}/sessions")
async def list_sessions(campaign_id: str, gateway: EngineGateway = Depends(get_gateway)) -> dict:
    try:
        rows = await gateway.list_sessions(campaign_id)
    except KeyError as err:
        _not_found(err)
    return {"sessions": rows}


@router.post("/campaigns/{campaign_id}/sessions")
async def create_or_update_session(
    campaign_id: str,
    payload: SessionCreateRequest,
    request: Request,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    try:
        row = await gateway.create_or_update_session(
            campaign_id,
            surface=payload.surface,
            surface_key=payload.surface_key,
            surface_guild_id=payload.surface_guild_id,
            surface_channel_id=payload.surface_channel_id,
            surface_thread_id=payload.surface_thread_id,
            enabled=payload.enabled,
            metadata=payload.metadata,
        )
    except KeyError as err:
        _not_found(err)
    except ValueError as err:
        _bad_request(err)
    await request.app.state.realtime.publish(campaign_id, {"type": "session", "payload": row})
    return {"session": row}


@router.patch("/campaigns/{campaign_id}/sessions/{session_id}")
async def update_session(
    campaign_id: str,
    session_id: str,
    payload: SessionUpdateRequest,
    request: Request,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    try:
        row = await gateway.update_session(
            campaign_id,
            session_id,
            enabled=payload.enabled,
            metadata=payload.metadata,
        )
    except KeyError as err:
        _not_found(err)
    await request.app.state.realtime.publish(campaign_id, {"type": "session", "payload": row})
    return {"session": row}


async def _publish_turn_events(
    request: Request,
    campaign_id: str,
    result,
    gateway,
    *,
    action_text: str | None = None,
) -> None:
    """Publish turn, media, and timer events via the realtime layer."""
    await request.app.state.realtime.publish(
        campaign_id,
        {
            "type": "turn",
            "session_id": result.session_id,
            "actor_id": result.actor_id,
            "payload": {
                **result.model_dump(),
                "action_text": str(action_text or "").strip() or None,
            },
        },
    )
    if result.image_prompt:
        await request.app.state.realtime.publish(
            campaign_id,
            {
                "type": "media",
                "session_id": result.session_id,
                "actor_id": result.actor_id,
                "payload": {
                    "image_prompt": result.image_prompt,
                    "actor_id": result.actor_id,
                    "session_id": result.session_id,
                    "turn_visibility": result.turn_visibility,
                },
            },
        )
    try:
        timers = await gateway.get_timers(campaign_id)
        await request.app.state.realtime.publish(
            campaign_id,
            {
                "type": "timers",
                "session_id": result.session_id,
                "actor_id": result.actor_id,
                "payload": {
                    **timers,
                    "turn_visibility": result.turn_visibility,
                    "actor_id": result.actor_id,
                    "session_id": result.session_id,
                },
            },
        )
    except KeyError:
        pass


@router.post("/campaigns/{campaign_id}/turns")
async def submit_turn(
    campaign_id: str,
    payload: TurnRequest,
    request: Request,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    payload.actor_id = _coerced_actor_id(request, payload.actor_id)
    pending_id, pending_targets = await _publish_pending_mentions(request, campaign_id, payload)
    shared_pending_id, shared_pending_targets = await _publish_pending_shared_turn(
        request,
        campaign_id,
        payload,
        gateway,
    )
    try:
        result = await gateway.submit_turn(campaign_id, payload)
    except KeyError as err:
        await _clear_pending_mentions(request, campaign_id, pending_id, pending_targets)
        await _clear_pending_shared_turn(
            request,
            campaign_id,
            shared_pending_id,
            shared_pending_targets,
        )
        _not_found(err)
    except ValueError as err:
        await _clear_pending_mentions(request, campaign_id, pending_id, pending_targets)
        await _clear_pending_shared_turn(
            request,
            campaign_id,
            shared_pending_id,
            shared_pending_targets,
        )
        _bad_request(err)
    except Exception:
        await _clear_pending_mentions(request, campaign_id, pending_id, pending_targets)
        await _clear_pending_shared_turn(
            request,
            campaign_id,
            shared_pending_id,
            shared_pending_targets,
        )
        raise
    await _publish_turn_events(
        request,
        campaign_id,
        result,
        gateway,
        action_text=payload.action,
    )
    await gateway.queue_discord_mirror(
        campaign_id,
        result,
        actor_display_name=_linked_display_name(request),
        action_text=payload.action,
    )
    await _clear_pending_mentions(request, campaign_id, pending_id, pending_targets)
    await _clear_pending_shared_turn(
        request,
        campaign_id,
        shared_pending_id,
        shared_pending_targets,
    )
    return result.model_dump()


@router.post("/campaigns/{campaign_id}/turns/stream")
async def submit_turn_stream(
    campaign_id: str,
    payload: TurnRequest,
    request: Request,
    gateway: EngineGateway = Depends(get_gateway),
) -> StreamingResponse:
    from app.services.schemas import TurnResult as TurnResultModel
    payload.actor_id = _coerced_actor_id(request, payload.actor_id)
    pending_id, pending_targets = await _publish_pending_mentions(request, campaign_id, payload)
    shared_pending_id, shared_pending_targets = await _publish_pending_shared_turn(
        request,
        campaign_id,
        payload,
        gateway,
    )

    # Collect all events *before* streaming so turn execution and realtime
    # publishing are not cancelled if the client disconnects mid-stream.
    collected_events: list[tuple[str, dict]] = []
    final_result: TurnResultModel | None = None
    error_event: str | None = None

    try:
        async for event in gateway.submit_turn_stream(campaign_id, payload):
            event_type = event.get("event", "message")
            event_data = event.get("data", {})
            collected_events.append((event_type, event_data))
            if event_type == "phase":
                try:
                    await request.app.state.realtime.publish(
                        campaign_id,
                        {
                            "type": "turn_progress",
                            "session_id": payload.session_id,
                            "actor_id": payload.actor_id,
                            "payload": event_data,
                        },
                    )
                except Exception:
                    pass  # best-effort
            if event_type == "complete":
                final_result = TurnResultModel(**event_data)
            elif event_type == "error":
                break
    except KeyError as err:
        await _clear_pending_mentions(request, campaign_id, pending_id, pending_targets)
        await _clear_pending_shared_turn(
            request,
            campaign_id,
            shared_pending_id,
            shared_pending_targets,
        )
        error_event = f"event: error\ndata: {json.dumps({'message': str(err)})}\n\n"
    except ValueError as err:
        await _clear_pending_mentions(request, campaign_id, pending_id, pending_targets)
        await _clear_pending_shared_turn(
            request,
            campaign_id,
            shared_pending_id,
            shared_pending_targets,
        )
        error_event = f"event: error\ndata: {json.dumps({'message': str(err)})}\n\n"
    except Exception as err:
        await _clear_pending_mentions(request, campaign_id, pending_id, pending_targets)
        await _clear_pending_shared_turn(
            request,
            campaign_id,
            shared_pending_id,
            shared_pending_targets,
        )
        error_event = f"event: error\ndata: {json.dumps({'message': str(err)})}\n\n"

    # Publish realtime events unconditionally — not tied to client connection.
    if final_result:
        await _publish_turn_events(
            request,
            campaign_id,
            final_result,
            gateway,
            action_text=payload.action,
        )
        await gateway.queue_discord_mirror(
            campaign_id,
            final_result,
            actor_display_name=_linked_display_name(request),
            action_text=payload.action,
        )
    await _clear_pending_mentions(request, campaign_id, pending_id, pending_targets)
    await _clear_pending_shared_turn(
        request,
        campaign_id,
        shared_pending_id,
        shared_pending_targets,
    )

    async def _sse():
        if error_event:
            yield error_event
            return
        for event_type, event_data in collected_events:
            yield f"event: {event_type}\ndata: {json.dumps(event_data)}\n\n"

    return StreamingResponse(
        _sse(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/campaigns/{campaign_id}/export")
async def campaign_export(
    campaign_id: str,
    export_type: str = "full",
    raw_format: str = "jsonl",
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    try:
        return await gateway.campaign_export(
            campaign_id,
            export_type=export_type,
            raw_format=raw_format,
        )
    except KeyError as err:
        _not_found(err)
    except ValueError as err:
        _bad_request(err)


@router.get("/campaigns/{campaign_id}/flags")
async def get_campaign_flags(campaign_id: str, gateway: EngineGateway = Depends(get_gateway)) -> dict:
    try:
        return await gateway.get_campaign_flags(campaign_id)
    except KeyError as err:
        _not_found(err)


@router.post("/campaigns/{campaign_id}/flags")
async def update_campaign_flags(
    campaign_id: str,
    payload: CampaignFlagsUpdate,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    try:
        return await gateway.update_campaign_flags(
            campaign_id,
            guardrails=payload.guardrails,
            on_rails=payload.on_rails,
            timed_events=payload.timed_events,
            difficulty=payload.difficulty,
            speed_multiplier=payload.speed_multiplier,
            clock_start_day_of_week=payload.clock_start_day_of_week,
            clock_type=payload.clock_type,
        )
    except KeyError as err:
        _not_found(err)
    except ValueError as err:
        _bad_request(err)


@router.get("/campaigns/{campaign_id}/source-materials")
async def get_source_materials(campaign_id: str, gateway: EngineGateway = Depends(get_gateway)) -> dict:
    try:
        return await gateway.get_source_materials(campaign_id)
    except KeyError as err:
        _not_found(err)


@router.post("/campaigns/{campaign_id}/source-materials")
async def ingest_source_material(
    campaign_id: str,
    payload: SourceMaterialIngest,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    try:
        return await gateway.ingest_source_material(campaign_id, payload)
    except KeyError as err:
        _not_found(err)
    except ValueError as err:
        _bad_request(err)


@router.get("/campaigns/{campaign_id}/campaign-rules")
async def get_campaign_rules(
    campaign_id: str,
    key: str | None = None,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    try:
        return await gateway.get_campaign_rules(campaign_id, key=key)
    except KeyError as err:
        _not_found(err)


@router.post("/campaigns/{campaign_id}/campaign-rules")
async def update_campaign_rule(
    campaign_id: str,
    payload: CampaignRuleUpdate,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    try:
        return await gateway.update_campaign_rule(campaign_id, payload)
    except KeyError as err:
        _not_found(err)
    except ValueError as err:
        _bad_request(err)


@router.post("/campaigns/{campaign_id}/rewind")
async def rewind_to_turn(
    campaign_id: str,
    target_turn_id: int,
    request: Request,
    session_id: str | None = None,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    try:
        result = await gateway.rewind_to_turn(
            campaign_id,
            target_turn_id,
            session_id=str(session_id or "").strip() or None,
            actor_id=_linked_actor_id(request),
        )
    except KeyError as err:
        _not_found(err)
    except ValueError as err:
        _bad_request(err)
    await request.app.state.realtime.publish(
        campaign_id,
        {
            "type": "turn_refresh",
            "session_id": str(result.get("session_id") or "").strip() or None,
            "actor_id": _linked_actor_id(request),
            "payload": {
                "target_turn_id": int(result.get("target_turn_id") or 0),
                "resolved_turn_id": int(result.get("resolved_turn_id") or 0),
                "session_id": str(result.get("session_id") or "").strip() or None,
                "source": "webui",
                "operation": "rewind",
            },
        },
    )
    return result


@router.post("/campaigns/{campaign_id}/timers/cancel")
async def cancel_pending_timer(campaign_id: str, gateway: EngineGateway = Depends(get_gateway)) -> dict:
    try:
        return await gateway.cancel_pending_timer(campaign_id)
    except KeyError as err:
        _not_found(err)


@router.get("/campaigns/{campaign_id}/player-statistics")
async def get_player_statistics(
    campaign_id: str,
    actor_id: str,
    request: Request,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    actor_id = _coerced_actor_id(request, actor_id)
    try:
        return await gateway.get_player_statistics(campaign_id, actor_id)
    except KeyError as err:
        _not_found(err)


@router.get("/campaigns/{campaign_id}/player-attributes")
async def get_player_attributes(
    campaign_id: str,
    actor_id: str,
    request: Request,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    actor_id = _coerced_actor_id(request, actor_id)
    try:
        return await gateway.get_player_attributes(campaign_id, actor_id)
    except KeyError as err:
        _not_found(err)


@router.post("/campaigns/{campaign_id}/player-attributes")
async def set_player_attribute(
    campaign_id: str,
    payload: AttributeSetRequest,
    request: Request,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    payload.actor_id = _coerced_actor_id(request, payload.actor_id)
    try:
        return await gateway.set_player_attribute(campaign_id, payload.actor_id, payload.attribute, payload.value)
    except KeyError as err:
        _not_found(err)
    except ValueError as err:
        _bad_request(err)


@router.post("/campaigns/{campaign_id}/player-name")
async def rename_player_character(
    campaign_id: str,
    payload: PlayerNameUpdateRequest,
    request: Request,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    payload.actor_id = _coerced_actor_id(request, payload.actor_id)
    try:
        return await gateway.rename_player_character(campaign_id, payload.actor_id, payload.name)
    except KeyError as err:
        _not_found(err)
    except ValueError as err:
        _bad_request(err)


@router.post("/campaigns/{campaign_id}/level-up")
async def level_up_player(
    campaign_id: str,
    payload: LevelUpRequest,
    request: Request,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    payload.actor_id = _coerced_actor_id(request, payload.actor_id)
    try:
        return await gateway.level_up_player(campaign_id, payload.actor_id)
    except KeyError as err:
        _not_found(err)


@router.get("/campaigns/{campaign_id}/recent-turns")
async def get_recent_turns(
    campaign_id: str,
    limit: int = 30,
    offset: int = 0,
    request: Request = None,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    if offset < 0 or limit < 1:
        _bad_request(ValueError("limit must be >= 1 and offset must be >= 0"))
    try:
        return await gateway.get_recent_turns(
            campaign_id,
            limit=limit,
            offset=offset,
            actor_id=_linked_actor_id(request),
        )
    except KeyError as err:
        _not_found(err)


@router.patch("/campaigns/{campaign_id}/turns/{turn_id}")
async def edit_turn(
    campaign_id: str,
    turn_id: int,
    payload: TurnEditRequest,
    request: Request,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    try:
        result = await gateway.edit_turn(
            campaign_id,
            turn_id,
            content=payload.content,
            actor_id=_linked_actor_id(request),
        )
    except KeyError as err:
        _not_found(err)
    except ValueError as err:
        _bad_request(err)
    await request.app.state.realtime.publish(
        campaign_id,
        {
            "type": "turn_refresh",
            "actor_id": result.get("actor_id"),
            "session_id": result.get("session_id"),
            "payload": {
                "turn_id": int(result.get("turn_id") or 0),
                "actor_id": result.get("actor_id"),
                "session_id": result.get("session_id"),
                "source": "webui",
                "operation": "edit",
            },
        },
    )
    return result


@router.delete("/campaigns/{campaign_id}/turns/{turn_id}")
async def delete_turn(
    campaign_id: str,
    turn_id: int,
    request: Request,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    try:
        result = await gateway.delete_turn(
            campaign_id,
            turn_id,
            actor_id=_linked_actor_id(request),
        )
    except KeyError as err:
        _not_found(err)
    await request.app.state.realtime.publish(
        campaign_id,
        {
            "type": "turn_refresh",
            "actor_id": result.get("actor_id"),
            "session_id": result.get("session_id"),
            "payload": {
                "turn_id": int(result.get("turn_id") or 0),
                "actor_id": result.get("actor_id"),
                "session_id": result.get("session_id"),
                "source": "webui",
                "operation": "delete",
            },
        },
    )
    return result


@router.get("/campaigns/{campaign_id}/persona")
async def get_campaign_persona(campaign_id: str, gateway: EngineGateway = Depends(get_gateway)) -> dict:
    try:
        return await gateway.get_campaign_persona(campaign_id)
    except KeyError as err:
        _not_found(err)


@router.post("/campaigns/{campaign_id}/persona")
async def set_campaign_persona(
    campaign_id: str,
    payload: PersonaUpdateRequest,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    try:
        return await gateway.set_campaign_persona(campaign_id, payload.persona)
    except KeyError as err:
        _not_found(err)
    except ValueError as err:
        _bad_request(err)


@router.get("/campaigns/{campaign_id}/puzzle/hint")
async def get_puzzle_hint(campaign_id: str, gateway: EngineGateway = Depends(get_gateway)) -> dict:
    try:
        return await gateway.get_puzzle_hint(campaign_id)
    except KeyError as err:
        _not_found(err)


@router.post("/campaigns/{campaign_id}/puzzle/answer")
async def submit_puzzle_answer(
    campaign_id: str,
    payload: PuzzleAnswerRequest,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    try:
        return await gateway.submit_puzzle_answer(campaign_id, payload.answer)
    except KeyError as err:
        _not_found(err)
    except ValueError as err:
        _bad_request(err)


@router.post("/campaigns/{campaign_id}/minigame/move")
async def submit_minigame_move(
    campaign_id: str,
    payload: MinigameMoveRequest,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    try:
        return await gateway.submit_minigame_move(campaign_id, payload.move)
    except KeyError as err:
        _not_found(err)
    except ValueError as err:
        _bad_request(err)


@router.get("/campaigns/{campaign_id}/minigame/board")
async def get_minigame_board(campaign_id: str, gateway: EngineGateway = Depends(get_gateway)) -> dict:
    try:
        return await gateway.get_minigame_board(campaign_id)
    except KeyError as err:
        _not_found(err)


@router.get("/campaigns/{campaign_id}/setup")
async def get_setup_status(campaign_id: str, gateway: EngineGateway = Depends(get_gateway)) -> dict:
    try:
        return await gateway.is_in_setup_mode(campaign_id)
    except KeyError as err:
        _not_found(err)


@router.post("/campaigns/{campaign_id}/setup/start")
async def start_campaign_setup(
    campaign_id: str,
    payload: SetupStartRequest,
    request: Request,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    payload.actor_id = _coerced_actor_id(request, payload.actor_id)
    try:
        return await gateway.start_campaign_setup(
            campaign_id,
            actor_id=payload.actor_id,
            on_rails=payload.on_rails,
            attachment_text=payload.attachment_text,
        )
    except KeyError as err:
        _not_found(err)
    except ValueError as err:
        _bad_request(err)


@router.post("/campaigns/{campaign_id}/setup/message")
async def handle_setup_message(
    campaign_id: str,
    payload: SetupMessageRequest,
    request: Request,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    payload.actor_id = _coerced_actor_id(request, payload.actor_id)
    try:
        return await gateway.handle_setup_message(campaign_id, payload.actor_id, payload.message)
    except KeyError as err:
        _not_found(err)
    except ValueError as err:
        _bad_request(err)


@router.get("/campaigns/{campaign_id}/scene-images")
async def get_scene_images(campaign_id: str, gateway: EngineGateway = Depends(get_gateway)) -> dict:
    try:
        return await gateway.get_scene_images(campaign_id)
    except KeyError as err:
        _not_found(err)


@router.get("/campaigns/{campaign_id}/literary-styles")
async def get_literary_styles(campaign_id: str, gateway: EngineGateway = Depends(get_gateway)) -> dict:
    try:
        return await gateway.get_literary_styles(campaign_id)
    except KeyError as err:
        _not_found(err)


@router.post("/campaigns/{campaign_id}/sms/cancel")
async def cancel_sms_deliveries(campaign_id: str, gateway: EngineGateway = Depends(get_gateway)) -> dict:
    try:
        return await gateway.cancel_sms_deliveries(campaign_id)
    except KeyError as err:
        _not_found(err)


@router.post("/campaigns/{campaign_id}/sms/schedule")
async def schedule_sms_delivery(
    campaign_id: str,
    payload: ScheduledSmsRequest,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    try:
        return await gateway.schedule_sms_delivery(
            campaign_id,
            thread=payload.thread,
            sender=payload.sender,
            recipient=payload.recipient,
            message=payload.message,
            delay_seconds=payload.delay_seconds,
        )
    except KeyError as err:
        _not_found(err)
    except ValueError as err:
        _bad_request(err)


@router.post("/campaigns/{campaign_id}/source-materials/search")
async def search_source_material(
    campaign_id: str,
    payload: SourceMaterialSearchRequest,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    try:
        return await gateway.search_source_material(
            campaign_id,
            payload.query,
            document_key=payload.document_key,
            top_k=payload.top_k,
        )
    except KeyError as err:
        _not_found(err)


@router.post("/campaigns/{campaign_id}/source-materials/digest")
async def ingest_source_material_with_digest(
    campaign_id: str,
    payload: SourceMaterialDigestIngest,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    try:
        return await gateway.ingest_source_material_with_digest(campaign_id, payload)
    except KeyError as err:
        _not_found(err)
    except ValueError as err:
        _bad_request(err)


@router.get("/campaigns/{campaign_id}/source-materials/browse")
async def browse_source_keys(
    campaign_id: str,
    wildcard: str = "*",
    document_key: str | None = None,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    try:
        return await gateway.browse_source_keys(campaign_id, wildcard=wildcard, document_key=document_key)
    except KeyError as err:
        _not_found(err)


@router.post("/campaigns/{campaign_id}/roster/portrait")
async def record_character_portrait(
    campaign_id: str,
    payload: CharacterPortraitRequest,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    try:
        return await gateway.record_character_portrait(campaign_id, payload.character_slug, payload.image_url)
    except KeyError as err:
        _not_found(err)
    except ValueError as err:
        _bad_request(err)


@router.delete("/campaigns/{campaign_id}")
async def delete_campaign(
    campaign_id: str,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    try:
        return await gateway.delete_campaign(campaign_id)
    except KeyError as err:
        _not_found(err)


@router.get("/campaigns/{campaign_id}/story")
async def get_story_state(campaign_id: str, gateway: EngineGateway = Depends(get_gateway)) -> dict:
    try:
        return await gateway.get_story_state(campaign_id)
    except KeyError as err:
        _not_found(err)


@router.get("/campaigns/{campaign_id}/chapters")
async def get_chapter_list(campaign_id: str, gateway: EngineGateway = Depends(get_gateway)) -> dict:
    try:
        return await gateway.get_chapter_list(campaign_id)
    except KeyError as err:
        _not_found(err)


@router.get("/campaigns/{campaign_id}/map")
async def get_map(
    campaign_id: str,
    actor_id: str,
    request: Request,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    actor_id = _coerced_actor_id(request, actor_id)
    try:
        data = await gateway.get_map(campaign_id, actor_id)
    except KeyError as err:
        _not_found(err)
    return {"map": data}


@router.get("/campaigns/{campaign_id}/timers")
async def get_timers(campaign_id: str, gateway: EngineGateway = Depends(get_gateway)) -> dict:
    try:
        return await gateway.get_timers(campaign_id)
    except KeyError as err:
        _not_found(err)


@router.get("/campaigns/{campaign_id}/calendar")
async def get_calendar(
    campaign_id: str,
    request: Request,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    try:
        return await gateway.get_calendar(
            campaign_id,
            actor_id=_linked_actor_id(request),
        )
    except KeyError as err:
        _not_found(err)


@router.post("/campaigns/{campaign_id}/calendar/{event_key}/visibility")
async def update_calendar_event_visibility(
    campaign_id: str,
    event_key: str,
    payload: CalendarVisibilityUpdateRequest,
    request: Request,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    try:
        return await gateway.update_calendar_event_visibility(
            campaign_id,
            event_key,
            visibility=payload.visibility,
            actor_id=_linked_actor_id(request),
        )
    except KeyError as err:
        _not_found(err)
    except ValueError as err:
        _bad_request(err)


@router.get("/campaigns/{campaign_id}/roster")
async def get_roster(campaign_id: str, gateway: EngineGateway = Depends(get_gateway)) -> dict:
    try:
        return await gateway.get_roster(campaign_id)
    except KeyError as err:
        _not_found(err)


@router.post("/campaigns/{campaign_id}/roster/upsert")
async def upsert_roster_character(
    campaign_id: str,
    payload: RosterUpsertRequest,
    request: Request,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    try:
        result = await gateway.upsert_roster_character(
            campaign_id,
            slug=payload.slug,
            name=payload.name,
            location=payload.location,
            status=payload.status,
            player=payload.player,
            fields=payload.fields,
        )
        roster = await gateway.get_roster(campaign_id)
    except KeyError as err:
        _not_found(err)
    except ValueError as err:
        _bad_request(err)
    await request.app.state.realtime.publish(campaign_id, {"type": "roster", "payload": roster})
    return result


@router.post("/campaigns/{campaign_id}/roster/remove")
async def remove_roster_character(
    campaign_id: str,
    payload: RosterRemoveRequest,
    request: Request,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    try:
        result = await gateway.remove_roster_character(
            campaign_id,
            payload.slug,
            player=payload.player,
        )
        roster = await gateway.get_roster(campaign_id)
    except KeyError as err:
        _not_found(err)
    except ValueError as err:
        _bad_request(err)
    await request.app.state.realtime.publish(campaign_id, {"type": "roster", "payload": roster})
    return result


@router.get("/campaigns/{campaign_id}/player-state")
async def get_player_state(
    campaign_id: str,
    actor_id: str,
    request: Request,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    actor_id = _coerced_actor_id(request, actor_id)
    try:
        data = await gateway.get_player_state(campaign_id, actor_id)
    except KeyError as err:
        _not_found(err)
    return {"player_state": data}


@router.get("/campaigns/{campaign_id}/media")
async def get_media(
    campaign_id: str,
    actor_id: str | None = None,
    request: Request = None,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    actor_id = _coerced_actor_id(request, actor_id) if request is not None else actor_id
    try:
        data = await gateway.get_media(campaign_id, actor_id)
    except KeyError as err:
        _not_found(err)
    return {"media": data}


@router.post("/campaigns/{campaign_id}/media/avatar/generate")
async def generate_avatar(
    campaign_id: str,
    payload: AvatarGenerateRequest,
    request: Request,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    payload.actor_id = _coerced_actor_id(request, payload.actor_id)
    """Generate an avatar image from a prompt and set it as the pending avatar."""
    settings = request.app.state.settings
    backend = (settings.image_backend or "none").strip().lower()
    if backend == "none":
        raise HTTPException(status_code=400, detail="No image backend configured.")

    # Generate the image
    orchestrator = getattr(request.app.state, "gpu_orchestrator", None)
    if orchestrator:
        await orchestrator.before_image_generation()

    if backend == "diffusers":
        client = getattr(request.app.state, "diffusers_client", None)
        if client is None:
            raise HTTPException(status_code=400, detail="Diffusers client not initialized.")
        result = await client.generate(
            prompt=payload.prompt,
            model_id=settings.diffusers_model,
            width=settings.image_width,
            height=settings.image_height,
            steps=settings.image_steps,
            guidance_scale=settings.image_guidance_scale,
        )
        job_id = result.get("job_id")
        if not job_id:
            raise HTTPException(status_code=500, detail="Image generation failed to start.")
        return {"job_id": job_id, "status": "pending", "actor_id": payload.actor_id}
    elif backend == "comfyui":
        client = getattr(request.app.state, "comfyui_client", None)
        if client is None:
            raise HTTPException(status_code=400, detail="ComfyUI client not initialized.")
        prompt_id = await client.queue_prompt(
            prompt=payload.prompt,
            width=settings.image_width,
            height=settings.image_height,
            steps=settings.image_steps,
            cfg=settings.image_guidance_scale,
        )
        return {"job_id": prompt_id, "status": "pending", "backend": "comfyui", "actor_id": payload.actor_id}
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported image backend: {backend}")


@router.post("/campaigns/{campaign_id}/media/avatar/commit")
async def commit_avatar(
    campaign_id: str,
    request: Request,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    """After generation completes, commit the image as the pending avatar."""
    body = await request.json()
    actor_id = _coerced_actor_id(request, body.get("actor_id", ""))
    image_url = body.get("image_url", "")
    prompt = body.get("prompt", "")
    if not actor_id or not image_url:
        raise HTTPException(status_code=400, detail="actor_id and image_url are required.")
    try:
        data = await gateway.record_pending_avatar(campaign_id, actor_id, image_url, prompt=prompt)
    except KeyError as err:
        _not_found(err)
    await request.app.state.realtime.publish(
        campaign_id,
        {"type": "media", "payload": {"action": "avatar_generated", "actor_id": actor_id, "image_url": image_url}},
    )
    return data


@router.post("/campaigns/{campaign_id}/media/avatar/accept")
async def accept_pending_avatar(
    campaign_id: str,
    payload: AvatarActionRequest,
    request: Request,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    payload.actor_id = _coerced_actor_id(request, payload.actor_id)
    try:
        data = await gateway.accept_pending_avatar(campaign_id, payload.actor_id)
    except KeyError as err:
        _not_found(err)
    await request.app.state.realtime.publish(
        campaign_id,
        {"type": "media", "payload": {"action": "avatar_accept", **data}},
    )
    return data


@router.post("/campaigns/{campaign_id}/media/avatar/decline")
async def decline_pending_avatar(
    campaign_id: str,
    payload: AvatarActionRequest,
    request: Request,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    payload.actor_id = _coerced_actor_id(request, payload.actor_id)
    try:
        data = await gateway.decline_pending_avatar(campaign_id, payload.actor_id)
    except KeyError as err:
        _not_found(err)
    await request.app.state.realtime.publish(
        campaign_id,
        {"type": "media", "payload": {"action": "avatar_decline", **data}},
    )
    return data


@router.post("/campaigns/{campaign_id}/memory/search")
async def memory_search(campaign_id: str, payload: MemorySearchRequest, gateway: EngineGateway = Depends(get_gateway)) -> dict:
    try:
        return await gateway.memory_search(campaign_id, payload.queries, payload.category, search_within_turn_ids=payload.search_within_turn_ids)
    except KeyError as err:
        _not_found(err)


@router.post("/campaigns/{campaign_id}/memory/terms")
async def memory_terms(campaign_id: str, payload: MemoryTermsRequest, gateway: EngineGateway = Depends(get_gateway)) -> dict:
    try:
        return await gateway.memory_terms(campaign_id, payload.wildcard)
    except KeyError as err:
        _not_found(err)


@router.post("/campaigns/{campaign_id}/memory/turn")
async def memory_turn(campaign_id: str, payload: MemoryTurnRequest, gateway: EngineGateway = Depends(get_gateway)) -> dict:
    try:
        return await gateway.memory_turn(campaign_id, payload.turn_id)
    except KeyError as err:
        _not_found(err)


@router.post("/campaigns/{campaign_id}/memory/store")
async def memory_store(campaign_id: str, payload: MemoryStoreRequest, gateway: EngineGateway = Depends(get_gateway)) -> dict:
    try:
        return await gateway.memory_store(campaign_id, payload)
    except KeyError as err:
        _not_found(err)


@router.post("/campaigns/{campaign_id}/sms/list")
async def sms_list(campaign_id: str, payload: SmsListRequest, gateway: EngineGateway = Depends(get_gateway)) -> dict:
    try:
        return await gateway.sms_list(campaign_id, payload.wildcard)
    except KeyError as err:
        _not_found(err)


@router.post("/campaigns/{campaign_id}/sms/read")
async def sms_read(
    campaign_id: str,
    payload: SmsReadRequest,
    request: Request,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    payload.viewer_actor_id = _coerced_actor_id(request, payload.viewer_actor_id)
    try:
        return await gateway.sms_read(campaign_id, payload.thread, payload.limit, viewer_actor_id=payload.viewer_actor_id)
    except KeyError as err:
        _not_found(err)


@router.post("/campaigns/{campaign_id}/sms/write")
async def sms_write(
    campaign_id: str,
    payload: SmsWriteRequest,
    request: Request,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    try:
        data = await gateway.sms_write(campaign_id, payload.thread, payload.sender, payload.recipient, payload.message)
    except KeyError as err:
        _not_found(err)
    await request.app.state.realtime.publish(campaign_id, {"type": "sms", "payload": data})
    return data


@router.get("/campaigns/{campaign_id}/debug/snapshot")
async def debug_snapshot(campaign_id: str, gateway: EngineGateway = Depends(get_gateway)) -> dict:
    try:
        return await gateway.debug_snapshot(campaign_id)
    except KeyError as err:
        _not_found(err)


@router.get("/settings")
async def get_settings(
    request: Request,
    campaign_id: str | None = None,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    settings = request.app.state.settings
    effective = await gateway.effective_llm_settings(campaign_id=str(campaign_id or "").strip() or None)
    return {
        "completion_mode": effective.get("completion_mode") or settings.tge_completion_mode,
        "base_url": effective.get("base_url") or settings.tge_llm_base_url,
        "model": effective.get("model") or settings.tge_llm_model,
        "temperature": effective.get("temperature", settings.tge_llm_temperature),
        "max_tokens": effective.get("max_tokens", settings.tge_llm_max_tokens),
        "timeout_seconds": effective.get("timeout_seconds", settings.tge_llm_timeout_seconds),
        "keep_alive": effective.get("keep_alive") or settings.tge_ollama_keep_alive,
        "ollama_options": effective.get("ollama_options") or {},
        "gateway_backend": settings.gateway_backend,
        "locked": bool(settings.tge_sync_with_dtm),
        "lock_message": (
            "LLM settings are managed by DTM while sync_zork_backend is enabled. "
            "Use Discord-side backend controls instead."
            if settings.tge_sync_with_dtm
            else ""
        ),
    }


@router.post("/settings")
async def update_settings(
    payload: LLMSettingsUpdate,
    request: Request,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    if request.app.state.gateway_backend != "tge":
        raise HTTPException(status_code=400, detail="LLM settings only available with tge backend.")
    from app.services.tge_gateway import TextGameEngineGateway

    if not isinstance(gateway, TextGameEngineGateway):
        raise HTTPException(status_code=400, detail="Gateway does not support reconfiguration.")
    if request.app.state.settings.tge_sync_with_dtm:
        raise HTTPException(
            status_code=400,
            detail="LLM settings are managed by DTM while sync_zork_backend is enabled.",
        )
    raw = payload.model_dump()
    merged = {}
    for k, v in raw.items():
        if v is None:
            continue
        # treat empty/whitespace-only strings as "not provided"
        if isinstance(v, str) and not v.strip():
            continue
        merged[k] = v
    if not merged:
        raise HTTPException(status_code=400, detail="No settings provided.")
    try:
        result = gateway.reconfigure_llm(merged)
    except ValueError as err:
        _bad_request(err)
    # Persist settings to SQLite so they survive restarts.
    from app.settings import persist_settings
    persist_settings(request.app.state.settings)
    return result


def _fetch_ollama_models(url: str) -> dict:
    """Blocking helper — run via asyncio.to_thread to avoid stalling the event loop."""
    req = urllib_request.Request(url, method="GET")
    with urllib_request.urlopen(req, timeout=5) as response:  # noqa: S310
        raw = response.read().decode("utf-8", errors="replace")
    data = json.loads(raw)
    models = []
    for m in data.get("models", []):
        models.append({
            "name": m.get("name", ""),
            "size": m.get("size"),
            "modified_at": m.get("modified_at"),
        })
    return {"models": models, "reachable": True}


@router.get("/ollama/models")
async def list_ollama_models(request: Request) -> dict:
    settings = request.app.state.settings
    base_url = settings.tge_llm_base_url.rstrip("/")
    # Strip known path suffixes so we get the Ollama root.
    # Users may configure base_url as "http://host:11434/v1" (for openai compat)
    # or "http://host:11434" (native ollama).  The /api/tags endpoint lives on root.
    for suffix in ("/v1", "/api"):
        if base_url.endswith(suffix):
            base_url = base_url[: -len(suffix)]
            break
    url = f"{base_url}/api/tags"
    try:
        return await asyncio.to_thread(_fetch_ollama_models, url)
    except Exception:
        return {"models": [], "reachable": False}


# ---------------------------------------------------------------------------
# GPU stats (Ollama + local accelerator probes)
# ---------------------------------------------------------------------------

_gpu_cache: dict = {}
_gpu_cache_ts: float = 0.0
_GPU_CACHE_TTL = 5.0  # seconds


def _coerce_percent(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return round(float(value), 1)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("%"):
            text = text[:-1]
        try:
            return round(float(text), 1)
        except ValueError:
            return None
    return None


def _coerce_bytes(value: object) -> int | None:
    if isinstance(value, (int, float)):
        return max(0, int(value))
    if not isinstance(value, str):
        return None
    match = re.search(r"(-?\d+(?:\.\d+)?)\s*([KMGTP]?i?B)?", value.strip(), re.IGNORECASE)
    if not match:
        return None
    try:
        number = float(match.group(1))
    except ValueError:
        return None
    if number < 0:
        return None
    unit = (match.group(2) or "B").upper()
    multipliers = {
        "B": 1,
        "KB": 1000,
        "MB": 1000**2,
        "GB": 1000**3,
        "TB": 1000**4,
        "KIB": 1024,
        "MIB": 1024**2,
        "GIB": 1024**3,
        "TIB": 1024**4,
    }
    return int(number * multipliers.get(unit, 1))


def _normalize_gpu_name(name: str | None) -> str | None:
    if not name:
        return None
    normalized = name.strip()
    for prefix in ("NVIDIA GeForce ", "NVIDIA ", "AMD Radeon ", "AMD "):
        if normalized.startswith(prefix):
            return normalized[len(prefix):]
    return normalized


def _pick_primary_gpu(candidates: list[dict]) -> dict | None:
    usable = [candidate for candidate in candidates if candidate]
    if not usable:
        return None

    def _sort_key(candidate: dict) -> tuple[int, float, float]:
        used = candidate.get("vram_used_bytes")
        util = candidate.get("utilization_pct")
        temp = candidate.get("temp_c")
        return (
            1 if used is not None else 0,
            float(used or 0),
            float(util if util is not None else (temp or 0)),
        )

    return max(usable, key=_sort_key)


def _query_nvidia_smi() -> dict | None:
    """Parse nvidia-smi CSV output. Returns the most-active GPU if available."""
    if not shutil.which("nvidia-smi"):
        return None
    try:
        r = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode != 0:
            return None
        candidates: list[dict] = []
        for raw_line in r.stdout.splitlines():
            if not raw_line.strip():
                continue
            parts = [p.strip() for p in raw_line.split(",")]
            if len(parts) < 5:
                continue
            candidates.append({
                "name": _normalize_gpu_name(parts[0]),
                "utilization_pct": int(parts[1]),
                "vram_used_bytes": int(parts[2]) * 1048576,
                "vram_total_bytes": int(parts[3]) * 1048576,
                "temp_c": int(parts[4]),
            })
        return _pick_primary_gpu(candidates)
    except Exception:
        return None


def _query_rocm_torch_memory(index: int) -> tuple[int | None, int | None]:
    if torch is None or not hasattr(torch, "cuda") or not torch.cuda.is_available():  # type: ignore[attr-defined]
        return None, None
    if not hasattr(torch.cuda, "mem_get_info"):
        return None, None
    try:
        try:
            free_bytes, total_bytes = torch.cuda.mem_get_info(index)  # type: ignore[misc]
        except TypeError:
            with torch.cuda.device(index):
                free_bytes, total_bytes = torch.cuda.mem_get_info()  # type: ignore[call-arg]
    except Exception:
        return None, None
    if not total_bytes:
        return None, None
    return max(0, int(total_bytes - free_bytes)), int(total_bytes)


def _query_rocm_smi() -> dict | None:
    rocm_smi = shutil.which("rocm-smi")
    if not rocm_smi:
        for candidate in ("/opt/rocm/bin/rocm-smi", "/usr/bin/rocm-smi"):
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                rocm_smi = candidate
                break
    if not rocm_smi:
        return None

    commands = [
        [rocm_smi, "--showproductname", "--showuse", "--showtemp", "--showmeminfo", "vram", "--json"],
        [rocm_smi, "--showproductname", "--showuse", "--showtemp", "--showmemuse", "--json"],
        [rocm_smi, "--showuse", "--showtemp", "--json"],
        [rocm_smi, "--showuse"],
    ]

    for command in commands:
        try:
            completed = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=3,
            )
        except (FileNotFoundError, subprocess.SubprocessError):
            continue

        output = (completed.stdout or "").strip()
        if not output:
            continue

        if "--json" in command:
            try:
                data = json.loads(output)
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict):
                continue
            candidates: list[dict] = []
            for key, entry in data.items():
                if not isinstance(entry, dict):
                    continue
                index_match = re.search(r"(\d+)", str(key))
                gpu_index = int(index_match.group(1)) if index_match else len(candidates)
                used_bytes, total_bytes = _query_rocm_torch_memory(gpu_index)
                if used_bytes is None:
                    used_bytes = (
                        _coerce_bytes(entry.get("VRAM Total Used Memory (B)"))
                        or _coerce_bytes(entry.get("VRAM Total Used Memory"))
                        or _coerce_bytes(entry.get("GPU Memory Used (B)"))
                        or _coerce_bytes(entry.get("GPU Memory Used"))
                    )
                if total_bytes is None:
                    total_bytes = (
                        _coerce_bytes(entry.get("VRAM Total Memory (B)"))
                        or _coerce_bytes(entry.get("VRAM Total Memory"))
                        or _coerce_bytes(entry.get("GPU Memory Total (B)"))
                        or _coerce_bytes(entry.get("GPU Memory Total"))
                    )
                # Fallback: compute used from percentage when only --showmemuse was available
                if used_bytes is None and total_bytes is not None:
                    mem_pct = (
                        _coerce_percent(entry.get("GPU memory use (%)"))
                        or _coerce_percent(entry.get("GPU Memory Allocated (VRAM%)"))
                    )
                    if mem_pct is not None:
                        used_bytes = int(total_bytes * mem_pct / 100.0)
                utilization_pct = None
                for util_key in (
                    "GPU use (%)",
                    "GPU use (%) (avg)",
                    "GPU use (%) (average)",
                    "GPU use (%) (current)",
                ):
                    utilization_pct = _coerce_percent(entry.get(util_key))
                    if utilization_pct is not None:
                        break
                temp_c = None
                for temp_key, raw_value in entry.items():
                    if "temperature" not in str(temp_key).lower():
                        continue
                    temp_c = _coerce_percent(raw_value)
                    if temp_c is not None:
                        break
                # Card model often returns a hex PCI ID (e.g. "0x74b5").
                # Check human-readable fields first, skip any hex values.
                raw_name = "AMD GPU"
                for name_key in ("Card series", "Market Name", "Device Name", "Card model"):
                    val = entry.get(name_key)
                    if isinstance(val, str) and val.strip() and not val.strip().startswith("0x"):
                        raw_name = val.strip()
                        break
                candidates.append({
                    "name": _normalize_gpu_name(raw_name),
                    "utilization_pct": utilization_pct,
                    "vram_used_bytes": used_bytes,
                    "vram_total_bytes": total_bytes,
                    "temp_c": temp_c,
                })
            primary = _pick_primary_gpu(candidates)
            if primary:
                return primary
            continue

        matches = re.findall(r"GPU\s*\[\s*(\d+)\s*\].*?GPU use.*?:\s*([0-9]+(?:\.[0-9]+)?)", output)
        if not matches:
            continue
        candidates = []
        for gpu_index_raw, util_raw in matches:
            gpu_index = int(gpu_index_raw)
            used_bytes, total_bytes = _query_rocm_torch_memory(gpu_index)
            candidates.append({
                "name": "AMD GPU",
                "utilization_pct": _coerce_percent(util_raw),
                "vram_used_bytes": used_bytes,
                "vram_total_bytes": total_bytes,
                "temp_c": None,
            })
        primary = _pick_primary_gpu(candidates)
        if primary:
            return primary

    return None


def _query_mps_stats() -> dict | None:
    if platform.system() != "Darwin" or torch is None:
        return None
    backend = getattr(torch.backends, "mps", None)
    if backend is None or not backend.is_available():
        return None

    used_bytes = None
    total_bytes = None
    driver_alloc = getattr(torch.mps, "driver_allocated_memory", None)
    driver_total = getattr(torch.mps, "driver_total_memory", None)
    if callable(driver_alloc) and callable(driver_total):
        try:
            used_bytes = int(driver_alloc())
            total_bytes = int(driver_total())
        except Exception:
            used_bytes = None
            total_bytes = None

    utilization_pct = None
    try:
        completed = subprocess.run(
            ["ioreg", "-r", "-k", "PerformanceStatistics", "-d", "1", "-a"],
            check=True,
            capture_output=True,
            text=False,
            timeout=2,
        )
        if completed.stdout:
            data = plistlib.loads(completed.stdout)
            if isinstance(data, list):
                values: list[float] = []
                for entry in data:
                    if not isinstance(entry, dict):
                        continue
                    perf = entry.get("PerformanceStatistics")
                    if not isinstance(perf, dict):
                        continue
                    value = perf.get("Device Utilization %")
                    if isinstance(value, (int, float)):
                        values.append(round(float(value), 1))
                if values:
                    utilization_pct = max(values)
    except Exception:
        utilization_pct = None

    if used_bytes is None and total_bytes is None and utilization_pct is None:
        return None

    return {
        "name": "Apple GPU",
        "utilization_pct": utilization_pct,
        "vram_used_bytes": used_bytes,
        "vram_total_bytes": total_bytes,
        "temp_c": None,
    }


def _detect_amd_gpu_without_rocm_smi() -> dict | None:
    """Check /sys/class/drm for AMD GPUs (vendor 0x1002) when rocm-smi is absent."""
    try:
        drm = Path("/sys/class/drm")
        if not drm.is_dir():
            return None
        for card in sorted(drm.iterdir()):
            vendor_file = card / "device" / "vendor"
            if not vendor_file.is_file():
                continue
            vendor = vendor_file.read_text().strip()
            if vendor == "0x1002":
                name = "AMD GPU"
                name_file = card / "device" / "product_name"
                if name_file.is_file():
                    name = _normalize_gpu_name(name_file.read_text().strip()) or name
                return {
                    "name": name,
                    "utilization_pct": None,
                    "vram_used_bytes": None,
                    "vram_total_bytes": None,
                    "temp_c": None,
                    "missing_tool": "rocm-smi",
                }
    except Exception:
        pass
    return None


def _query_gpu_stats() -> dict | None:
    for probe in (_query_nvidia_smi, _query_rocm_smi, _query_mps_stats):
        result = probe()
        if result:
            return result
    # No stats tool found — check if AMD hardware is present anyway
    return _detect_amd_gpu_without_rocm_smi()


def _query_ollama_ps(base_url: str) -> list[dict]:
    """Fetch /api/ps from Ollama. Returns [] on failure."""
    for suffix in ("/v1", "/api"):
        if base_url.endswith(suffix):
            base_url = base_url[: -len(suffix)]
            break
    url = f"{base_url}/api/ps"
    try:
        req = urllib_request.Request(url, method="GET")
        with urllib_request.urlopen(req, timeout=5) as resp:  # noqa: S310
            data = json.loads(resp.read())
        models = []
        for m in data.get("models", []):
            models.append({
                "name": m.get("name", ""),
                "size_vram": m.get("size_vram", 0),
                "parameter_size": (m.get("details") or {}).get("parameter_size", ""),
                "quantization": (m.get("details") or {}).get("quantization_level", ""),
                "expires_at": m.get("expires_at"),
            })
        return models
    except Exception:
        return []


@router.get("/gpu-stats")
async def gpu_stats(request: Request) -> dict:
    global _gpu_cache, _gpu_cache_ts
    now = time.monotonic()
    if now - _gpu_cache_ts < _GPU_CACHE_TTL and _gpu_cache:
        return _gpu_cache

    settings = request.app.state.settings
    mode = getattr(settings, "tge_completion_mode", "")

    if mode != "ollama":
        result = {"available": False}
        _gpu_cache, _gpu_cache_ts = result, now
        return result

    base_url = settings.tge_llm_base_url.rstrip("/")
    gpu, models = await asyncio.gather(
        asyncio.to_thread(_query_gpu_stats),
        asyncio.to_thread(_query_ollama_ps, base_url),
    )

    if not gpu and not models:
        result: dict = {"available": False}
    else:
        gpu = gpu or {}
        if not gpu and models:
            total_vram = sum(m.get("size_vram", 0) for m in models)
            gpu = {
                "name": None,
                "utilization_pct": None,
                "vram_used_bytes": total_vram,
                "vram_total_bytes": None,
                "temp_c": None,
            }
        result = {"available": True, "gpu": gpu, "ollama_models": models}

    _gpu_cache, _gpu_cache_ts = result, now
    return result


# ---------------------------------------------------------------------------
# Image generation settings & daemon control
# ---------------------------------------------------------------------------


@router.get("/settings/image")
async def get_image_settings(request: Request) -> dict:
    settings = request.app.state.settings
    daemon = getattr(request.app.state, "diffusers_daemon", None)
    return {
        "image_backend": settings.image_backend,
        "diffusers_host": settings.diffusers_host,
        "diffusers_port": settings.diffusers_port,
        "diffusers_model": settings.diffusers_model,
        "diffusers_device": settings.diffusers_device,
        "diffusers_dtype": settings.diffusers_dtype,
        "diffusers_offload": settings.diffusers_offload,
        "diffusers_quantization": settings.diffusers_quantization,
        "diffusers_vae_tiling": settings.diffusers_vae_tiling,
        "diffusers_autostart": settings.diffusers_autostart,
        "comfyui_url": settings.comfyui_url,
        "comfyui_workflow_json": settings.comfyui_workflow_json,
        "image_width": settings.image_width,
        "image_height": settings.image_height,
        "image_steps": settings.image_steps,
        "image_guidance_scale": settings.image_guidance_scale,
        "image_cache_max_entries": settings.image_cache_max_entries,
        "daemon_state": daemon.state.value if daemon else None,
    }


@router.post("/settings/image")
async def update_image_settings(
    payload: ImageSettingsUpdate,
    request: Request,
) -> dict:
    settings = request.app.state.settings
    raw = payload.model_dump()
    updated = []
    for k, v in raw.items():
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        setattr(settings, k, v)
        updated.append(k)
    if not updated:
        raise HTTPException(status_code=400, detail="No settings provided.")

    from app.settings import persist_settings

    persist_settings(settings)

    # Diffusers daemon settings that can be hot-reloaded via daemon.restart()
    _DIFFUSERS_DAEMON_KEYS = {
        "diffusers_host", "diffusers_port", "diffusers_model",
        "diffusers_device", "diffusers_dtype", "diffusers_offload",
        "diffusers_quantization", "diffusers_vae_tiling",
    }
    # Settings that still require a full server restart
    _RESTART_KEYS = {"comfyui_url", "comfyui_workflow_json"}

    restart_required = False
    daemon_restarted = False
    updated_set = set(updated)

    # Hot-reload diffusers daemon if daemon keys changed
    if updated_set & _DIFFUSERS_DAEMON_KEYS:
        daemon = getattr(request.app.state, "diffusers_daemon", None)
        if daemon is not None and daemon.state.value != "stopped":
            # Map settings keys to daemon kwarg names (strip diffusers_ prefix)
            kwargs = {}
            for k in _DIFFUSERS_DAEMON_KEYS & updated_set:
                daemon_key = k.replace("diffusers_", "")
                kwargs[daemon_key] = getattr(settings, k)
            await daemon.restart(**kwargs)
            # Update client base_url too
            client = getattr(request.app.state, "diffusers_client", None)
            if client is not None:
                client._base = daemon.base_url
            daemon_restarted = True
        elif daemon is not None:
            # Daemon exists but stopped — just update its internal fields
            for k in _DIFFUSERS_DAEMON_KEYS & updated_set:
                daemon_key = k.replace("diffusers_", "")
                attr = f"_{daemon_key}"
                val = getattr(settings, k)
                if daemon_key == "port":
                    val = int(val)
                setattr(daemon, attr, val)
            client = getattr(request.app.state, "diffusers_client", None)
            if client is not None:
                client._base = daemon.base_url

    # Backend switch or comfyui changes still need restart
    if "image_backend" in updated_set or (updated_set & _RESTART_KEYS):
        restart_required = True

    result = {"updated": updated, "restart_required": restart_required}
    if daemon_restarted:
        result["daemon_restarted"] = True
    return result


@router.post("/image/daemon/start")
async def start_image_daemon(request: Request) -> dict:
    daemon = getattr(request.app.state, "diffusers_daemon", None)
    if daemon is None:
        raise HTTPException(
            status_code=400,
            detail="No diffusers daemon configured. Set image_backend to 'diffusers' first.",
        )
    return await daemon.start()


@router.post("/image/daemon/stop")
async def stop_image_daemon(request: Request) -> dict:
    daemon = getattr(request.app.state, "diffusers_daemon", None)
    if daemon is None:
        raise HTTPException(status_code=400, detail="No diffusers daemon configured.")
    return await daemon.stop()


@router.get("/image/daemon/status")
async def image_daemon_status(request: Request) -> dict:
    daemon = getattr(request.app.state, "diffusers_daemon", None)
    if daemon is None:
        return {"state": "not_configured"}

    result: dict = {"state": daemon.state.value}

    # Include GPU stats if daemon is running
    client = getattr(request.app.state, "diffusers_client", None)
    if client and daemon.state.value == "running":
        try:
            result["system_stats"] = await client.system_stats()
        except Exception:
            result["system_stats"] = None
    return result


@router.get("/image/daemon/logs")
async def image_daemon_logs(request: Request) -> dict:
    daemon = getattr(request.app.state, "diffusers_daemon", None)
    if daemon is None:
        return {"logs": []}
    return {"logs": daemon.recent_logs}


@router.post("/image/generate")
async def generate_image(
    payload: ImageGenerateRequest,
    request: Request,
) -> dict:
    settings = request.app.state.settings
    backend = (settings.image_backend or "none").strip().lower()

    orchestrator = getattr(request.app.state, "gpu_orchestrator", None)
    if orchestrator:
        await orchestrator.before_image_generation()

    if backend == "diffusers":
        client = getattr(request.app.state, "diffusers_client", None)
        if client is None:
            raise HTTPException(status_code=400, detail="Diffusers client not initialized.")
        result = await client.generate(
            prompt=payload.prompt,
            model_id=payload.model_id or settings.diffusers_model,
            width=payload.width if payload.width is not None else settings.image_width,
            height=payload.height if payload.height is not None else settings.image_height,
            steps=payload.steps if payload.steps is not None else settings.image_steps,
            guidance_scale=payload.guidance_scale if payload.guidance_scale is not None else settings.image_guidance_scale,
            seed=payload.seed,
        )
        job_id = result.get("job_id")
        if orchestrator and job_id:
            _gpu_orchestrated_jobs = getattr(request.app.state, "gpu_orchestrated_jobs", None)
            if _gpu_orchestrated_jobs is not None:
                _gpu_orchestrated_jobs.add(job_id)
        return result

    elif backend == "comfyui":
        client = getattr(request.app.state, "comfyui_client", None)
        if client is None:
            raise HTTPException(status_code=400, detail="ComfyUI client not initialized.")
        prompt_id = await client.queue_prompt(
            prompt=payload.prompt,
            width=payload.width if payload.width is not None else settings.image_width,
            height=payload.height if payload.height is not None else settings.image_height,
            steps=payload.steps if payload.steps is not None else settings.image_steps,
            cfg=payload.guidance_scale if payload.guidance_scale is not None else settings.image_guidance_scale,
            seed=payload.seed,
            model=payload.model_id or settings.diffusers_model,
        )
        if orchestrator and prompt_id:
            _gpu_orchestrated_jobs = getattr(request.app.state, "gpu_orchestrated_jobs", None)
            if _gpu_orchestrated_jobs is not None:
                _gpu_orchestrated_jobs.add(prompt_id)
        return {"job_id": prompt_id, "status": "pending", "backend": "comfyui"}

    else:
        raise HTTPException(
            status_code=400,
            detail=f"No image backend configured (current: {backend}).",
        )


async def _maybe_after_image_generation(request: Request, job_id: str) -> None:
    """Call orchestrator.after_image_generation() if this job was orchestrated."""
    tracked = getattr(request.app.state, "gpu_orchestrated_jobs", None)
    if tracked is None or job_id not in tracked:
        return
    tracked.discard(job_id)
    orchestrator = getattr(request.app.state, "gpu_orchestrator", None)
    if orchestrator:
        await orchestrator.after_image_generation()


@router.get("/image/status/{job_id}")
async def image_job_status(job_id: str, request: Request) -> dict:
    settings = request.app.state.settings
    backend = (settings.image_backend or "none").strip().lower()

    if backend == "diffusers":
        client = getattr(request.app.state, "diffusers_client", None)
        if client is None:
            raise HTTPException(status_code=400, detail="Diffusers client not initialized.")
        status = await client.poll_status(job_id)
        # If completed, store the first image in cache and return a URL
        if status.get("status") == "completed" and status.get("images"):
            cache = request.app.state.image_cache
            entry = cache.store_from_base64(
                base64_png=status["images"][0],
                prompt="(manual generation)",
            )
            status["image_url"] = cache.url_for(entry)
            status["image_id"] = entry.image_id
        if status.get("status") in ("completed", "failed", "interrupted"):
            await _maybe_after_image_generation(request, job_id)
        return status

    elif backend == "comfyui":
        client = getattr(request.app.state, "comfyui_client", None)
        if client is None:
            raise HTTPException(status_code=400, detail="ComfyUI client not initialized.")
        try:
            history = await client.get_history(job_id)
        except Exception as exc:
            return {"status": "polling", "error": str(exc)}
        if job_id in history:
            entry = history[job_id]
            completed = entry.get("status", {}).get("completed", False)
            if completed:
                await _maybe_after_image_generation(request, job_id)
                # Download and cache first output image
                for _nid, node_out in entry.get("outputs", {}).items():
                    images = node_out.get("images", [])
                    if images:
                        img_info = images[0]
                        png_bytes = await client.download_image(
                            filename=img_info["filename"],
                            subfolder=img_info.get("subfolder", ""),
                            type_=img_info.get("type", "output"),
                        )
                        cache = request.app.state.image_cache
                        cached = cache.store(
                            png_bytes=png_bytes,
                            prompt="(manual generation)",
                        )
                        return {
                            "status": "completed",
                            "image_url": cache.url_for(cached),
                            "image_id": cached.image_id,
                        }
                return {"status": "completed", "images": []}
            return {"status": "processing"}
        return {"status": "pending"}

    raise HTTPException(status_code=400, detail="No image backend configured.")


@router.get("/image/recent")
async def recent_images(request: Request) -> dict:
    cache = getattr(request.app.state, "image_cache", None)
    if cache is None:
        return {"images": []}
    entries = cache.recent(limit=20)
    return {
        "images": [
            {
                "image_id": e.image_id,
                "url": cache.url_for(e),
                "prompt": e.prompt,
                "campaign_id": e.campaign_id,
                "ref_type": e.ref_type,
                "created_at": e.created_at,
            }
            for e in entries
        ]
    }
