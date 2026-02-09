# ClawQuake Feature TODO

Last updated: 2026-02-09

## Requested Features (User Brain Dump)

1. Human player naming in-game (replace `UnnamedPlayer`)
Status: TODO
Notes: Use logged-in ClawQuake username as default display name, plus optional user-defined player tag override.

2. Leaderboard click-through to live telemetry
Status: TODO
Notes: Clicking a leaderboard row should open a live telemetry panel for that player/bot (position, health/armor, weapon, ping, server, match state, recent events).

3. Overhead map with live player dots
Status: TODO
Notes: Add a minimap/overhead tactical view in dashboard or spectate page with real-time player markers and labels.

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
