# TODOS

## Telemetry & Streaming

- **Dashboard rate-limited telemetry (5Hz)**
  **Priority:** P2
  Deferred from plan: transient-drifting-sunset.md. Add per-match telemetry subscription to websocket_hub.py, rate-limited to 5Hz for browser spectators.

- **WebSocket integration tests with live server**
  **Priority:** P2
  WS endpoints (agent_stream, internal_telemetry) need integration tests that spin up a real ASGI server. Currently covered by unit tests only.

## Completed
