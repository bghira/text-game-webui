from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import NoReturn
from urllib import request as urllib_request

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.services.engine_gateway import FEATURES, EngineGateway
from app.services.schemas import (
    AttributeSetRequest,
    AvatarActionRequest,
    CampaignRuleUpdate,
    CampaignFlagsUpdate,
    CharacterPortraitRequest,
    LLMSettingsUpdate,
    LevelUpRequest,
    MinigameMoveRequest,
    MemorySearchRequest,
    MemoryStoreRequest,
    MemoryTermsRequest,
    MemoryTurnRequest,
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
    TurnRequest,
)

router = APIRouter(prefix="/api", tags=["api"])


class CampaignCreateRequest(BaseModel):
    namespace: str = "default"
    name: str
    actor_id: str


def get_gateway(request: Request) -> EngineGateway:
    return request.app.state.gateway


def _not_found(err: KeyError) -> NoReturn:
    raise HTTPException(status_code=404, detail=str(err)) from err


def _bad_request(err: ValueError) -> NoReturn:
    raise HTTPException(status_code=400, detail=str(err)) from err


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


@router.get("/campaigns")
async def list_campaigns(namespace: str = "default", gateway: EngineGateway = Depends(get_gateway)) -> dict:
    rows = await gateway.list_campaigns(namespace)
    return {"campaigns": [row.model_dump() for row in rows]}


@router.post("/campaigns")
async def create_campaign(payload: CampaignCreateRequest, gateway: EngineGateway = Depends(get_gateway)) -> dict:
    row = await gateway.create_campaign(payload.namespace, payload.name, payload.actor_id)
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


async def _publish_turn_events(request: Request, campaign_id: str, result, gateway) -> None:
    """Publish turn, media, and timer events via the realtime layer."""
    await request.app.state.realtime.publish(
        campaign_id,
        {
            "type": "turn",
            "session_id": result.session_id,
            "actor_id": result.actor_id,
            "payload": result.model_dump(),
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
    try:
        result = await gateway.submit_turn(campaign_id, payload)
    except KeyError as err:
        _not_found(err)
    except ValueError as err:
        _bad_request(err)
    await _publish_turn_events(request, campaign_id, result, gateway)
    return result.model_dump()


@router.post("/campaigns/{campaign_id}/turns/stream")
async def submit_turn_stream(
    campaign_id: str,
    payload: TurnRequest,
    request: Request,
    gateway: EngineGateway = Depends(get_gateway),
) -> StreamingResponse:
    from app.services.schemas import TurnResult as TurnResultModel

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
            if event_type == "complete":
                final_result = TurnResultModel(**event_data)
            elif event_type == "error":
                break
    except KeyError as err:
        error_event = f"event: error\ndata: {json.dumps({'message': str(err)})}\n\n"
    except ValueError as err:
        error_event = f"event: error\ndata: {json.dumps({'message': str(err)})}\n\n"

    # Publish realtime events unconditionally — not tied to client connection.
    if final_result:
        await _publish_turn_events(request, campaign_id, final_result, gateway)

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
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    try:
        return await gateway.rewind_to_turn(campaign_id, target_turn_id)
    except KeyError as err:
        _not_found(err)
    except ValueError as err:
        _bad_request(err)


@router.post("/campaigns/{campaign_id}/timers/cancel")
async def cancel_pending_timer(campaign_id: str, gateway: EngineGateway = Depends(get_gateway)) -> dict:
    try:
        return await gateway.cancel_pending_timer(campaign_id)
    except KeyError as err:
        _not_found(err)


@router.get("/campaigns/{campaign_id}/player-statistics")
async def get_player_statistics(campaign_id: str, actor_id: str, gateway: EngineGateway = Depends(get_gateway)) -> dict:
    try:
        return await gateway.get_player_statistics(campaign_id, actor_id)
    except KeyError as err:
        _not_found(err)


@router.get("/campaigns/{campaign_id}/player-attributes")
async def get_player_attributes(campaign_id: str, actor_id: str, gateway: EngineGateway = Depends(get_gateway)) -> dict:
    try:
        return await gateway.get_player_attributes(campaign_id, actor_id)
    except KeyError as err:
        _not_found(err)


@router.post("/campaigns/{campaign_id}/player-attributes")
async def set_player_attribute(
    campaign_id: str,
    payload: AttributeSetRequest,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    try:
        return await gateway.set_player_attribute(campaign_id, payload.actor_id, payload.attribute, payload.value)
    except KeyError as err:
        _not_found(err)
    except ValueError as err:
        _bad_request(err)


@router.post("/campaigns/{campaign_id}/level-up")
async def level_up_player(
    campaign_id: str,
    payload: LevelUpRequest,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    try:
        return await gateway.level_up_player(campaign_id, payload.actor_id)
    except KeyError as err:
        _not_found(err)


@router.get("/campaigns/{campaign_id}/recent-turns")
async def get_recent_turns(
    campaign_id: str,
    limit: int = 30,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    try:
        return await gateway.get_recent_turns(campaign_id, limit=limit)
    except KeyError as err:
        _not_found(err)


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
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
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
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
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


@router.get("/campaigns/{campaign_id}/map")
async def get_map(campaign_id: str, actor_id: str, gateway: EngineGateway = Depends(get_gateway)) -> dict:
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
async def get_calendar(campaign_id: str, gateway: EngineGateway = Depends(get_gateway)) -> dict:
    try:
        return await gateway.get_calendar(campaign_id)
    except KeyError as err:
        _not_found(err)


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
async def get_player_state(campaign_id: str, actor_id: str, gateway: EngineGateway = Depends(get_gateway)) -> dict:
    try:
        data = await gateway.get_player_state(campaign_id, actor_id)
    except KeyError as err:
        _not_found(err)
    return {"player_state": data}


@router.get("/campaigns/{campaign_id}/media")
async def get_media(
    campaign_id: str,
    actor_id: str | None = None,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
    try:
        data = await gateway.get_media(campaign_id, actor_id)
    except KeyError as err:
        _not_found(err)
    return {"media": data}


@router.post("/campaigns/{campaign_id}/media/avatar/accept")
async def accept_pending_avatar(
    campaign_id: str,
    payload: AvatarActionRequest,
    request: Request,
    gateway: EngineGateway = Depends(get_gateway),
) -> dict:
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
        return await gateway.memory_search(campaign_id, payload.queries, payload.category)
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
async def sms_read(campaign_id: str, payload: SmsReadRequest, gateway: EngineGateway = Depends(get_gateway)) -> dict:
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
async def get_settings(request: Request) -> dict:
    settings = request.app.state.settings
    try:
        ollama_options = json.loads(settings.tge_ollama_options_json or "{}")
    except (json.JSONDecodeError, TypeError):
        ollama_options = {}
    return {
        "completion_mode": settings.tge_completion_mode,
        "base_url": settings.tge_llm_base_url,
        "model": settings.tge_llm_model,
        "temperature": settings.tge_llm_temperature,
        "max_tokens": settings.tge_llm_max_tokens,
        "timeout_seconds": settings.tge_llm_timeout_seconds,
        "keep_alive": settings.tge_ollama_keep_alive,
        "ollama_options": ollama_options,
        "gateway_backend": settings.gateway_backend,
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
