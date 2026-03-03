from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.services.engine_gateway import FEATURES, EngineGateway
from app.services.schemas import (
    MemorySearchRequest,
    MemoryStoreRequest,
    MemoryTermsRequest,
    MemoryTurnRequest,
    SmsListRequest,
    SmsReadRequest,
    SmsWriteRequest,
    TurnRequest,
)

router = APIRouter(prefix="/api", tags=["api"])


class CampaignCreateRequest(BaseModel):
    namespace: str = "default"
    name: str
    actor_id: str


def get_gateway(request: Request) -> EngineGateway:
    return request.app.state.gateway


def _not_found(err: KeyError) -> None:
    raise HTTPException(status_code=404, detail=str(err)) from err


@router.get("/health")
async def health() -> dict:
    return {"ok": True}


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
    await request.app.state.realtime.publish(campaign_id, {"type": "turn", "payload": result.model_dump()})
    return result.model_dump()


@router.get("/campaigns/{campaign_id}/map")
async def get_map(campaign_id: str, actor_id: str, gateway: EngineGateway = Depends(get_gateway)) -> dict:
    try:
        data = await gateway.get_map(campaign_id, actor_id)
    except KeyError as err:
        _not_found(err)
    return {"map": data}


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
        return await gateway.sms_read(campaign_id, payload.thread, payload.limit)
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
