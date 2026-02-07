"""
Quake 3 network protocol parser.

Handles the server frame format: connectionless packets (challenge, connect)
and connected packets (gamestate, snapshots, commands, config strings).

The Q3 protocol sends all data as Huffman-coded bit streams. Connected packets
use sequence numbers for ordering and can be fragmented.
"""

import struct
import logging
from .defs import (
    svc_ops_e, CONNECTIONLESS_MARKER, FRAGMENT_BIT, GENTITYNUM_BITS,
    MAX_GENTITIES, MAX_CONFIGSTRINGS, MAX_RELIABLE_COMMANDS,
)

logger = logging.getLogger('clawquake.protocol')
from .buffers import Buffer
from .snapshot import (
    Snapshot, PlayerState, EntityState,
    read_delta_playerstate, read_delta_entity,
)


class ServerFrame:
    """Parsed result of a connected server packet."""

    def __init__(self):
        self.sequence = 0
        self.reliable_ack = 0
        self.commands = []          # list of (seq, text)
        self.command_seq = 0        # highest command sequence
        self.config_strings = {}    # index -> value
        self.snapshot = None        # Snapshot or None
        self.checksum_feed = 0
        self.client_num = -1
        self.server_id = 0


def parse_connectionless(data):
    """Parse a connectionless (OOB) packet. Returns (command, args) or None."""
    # Skip the 0xFFFFFFFF marker (4 bytes)
    text = data[4:].decode('ascii', errors='replace').strip('\x00').strip()
    parts = text.split(None, 1)
    command = parts[0] if parts else ''
    args = parts[1] if len(parts) > 1 else ''
    return command, args


def parse_server_frame(buf, baselines, old_snapshots, server_commands, current_sequence=0):
    """
    Parse a full server frame from a Huffman-coded buffer.

    Args:
        buf: Buffer positioned after sequence/reliable_ack header
        baselines: dict of entity number -> EntityState (baselines)
        old_snapshots: dict of (sequence & PACKET_MASK) -> Snapshot (circular buffer)
        server_commands: list of server command strings (for delta reference)
        current_sequence: current message sequence number (for snapshot delta lookup)

    Returns:
        ServerFrame with parsed data
    """
    frame = ServerFrame()
    frame.reliable_ack = buf.read_long()

    while True:
        if buf.bits_remaining < 8:
            break

        cmd = buf.read_byte()

        if cmd == svc_ops_e.svc_EOF:
            break
        elif cmd == svc_ops_e.svc_nop:
            continue
        elif cmd == svc_ops_e.svc_serverCommand:
            _parse_server_command(buf, frame)
        elif cmd == svc_ops_e.svc_gamestate:
            _parse_gamestate(buf, frame, baselines)
        elif cmd == svc_ops_e.svc_configstring:
            _parse_configstring(buf, frame)
        elif cmd == svc_ops_e.svc_baseline:
            _parse_baseline(buf, baselines)
        elif cmd == svc_ops_e.svc_snapshot:
            _parse_snapshot(buf, frame, baselines, old_snapshots, current_sequence)
        elif cmd == svc_ops_e.svc_download:
            break  # Not handling downloads
        else:
            break  # Unknown command, stop parsing

    return frame


def _parse_server_command(buf, frame):
    """Parse svc_serverCommand: a reliable command from the server."""
    seq = buf.read_long()
    text = buf.read_string().decode('ascii', errors='replace')
    frame.commands.append((seq, text))
    if seq > frame.command_seq:
        frame.command_seq = seq


