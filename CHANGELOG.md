# Changelog

All notable changes to ClawQuake will be documented in this file.

## [0.2.0.0] - 2026-04-03

### Added
- Tournament cancel button: DELETE `/api/tournaments/{tid}/cancel` endpoint + red UI button on detail page
- Dynamic minimap with item-based map reveal: items appear on radar as bots discover them
- Firing indicator on minimap: red line + orange muzzle flash showing aim direction when attacking
- Weapon label and ammo bar on minimap: shows current weapon name and total ammo across real weapons
- Fog of war perception filtering: 2D distance (800u XY) + Z band (128u) on observe and live-positions APIs
- Sparring bot (sparbot): system bot that auto-readies when registered to tournaments
- Custom strategies persistent volume mount (`./custom_strategies`)
- Gotcha bot v2.0: waypoint navigation, 3-pass lead aim, splash targeting, posture system, gauntlet fallback
- `PRODUCTION_SETUP.md`: comprehensive deployment guide with SSL, proxy, and Docker configuration
- Items included in `GameView.to_dict()` for minimap data flow
- Firing state tracked in agent runner and synced via telemetry

### Fixed
- SSL: added `LETSENCRYPT_HOST` env var for permanent Let's Encrypt cert management
- Nginx crash: spectator upstream uses variable-based resolver (starts without spectator service)
- WSS: always drop port on HTTPS pages (was only dropping port 80)
- QuakeJS spectator mode: use `+cmd team spectator` (Cbuf_AddText not exported in emscripten)
- RCON password mismatch: game server reads from env var, matches orchestrator
- Warmup freeze: server.cfg patched with g_doWarmup/g_warmup/g_countdown 0 at container startup
- Warmup freeze: bot runner sends attack during first 100 ticks for all strategies
- RCON map change: skip reload if server already on correct map (avoids re-triggering warmup)
- Ammo bar: uses real weapon ammo (indices 2-8), skips 65535 weapon flags, shows "dry" when empty
- Firing indicator: uses actual attack state from strategy tick, not player visibility
- Tournament cancel: fixed winner_bot_id column name
- Default map changed from q3dm17 to q3dm1 (small enclosed arena for guaranteed encounters)

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
