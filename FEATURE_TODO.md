# ClawQuake Feature TODO

Last updated: 2026-04-03

## Requested Features (User Brain Dump)

1. Human player naming in-game (replace `UnnamedPlayer`)
Status: TODO
Notes: Use logged-in ClawQuake username as default display name, plus optional user-defined player tag override.

2. Leaderboard click-through to live telemetry
Status: DONE
Notes: Clicking a leaderboard row opens a live telemetry panel showing health, armor, weapon, position, and recent events. Backend: `/ws/bot-telemetry/{bot_id}` endpoint rate-limited to 5Hz. Frontend: clickable rows, real-time WebSocket panel with auto-reconnect. Infrastructure: TelemetryHub, internal/external WS endpoints, SDK `connect_telemetry()`.

3. Overhead map with live player dots
Status: DONE (v1)
Notes: Dynamic minimap at `/radar` and embedded in tournament detail page. Bot dots with health bars, weapon labels, ammo bars, and firing indicators. Items discovered by bots appear as map landmarks (fog-of-war reveal). Auto-bounds from entity positions. Remaining: item classifier needs fixing (all items show as generic "item" type instead of health/armor/weapon).

4. QuakeJS/Quake code customization research
Status: TODO
Notes: Document what parts are open source, licensing constraints, and the safest extension points for ClawQuake-specific changes.

5. MCP strategy library/runtime integration
Status: TODO
Notes: Add an MCP-native integration path for strategy execution so agents are not limited to the current API control plane + local file strategy resolution model.

6. Human session persistence across browser refresh
Status: TODO
Notes: Refresh should not create a new in-game human identity/session each time. Reuse the same player identity (name/tag/session key) and reconnect semantics where possible.

7. Spectator mode selection (follow bot or free-float)
Status: TODO
Notes: Let user choose spectate behavior: (a) attach/follow a selected bot POV, or (b) join as free spectator and fly around manually.

8. Crypto betting / wagering on bot matches
Status: IDEA (not committed to building yet)
Notes: Potential monetization path — allow users to place bets on bot matches using cryptocurrency. Would need: wallet integration, odds calculation (possibly ELO-based), escrow/smart contract for payouts, match result verification, and regulatory/legal research. This is exploratory — document and revisit when platform is more mature.

9. Tournament/match cancel button
Status: DONE
Notes: DELETE `/api/tournaments/{tid}/cancel` endpoint. Red "Cancel Tournament" button on detail page with confirmation dialog. Cancels runner task, closes open matches, kills bot processes. Cancelled status shown with red badge.

10. Fog of war / AI hearing
Status: DONE (v1)
Notes: Observe API and live-positions API filter by perception range. 2D XY distance < 800 units + Z band < 128 units. Bots can only "hear" nearby entities on the same floor. Spectator minimap uses combined view from all bots (no fog of war on spectator view).

11. Item classifier fix
Status: TODO
Notes: All items show as generic "item" type. The `ItemClassifier` in `bot/game_intelligence.py` checks model names from config_strings but QuakeJS model paths don't match the expected patterns (health, armor, weapon keywords). Needs investigation of actual Q3 config string values.

12. Match timeout detection
Status: TODO
Notes: When orchestrator restarts mid-match, it loses process tracking and matches never finalize. Need a timeout mechanism (e.g. check match age, force-finalize stale matches on startup).

13. Kill/death stat propagation
Status: TODO
Notes: Game server logs kills (`Kill: 0 3 3: gotcha killed cillpill`) but bot-status API shows 0 kills/deaths. The kill tracker in the bot runner isn't propagating to the match finalization.
