# Testing

## Backend
- Run: `pytest`
- Scope: API handlers, gateway behavior, route contracts.

## Frontend (Jest)
- Run in `tests/frontend`: `npm test`
- Required:
  - flow tests in `tests/frontend/flows/*.test.ts`
  - deterministic mocks for network/websocket behavior
