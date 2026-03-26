# Changelog

All notable changes to ClawQuake will be documented in this file.

## [0.1.0.0] - 2026-03-26

### Added
- Real-time bidirectional WebSocket telemetry streaming for bot-to-orchestrator and agent-to-orchestrator communication
- TelemetryHub: per-bot pub/sub with bounded queues (maxsize=10) and dropped_frames counter for slow consumer detection
- External agent WebSocket endpoint (`ws /api/agent/stream`) with API key auth, heartbeat, and command forwarding
- Internal bot runner WebSocket endpoint (`ws /api/agent/internal/telemetry`) for 20Hz telemetry push and command drain
- Action validation whitelist with shell metacharacter injection prevention
- TelemetryStreamer in agent_runner.py for WebSocket telemetry streaming with graceful fallback
- SDK `connect_telemetry()` async context manager for bidirectional bot telemetry and commands
- Retro-futuristic design system (DESIGN.md) with Space Grotesk, Instrument Sans, JetBrains Mono, and Quake 3-inspired palette
- Comprehensive test suite: TelemetryHub unit tests, WebSocket security tests, integration tests (51 tests total)

### Fixed
- EventStream `_send()` no longer a no-op — delegates to `_send_sync()` for reliable event emission

### Changed
- CSS custom properties updated to retro-futuristic design system palette and typography