def _parse_gamestate(buf, frame, baselines):
    """Parse svc_gamestate: full game state dump (sent on connect).

    Format:
      command_seq: 32 bits
      Loop of:
        op: 8 bits (svc_configstring=3, svc_baseline=4, svc_EOF=8)
        If configstring: index(16) + string
        If baseline: entity_number(10) + update_or_delete(1) + delta_entity
      client_num: 32 bits
      checksum_feed: 32 bits
    """
    frame.command_seq = buf.read_long()

    while True:
        cmd = buf.read_byte()

        if cmd == svc_ops_e.svc_EOF:
            break
        elif cmd == svc_ops_e.svc_configstring:
            index = buf.read_short()
            text = buf.read_string().decode('ascii', errors='replace')
            frame.config_strings[index] = text
        elif cmd == svc_ops_e.svc_baseline:
            num = buf.read_bits(GENTITYNUM_BITS)
            # Baseline also has update_or_delete bit
            if not buf.read_bit():  # 0 = update
                es = read_delta_entity(buf, None, num)
                if es:
                    baselines[num] = es
            # if bit is 1 (delete), skip - unusual in gamestate
        else:
            logger.warning(f"Unknown gamestate op: {cmd}")
            break

    frame.client_num = buf.read_long()
    frame.checksum_feed = buf.read_long()


def _parse_configstring(buf, frame):
    """Parse svc_configstring: single config string update."""
    index = buf.read_short()
    text = buf.read_string().decode('ascii', errors='replace')
    frame.config_strings[index] = text


def _parse_baseline(buf, baselines):
    """Parse svc_baseline: entity baseline for delta compression."""
    num = buf.read_bits(GENTITYNUM_BITS)
    if not buf.read_bit():  # update_or_delete: 0 = update
        es = read_delta_entity(buf, None, num)
        if es:
            baselines[num] = es


def _parse_snapshot(buf, frame, baselines, old_snapshots, current_sequence=0):
    """Parse svc_snapshot: delta-compressed game state snapshot.

    Args:
        buf: Buffer positioned at start of snapshot data
        frame: ServerFrame to populate
        baselines: dict of entity number -> EntityState (baselines)
        old_snapshots: dict of (sequence & PACKET_MASK) -> Snapshot
        current_sequence: current message sequence number (for delta lookup)
    """
    from .defs import PACKET_BACKUP, PACKET_MASK

    snap = Snapshot()
    snap.server_time = buf.read_long()
    snap.message_num = current_sequence

    # delta_num is a relative offset: 0 = no delta, N = delta from (sequence - N)
    delta_num = buf.read_byte()

    # snap_flags and area_mask (must be read to advance buffer correctly)
    snap_flags = buf.read_byte()
    area_bytes = buf.read_byte()
    for _ in range(area_bytes):
        buf.read_byte()  # area_mask data

    if delta_num == 0:
        # No delta - full snapshot
        old_snap = None
    else:
        # Look up the base snapshot by relative offset
        base_seq = current_sequence - delta_num
        base_key = base_seq & PACKET_MASK
        old_snap = old_snapshots.get(base_key)
        if old_snap and old_snap.message_num != base_seq:
            # Stale entry in circular buffer — can't delta from it
            old_snap = None
        if not old_snap:
            # Can't decode this snapshot without the reference
            return

    # Read player state
    old_ps = old_snap.player_state if old_snap else None
    snap.player_state = read_delta_playerstate(buf, old_ps)

    # Read entity states
    # Format: entity_number(10 bits), then either:
    #   - MAX_GENTITIES-1 = sentinel (end of entities)
    #   - update_or_delete(1 bit): 1=delete, 0=update via read_delta_entity
    old_entities = old_snap.entities if old_snap else {}
    entities = dict(old_entities)  # start with copy of old entities

    entity_count = 0
    while True:
        entity_count += 1
        if entity_count > MAX_GENTITIES:
            logger.warning(f"Entity parsing exceeded MAX_GENTITIES ({MAX_GENTITIES}), aborting")
            break

        new_num = buf.read_bits(GENTITYNUM_BITS)
        if new_num == MAX_GENTITIES - 1:
            break  # sentinel - end of entity updates

        if buf.read_bit():  # update_or_delete: 1 = delete
            if new_num in entities:
                del entities[new_num]
        else:
            # Update: read delta entity
            old_es = entities.get(new_num) or baselines.get(new_num)
            es = read_delta_entity(buf, old_es, new_num)
            if es:
                entities[new_num] = es

    snap.entities = entities

    frame.snapshot = snap
