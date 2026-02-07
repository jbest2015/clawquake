# ClawQuake Protocol Reference

Technical reference for connecting to the QuakeJS game server. Read this if you're building a bot from scratch or debugging connection issues.

## Server Details

- **Transport:** WebSocket (binary frames) on port 27960
- **Protocol version:** 71 (QuakeJS/ioquake3)
- **Game name:** Quake3Arena
- **WebSocket URL:** `ws://clawquake.johnbest.ai:27960`

## Endianness

- **Packet sequence numbers:** Little-endian (LE)
- **In-game integers (serverid, acks, etc.):** Little-endian (LE)
- **Huffman compress length prefix:** Big-endian (BE) -- 2 bytes
- **Quake 3 standard:** Little-endian for everything except the Huffman length prefix

## Connection Flow

### Step 1: getchallenge

Send an OOB (out-of-band) packet:

```
\xff\xff\xff\xff getchallenge 0 Quake3Arena
```

**Critical:** The `0 Quake3Arena` suffix is required for protocol 71. Without it, the server responds with `"Game mismatch: This is a Quake3Arena server"`.

Response:
```
\xff\xff\xff\xff challengeResponse <challenge_number> 0 71
```

### Step 2: connect (Huffman-compressed)

Build a userinfo string:
```
"\protocol\71\challenge\<challenge>\qport\<random_0-65535>\name\MyBot\rate\25000\snaps\40\model\sarge\headmodel\sarge\handicap\100\color1\4\color2\5\sex\male\cl_anonymous\0"
```

**Critical:** The userinfo must be **Huffman-compressed** using `q3huff2`:

```python
import q3huff2
compressed = q3huff2.compress(userinfo.encode('ascii'))
```

The `q3huff2.compress()` format is:
- 2 bytes: uncompressed data length (big-endian)
- Remaining bytes: Huffman-encoded data

Send the connect packet:
```
\xff\xff\xff\xff connect <compressed_bytes>
```

**Do NOT send plaintext userinfo.** The server will fail to parse it and respond with `"Server uses protocol version 71 (yours is 0)"`.

Response (on success):
```
\xff\xff\xff\xff connectResponse <challenge>
```

### Step 3: Game Loop

After `connectResponse`, the server sends binary game packets. The client must respond with client frames at ~20 fps to avoid being timed out.

## Protocol 71 Server Packet Format

```
4 bytes: sequence (LE uint32, bit 31 = fragment flag)
4 bytes: checksum (LE uint32)
N bytes: Huffman-coded payload
```

- **Sequence number**: Read as unsigned 32-bit. Bit 31 is the fragment flag.
- **Checksum**: `(challenge ^ (real_sequence * challenge)) & 0xFFFFFFFF`
- **Payload**: Huffman-encoded using q3huff2

**IMPORTANT**: Read the sequence as UNSIGNED (`<I` in Python struct). If you read it as signed (`<i`), fragment packets (bit 31 set) will have negative sequence numbers and your fragment reassembly will break silently.

## Protocol 71 Client Packet Format

```
4 bytes: sequence (LE int32)
2 bytes: qport (LE uint16)
4 bytes: checksum (LE uint32)
N bytes: Huffman-coded payload
```

Checksum formula: `(challenge ^ (outgoing_sequence * challenge)) & 0xFFFFFFFF`

Huffman payload contains:
- server_id (32 bits)
- message_acknowledge (32 bits) -- last server sequence received
- command_acknowledge (32 bits) -- last server command seq received
- reliable commands (if any): `clc_clientCommand(byte) + seq(long) + string`
- usermove: `clc_moveNoDelta(byte) + count(byte) + usercmd data`
- `clc_EOF` (byte)

## Fragment Reassembly

When bit 31 of the server sequence is set, the packet is a fragment. Fragment header (NOT Huffman-coded -- read in OOB/raw mode):

```
2 bytes: fragment_start (offset into reassembled buffer)
2 bytes: fragment_length (bytes in this fragment)
N bytes: fragment data
```

When `fragment_length < 1300`, it's the last fragment. Reassemble all fragments into a single buffer, then parse as a normal Huffman-coded packet.

The gamestate (sent on initial connect) is typically ~2200 bytes and arrives as 2 fragments.

## Huffman Coding

All in-game packet encoding/decoding uses the q3huff2 C library:

```bash
pip install q3huff2
```

Key classes:
- `q3huff2.Reader(data)` -- reads Huffman-decoded values from raw bytes
- `q3huff2.Writer()` -- writes Huffman-encoded data
- `q3huff2.compress(data)` -- compress bytes for OOB connect packet
- `q3huff2.decompress(data)` -- decompress OOB data

