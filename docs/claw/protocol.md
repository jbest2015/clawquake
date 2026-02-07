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
- **Huffman compress length prefix:** Big-endian (BE) — 2 bytes
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

After `connectResponse`, the server sends binary game packets:
- 4-byte little-endian sequence number (bit 31 = fragment flag)
- Huffman-coded payload containing:
  - Server commands (chat, configstrings)
  - Game state (player positions, entity updates)
  - Snapshots (delta-compressed world state)

The client must respond with client frames containing:
- Sequence number
- QPort (2 bytes, little-endian)
- Huffman-coded payload:
  - Server ID acknowledgement
  - Message sequence acknowledgement
  - Command sequence acknowledgement
  - Reliable commands (if any)
  - User movement commands (usercmd)

## Packet Types

### OOB (Out-of-Band) Packets
- Start with `\xff\xff\xff\xff` (4 bytes, value -1 as signed int32)
- Followed by ASCII text
- Used for: getchallenge, connect, disconnect, getinfo, getstatus

### Game Packets
- Start with 4-byte LE sequence number
- Bit 31 of sequence = fragment flag
- Payload is Huffman-coded (after the 4-byte header)
- Protocol 71: **no XOR encryption** (protocol 68 has encryption)

## Huffman Coding

Two different Huffman implementations are needed:

### 1. OOB Connect Packet → `q3huff2` (C library)
```bash
pip install q3huff2
```
Used ONLY for compressing the connect packet userinfo. Format: 2-byte BE length + Huffman data.

### 2. In-Game Packets → Q3 Huffman (SAVED_TREE)
The standard Quake 3 Huffman tree (512-entry SAVED_TREE array) is used for encoding/decoding in-game packet payloads. This is a DIFFERENT tree than what q3huff2 uses for OOB packets.

**Important:** These two Huffman implementations produce DIFFERENT output for the same input. Use the right one for each context.

## Common Pitfalls

1. **Wrong getchallenge format** → "Game mismatch" error
2. **Plaintext connect userinfo** → "Server uses protocol version 71 (yours is 0)"
3. **Wrong Huffman tree for connect** → Server can't decode userinfo
4. **Protocol 68 instead of 71** → Various failures
5. **Missing qport in userinfo** → Connection rejected
6. **Not sending client frames** → Server times you out after ~30 seconds

## Python Dependencies

```bash
pip install websockets q3huff2
```

## Reference Implementations

- **q3net** (Python): Uses `q3huff2.compress()` for connect packets — [engine.py line 46]
- **quake3-proxy-aimbot** (Python): SAVED_TREE Huffman for in-game packets
- **ioquake3** (C): Authoritative Q3 protocol implementation
