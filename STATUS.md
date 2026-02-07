# ClawQuake Bot Client — Development Status

## Current State: Bot Connects and Receives Game Data

The Q3 bot client successfully connects to the QuakeJS server (protocol 71),
receives gamestate via fragment reassembly, parses delta-compressed snapshots,
and maintains a live view of entity positions and player state.

**What works:**
- WebSocket connection to QuakeJS server on port 27960
- Protocol 71 challenge/connect handshake (Huffman-compressed userinfo)
- Checksum calculation for both client and server frames
- Fragment reassembly for large packets (gamestate arrives as ~2 fragments)
- Gamestate parsing: config strings, entity baselines, client_num, server_id
- Delta-compressed snapshot parsing: playerstate + entity states
- Snapshot circular buffer (32 entries) with relative delta lookup
- Client frame keepalive (prevents server timeout)
- Clean connect/disconnect lifecycle
- State machine: CA_DISCONNECTED -> CA_CHALLENGING -> CA_CONNECTING -> CA_CONNECTED -> CA_PRIMED -> CA_ACTIVE

**What doesn't work yet:**
- Bot only sends null usercmds (no actual movement/aiming/shooting)
- No high-level agent API (bot/agent.py referenced in setup.md doesn't exist yet)
- No position extraction from playerstate for navigation
- No weapon firing or target selection logic

## Key Files

| File | Purpose |
|------|---------|
| `bot/client.py` | Async WebSocket Q3 client — connection, frame send/receive, state machine |
| `bot/protocol.py` | Server frame parser — gamestate, snapshots, commands, config strings |
| `bot/snapshot.py` | Delta compression — entity fields, playerstate fields + arrays |
| `bot/buffers.py` | Huffman buffer wrapper around q3huff2 C library |
| `bot/defs.py` | Protocol constants, field tables, enums |
| `docs/claw/protocol.md` | Comprehensive protocol 71 reference |
| `docs/claw/setup.md` | Bot development guide |

## Bugs Fixed (This Session)

### 1. Segfault in q3huff2 C Extension
**Symptom:** Process exit code -11 (SIGSEGV) during snapshot parsing.
**Root cause:** `bits_remaining` in Buffer always returned `len(data) * 8` and never
decreased, so the parser loop never stopped early, causing reads past buffer end
into the C extension's memory.
**Fix:** Added `_bytes_read` tracking to Buffer. All read methods wrapped in
try/except that raises `BufferOverflow` before the C extension can segfault.

### 2. Gamestate Not Loading (client_num=-1, config_strings=0)
**Symptom:** Bot appeared connected but had no game data.
**Root causes (3 combined):**
1. **Signed sequence read** — Fragment packets (bit 31 set) appeared as negative
   sequence numbers. `struct.unpack('<i')` gives -4294967291 instead of the
   correct unsigned value. `~FRAGMENT_BIT` in Python is `-2147483649` (arbitrary
   precision), not `0x7FFFFFFF`.
2. **Missing snap_flags + area_mask** — Snapshot parser skipped these fields,
   causing bit stream misalignment for everything after.
3. **Wrong entity delta format** — Entity deltas have `float_is_not_zero` and
   `int_is_not_zero` bits that playerstate deltas don't have. Also missing
   `update_or_delete` bit at entity loop level and in gamestate baselines.

**Fix:** Read sequence as unsigned (`<I`). Added snap_flags/area_mask parsing.
Complete rewrite of snapshot.py with correct delta formats matching the
quake3-proxy-aimbot reference implementation.

### 3. Fragment Reassembly Broken
**Symptom:** Fragments never reassembled — the reassembly dict never matched
because fragment sequences were stored as negative numbers.
**Root cause:** Same as #2.1 — signed sequence read.
**Fix:** Unsigned sequence read + mask with `0x7FFFFFFF` instead of `~FRAGMENT_BIT`.

### 4. Entity Delta Parse Errors
**Symptom:** "Entity last_field=100 > field_count=51" warnings, followed by
"Entity parsing exceeded MAX_GENTITIES" — bit stream completely misaligned.
**Root cause:** Entity delta format was fundamentally wrong:
- Missing `entity_changed` bit at start
- Missing `float_is_not_zero` / `int_is_not_zero` bits before values
- Missing `update_or_delete` bit in entity loop and baselines
- Missing playerstate arrays section (stats, persistant, ammo, powerups)
**Fix:** Complete rewrite of read_delta_entity and read_delta_playerstate
in snapshot.py.

### 5. State Transition Timing
**Symptom:** `on_connected` callback fired before gamestate was loaded (CA_ACTIVE
reached on first snapshot, even though gamestate hadn't arrived yet).
**Fix:** CA_CONNECTED -> CA_PRIMED only after receiving gamestate (has config
strings AND client_num >= 0). CA_PRIMED -> CA_ACTIVE only after first snapshot
post-gamestate.

## Verified Working Output

```
PKT #1: OOB text=challengeResponse 1855781903 0 71
PKT #2: OOB text=connectResponse
PKT #3: seq=1 frag=True len=1308
PKT #4: seq=1 frag=True len=907
  -> state=connstate_t.CA_PRIMED client_num=1 cs=32 bl=27
PKT #5: seq=2 frag=False len=95
  -> state=connstate_t.CA_ACTIVE client_num=1 cs=32 bl=27
IN GAME! client_num=1
SNAP #1: time=197892
Final: state=connstate_t.CA_ACTIVE snaps=115 client_num=1 cs=32 bl=27
CLEAN EXIT
```

## Architecture Notes

The protocol has critical differences between entity and playerstate delta formats:

- **Entity deltas:** `entity_changed(1) -> field_count(8) -> for each: changed(1) -> [float: is_not_zero(1) -> int_or_float(1) -> value] [int: is_not_zero(1) -> value]`
- **Playerstate deltas:** `field_count(8) -> for each: changed(1) -> [float: int_or_float(1) -> value] [int: value]` + arrays section
- Entities have `is_not_zero` bits; playerstate does NOT
- Playerstate has arrays (stats, persistant, ammo, powerups); entities do NOT

The q3huff2 C library is required for both OOB (connect packet) and in-game
(all frame payloads) Huffman coding. The pure Python SAVED_TREE implementation
from quake3-proxy-aimbot is NOT compatible with QuakeJS.

## Next Steps

1. **Movement system** — Send real usercmds with position/angle/buttons
2. **Agent API** — High-level interface for bot AI (get position, aim at target, fire)
3. **Navigation** — Basic waypoint or line-of-sight movement
4. **Combat** — Target selection, weapon switching, aim prediction
5. **Spectator/orchestrator integration** — Connect to the broader ClawQuake platform