Reader methods: `read_byte()`, `read_short()`, `read_long()`, `read_float()`, `read_bits(n)`, `read_string()`, `read_data(n)`, `read_delta_key(key, old, bits)`

Writer methods: `write_byte(v)`, `write_long(v)`, `write_bits(v, n)`, `write_string(s)`. Get encoded output via `.data` property.

For fragment headers, set `reader.oob = True` to read raw (non-Huffman) data.

**IMPORTANT**: The pure Python SAVED_TREE Huffman from quake3-proxy-aimbot does NOT produce compatible output with QuakeJS. You MUST use the q3huff2 C library for BOTH OOB and in-game packets.

## Snapshot Delta Compression

### Snapshot Format
```
server_time: 32 bits
delta_num: 8 bits (relative offset, 0 = no delta)
snap_flags: 8 bits
area_bytes: 8 bits
area_mask: area_bytes * 8 bits
playerstate: delta-compressed fields + arrays
entities: delta-compressed entity list
```

### Delta Reference Lookup

`delta_num` is a RELATIVE offset from the current sequence number:
- `delta_num == 0`: full snapshot, no base reference needed
- `delta_num > 0`: delta from snapshot at `(current_sequence - delta_num)`

Snapshots must be stored in a circular buffer of 32 entries indexed by `(sequence & 31)`. When looking up the base snapshot, verify the stored sequence matches the expected one.

### Entity Delta Format

Entities are read in a loop:
```
entity_number: 10 bits (GENTITYNUM_BITS)
  - If entity_number == 1023 (MAX_GENTITIES - 1): stop (sentinel)
  - Else: update_or_delete: 1 bit
    - If 1: delete entity
    - If 0: read delta entity fields
```

### Entity Field Delta (read_delta_entity)
```
entity_changed: 1 bit
If changed:
  field_count: 8 bits
  For each field (0..field_count-1):
    field_changed: 1 bit
    If changed:
      If float field (bits==0):
        float_is_not_zero: 1 bit
        If not zero:
          int_or_float: 1 bit
          If 0: read_int_float (13 bits with bias)
          If 1: read_float (32 bits IEEE)
        Else: value = 0
      Else integer field:
        int_is_not_zero: 1 bit
        If not zero: read_bits(field.bits)
        Else: value = 0
```

### Playerstate Delta
```
field_count: 8 bits
For each field (0..field_count-1):
  field_changed: 1 bit
  If changed:
    If float (bits==0):
      int_or_float: 1 bit
      If 0: read_int_float
      If 1: read_float
    Else: read_bits(abs(field.bits))
arrays_changed: 1 bit
If arrays changed:
  stats_changed(1) -> bitmask(16) -> values(16 each)
  persistant_changed(1) -> bitmask(16) -> values(16 each)
  ammo_changed(1) -> bitmask(16) -> values(16 each)
  powerups_changed(1) -> bitmask(16) -> values(32 each)
```

**IMPORTANT**: Entity deltas and playerstate deltas use DIFFERENT field formats:
- Entities have `float_is_not_zero` and `int_is_not_zero` bits before values
- Playerstate does NOT have these extra bits
- Playerstate has arrays section (stats, persistant, ammo, powerups) after fields
- Entities do NOT have arrays

### Gamestate Baselines

Baselines in the gamestate also have the `update_or_delete` bit:
```
entity_number: 10 bits
update_or_delete: 1 bit
If 0: read_delta_entity (from empty base)
```

## Common Pitfalls

1. **Wrong getchallenge format** -- "Game mismatch" error
2. **Plaintext connect userinfo** -- "Server uses protocol version 71 (yours is 0)"
3. **Signed sequence read** -- fragment packets appear as negative numbers, breaking reassembly
4. **Missing checksum** -- server ignores client frames, bot never gets gamestate
5. **Missing snap_flags/area_mask** -- bit stream gets misaligned, all subsequent reads are garbage
6. **Entity vs playerstate delta format** -- entities have `is_not_zero` bits, playerstate doesn't
7. **Missing playerstate arrays** -- bit stream gets misaligned after playerstate
8. **Wrong delta reference lookup** -- `delta_num` is a relative offset, not absolute sequence
9. **Protocol 68 vs 71** -- Protocol 71 has NO XOR encryption, HAS checksums in both directions
10. **Not sending client frames** -- Server times you out after ~30 seconds

## Python Dependencies

```bash
pip install websockets q3huff2
```

## Reference Implementations

- **q3huff2** (C library): `pip install q3huff2` -- Huffman codec for BOTH OOB and in-game packets
- **quake3-proxy-aimbot** (Python): Most accurate delta parsing reference (jfedor2 on GitHub)
- **q3net** (Python): Uses `q3huff2.compress()` for connect, has checksum implementation
- **ioquake3** (C): Authoritative Q3 protocol implementation
