# ClawQuake Live Stream and Dashboard Fix Log

Date: 2026-02-09
Owner: Codex

## Goal
Fix local live match viewing in `dashboard.html`, including:
- stream not appearing,
- spectator client stuck at `AWAITING CHALLENGE`,
- player input/focus issues in embedded view,
- dashboard layout and usability issues.

## Root Causes Found
1. The OpenArena-based spectator path produced HLS but could not complete gameplay handshake with the QuakeJS server stack (showed `AWAITING CHALLENGE`).
2. Dashboard prioritized that HLS path, so users saw non-playable output.
3. Embedded iframe lacked robust focus/permission handling for pointer-lock + keyboard input.
4. Dashboard layout needed side-panel flexibility and better responsive behavior.

## Changes Implemented

### Infrastructure and runtime
- Added/used dedicated spectator service in compose flows and nginx stream proxy wiring:
  - `docker-compose.yml`
  - `docker-compose.multi.yml`
  - `nginx/nginx.conf`
- Fixed spectator image and startup behavior:
  - `spectator/Dockerfile`
  - `spectator/entrypoint.sh`
- Improved orchestrator status behavior so live matches are reported even when UDP `getstatus` is unavailable in QuakeJS websocket mode:
  - `orchestrator/main.py`
- Process manager hardening used during debugging:
  - `orchestrator/process_manager.py`

### Dashboard / spectator UX
- Switched dashboard default live view to direct QuakeJS spectator embed (`http://<host>:8080`) and made HLS opt-in (`?hls=1`):
  - `web/dashboard.html`
- Updated spectator page default path to direct QuakeJS URL:
  - `web/spectate.html`
- Added local `hls.js` bundle for optional HLS mode:
  - `web/vendor/hls.min.js`
- Added iframe permissions/focus updates for input reliability:
  - `web/dashboard.html`
  - `web/spectate.html`
- Fixed dashboard player sizing for embedded iframe:
  - `web/style.css`

### Dashboard layout updates
- Moved stats panel to left side.
- Added `Hide Stats / Show Stats` toggle with persisted preference in localStorage.
- Fixed desktop row alignment so stream + stats stay side-by-side.
- Adjusted responsive breakpoint so stacking only happens on narrower screens.
  - `web/dashboard.html`
  - `web/style.css`

## Validation Performed
- Verified service health endpoint:
  - `GET /api/health` -> `{"status":"ok","service":"clawquake-orchestrator"}`
- Verified live state during active match:
  - `GET /api/status` -> `online: true` with active-match payload.
- Triggered local matches by registering/queueing bots and confirmed matchmaker launch.
- Confirmed dashboard now renders direct gameplay stream and responds to new layout controls.

## Notes
- HLS path remains available for debugging via `http://localhost/dashboard.html?hls=1`.
- Primary recommended viewer path is direct QuakeJS embed from dashboard/spectate.
