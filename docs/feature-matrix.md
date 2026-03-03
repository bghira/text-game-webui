# Feature Matrix

| Feature | API Surface | UI Surface | Test Coverage |
|---|---|---|---|
| Runtime backend metadata + checks | `GET /api/runtime`, `GET /api/health`, `GET /api/runtime/checks` (`probe_llm` override supported) | Runtime panel + status bar (including one-click manual LLM probe) | `tests/backend/test_health.py`, `tests/backend/test_tge_gateway_optional.py`, `tests/frontend/flows/runtime_flow.test.ts` |
| Campaign create/list/select | `GET/POST /api/campaigns` | Left campaign panel | `tests/backend/test_campaign_api.py` |
| Session management | `GET /api/campaigns/{id}/sessions`, `POST /api/campaigns/{id}/sessions`, `PATCH /api/campaigns/{id}/sessions/{session_id}` | Inspector Sessions tab | `tests/backend/test_campaign_api.py`, `tests/backend/test_tge_gateway_optional.py`, `tests/frontend/flows/sessions_flow.test.ts` |
| Turn submit + narration | `POST /api/campaigns/{id}/turns` | Turn form + stream | `tests/backend/test_campaign_api.py`, `tests/frontend/flows/turn_submit_flow.test.ts` |
| Realtime updates | `/ws/campaigns/{id}` (`turn`, `sms`, `session`, `media`, `timers`, `roster`) | Turn stream live events | `tests/backend/test_campaign_api.py`, `tests/backend/test_realtime_publish.py` |
| Map inspector | `GET /api/campaigns/{id}/map` | Inspector Map tab | `tests/backend/test_campaign_api.py` |
| Timers inspector | `GET /api/campaigns/{id}/timers` | Inspector Timers tab | `tests/backend/test_campaign_api.py`, `tests/frontend/flows/turn_submit_flow.test.ts`, `tests/backend/test_tge_gateway_optional.py` |
| Calendar inspector | `GET /api/campaigns/{id}/calendar` | Inspector Calendar tab | `tests/backend/test_campaign_api.py` |
| Roster inspector + mutation | `GET /api/campaigns/{id}/roster`, `POST /api/campaigns/{id}/roster/upsert`, `POST /api/campaigns/{id}/roster/remove` | Inspector Roster tab (refresh/upsert/remove) | `tests/backend/test_campaign_api.py`, `tests/backend/test_tge_gateway_optional.py`, `tests/frontend/flows/roster_flow.test.ts` |
| Player state + inventory inspector | `GET /api/campaigns/{id}/player-state?actor_id=...` | Inspector Player tab | `tests/backend/test_campaign_api.py`, `tests/frontend/flows/turn_submit_flow.test.ts` |
| Scene/avatar media status | `GET /api/campaigns/{id}/media?actor_id=...` | Inspector Media tab | `tests/backend/test_campaign_api.py`, `tests/frontend/flows/turn_submit_flow.test.ts`, `tests/backend/test_tge_gateway_optional.py` |
| Avatar accept/decline actions | `POST /api/campaigns/{id}/media/avatar/accept`, `POST /api/campaigns/{id}/media/avatar/decline` | Inspector Media tab | `tests/backend/test_campaign_api.py`, `tests/backend/test_tge_gateway_optional.py`, `tests/frontend/flows/media_avatar_flow.test.ts` |
| Memory tools | `POST /api/campaigns/{id}/memory/search`, `POST /api/campaigns/{id}/memory/terms`, `POST /api/campaigns/{id}/memory/turn`, `POST /api/campaigns/{id}/memory/store` | Inspector Memory tab | `tests/backend/test_campaign_api.py`, `tests/frontend/flows/memory_flow.test.ts` |
| SMS tools | `POST /api/campaigns/{id}/sms/list`, `POST /api/campaigns/{id}/sms/read`, `POST /api/campaigns/{id}/sms/write` | Inspector SMS tab | `tests/backend/test_campaign_api.py`, `tests/frontend/flows/sms_flow.test.ts` |
| Debug snapshot | `GET /api/campaigns/{id}/debug/snapshot` | Inspector Debug tab | `tests/backend/test_campaign_api.py` |
| Connection diagnostics + bundle export | Client telemetry (`/api/runtime`, `/api/health`, `/api/runtime/checks`, websocket lifecycle) + server bundle (`GET /api/diagnostics/bundle`) | Inspector Debug tab | `tests/frontend/flows/runtime_flow.test.ts`, `tests/backend/test_ui_index.py`, `tests/backend/test_campaign_api.py`, `tests/backend/test_health.py` |
| Gateway selection + completion mode | `app/services/gateway_factory.py`, `app/services/tge_gateway.py` | N/A | `tests/backend/test_gateway_factory.py`, `tests/backend/test_tge_gateway_optional.py` |
