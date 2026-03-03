# Feature Matrix

| Feature | API Surface | UI Surface |
|---|---|---|
| Campaign management | `/api/campaigns` | Campaign sidebar |
| Turn play | `/api/campaigns/{id}/turns` | Play composer + stream |
| Map | `/api/campaigns/{id}/map` | Inspector tab |
| Calendar | `/api/campaigns/{id}/calendar` | Inspector tab |
| Roster | `/api/campaigns/{id}/roster` | Inspector tab |
| Memory search/terms/turn/store | `/api/campaigns/{id}/memory/*` | Memory tab |
| SMS list/read/write | `/api/campaigns/{id}/sms/*` | SMS tab |
| Realtime events | `/ws/campaigns/{id}` | Stream + timer/status widgets |
