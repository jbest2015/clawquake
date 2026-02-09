"""
Quake 3 WebSocket client - connects to QuakeJS game servers.

Handles the full connection lifecycle:
  1. getchallenge → challengeResponse
  2. connect (with userinfo) → connectResponse
  3. Game loop: receive snapshots, send client frames

QuakeJS WebSocket frames contain the exact same binary data as Q3 UDP packets.
"""

import asyncio
import struct
import random
import time
import logging
import websockets
import q3huff2

from .defs import (
    connstate_t, clc_ops_e, configstr_t,
    FRAGMENT_BIT, MAX_RELIABLE_COMMANDS, PACKET_MASK,
)
from .buffers import BufferOverflow
from .buffers import Buffer
from .protocol import parse_connectionless, parse_server_frame

logger = logging.getLogger('clawquake.client')

BUTTON_ATTACK = 1
DEFAULT_MOVE_FRAMES = 8
DEFAULT_BUTTON_FRAMES = 2
DEFAULT_VIEW_FRAMES = 8


class UserInfo(dict):
    """Q3 userinfo string builder."""

    def serialize(self):
        parts = []
        for key, value in self.items():
            parts.append(f"\\{key}\\{value}")
        return '"' + ''.join(parts) + '"'


def default_userinfo(name="ClawBot"):
    ui = UserInfo()
    ui['name'] = name
    ui['model'] = 'sarge'
    ui['headmodel'] = 'sarge'
    ui['team_model'] = 'james'
    ui['team_headmodel'] = 'james'
    ui['handicap'] = '100'
    ui['teamtask'] = '0'
    ui['sex'] = 'male'
    ui['color1'] = '4'
    ui['color2'] = '5'
    ui['rate'] = '25000'
    ui['snaps'] = '40'
    ui['cl_maxpackets'] = '125'
    ui['cl_timeNudge'] = '0'
    ui['cl_anonymous'] = '0'
    return ui


class Q3Client:
    """
    Async Quake 3 client that connects via WebSocket to a QuakeJS server.

    Usage:
        client = Q3Client("ws://server:27960", name="MyBot")
        client.on_snapshot = my_snapshot_handler
        client.on_chat = my_chat_handler
        await client.connect()
        await client.run()
    """

    def __init__(self, server_url, name="ClawBot", protocol=71, pure_checksums=None):
        self.server_url = server_url
        self.protocol_version = protocol
        self.userinfo = default_userinfo(name)

        # Connection state
        self.state = connstate_t.CA_DISCONNECTED
        self.challenge = 0
        self.qport = random.randint(0, 0xFFFF)
        self.server_id = 0
        self.checksum_feed = 0
        self.client_num = -1
        self.sv_pure = 0

        # Sequence tracking
        self.message_seq = 0        # last received server sequence
        self.command_seq = 0        # last received server command seq
        self.outgoing_seq = 1       # our outgoing sequence counter
        self.reliable_ack = 0       # server's ack of our reliable commands
        self.reliable_seq = 0       # our reliable command sequence

        # Reliable commands (circular buffer)
        self.reliable_commands = [""] * MAX_RELIABLE_COMMANDS
        self.server_commands = [""] * MAX_RELIABLE_COMMANDS

        # Game state
        self.config_strings = {}
        self.baselines = {}
        self.snapshots = {}         # (sequence & PACKET_MASK) -> Snapshot (circular buffer)
        self.current_snapshot = None
        self.server_time = 0

        # Pending input state (held for a few frames so lower-rate AI loops still move)
        self._held_forward = 0
        self._held_right = 0
        self._held_up = 0
        self._held_forward_frames = 0
        self._held_right_frames = 0
        self._held_up_frames = 0
        self._held_attack_frames = 0
        self._pending_weapon = 0
        self._aim_angles = None
        self._aim_frames = 0
        self._pure_checksums = pure_checksums  # "cgame ui @ refs... checksum" (no leading "cp <serverid>")
        self._pure_sent = False
        self._begin_sent = False
        self._last_usercmd = {
            "server_time": 0,
            "angles": [0, 0, 0],
            "forwardmove": 0,
            "rightmove": 0,
            "upmove": 0,
            "buttons": 0,
            "weapon": 0,
        }

        # WebSocket
        self._ws = None
        self._running = False

        # Fragment reassembly
        self._frag_sequence = 0
        self._frag_buffer = bytearray()

        # Callbacks
        self.on_snapshot = None     # async fn(client, snapshot)
        self.on_chat = None         # async fn(client, sender, message)
        self.on_connected = None    # async fn(client)
        self.on_disconnected = None # async fn(client, reason)
        self.on_command = None      # async fn(client, seq, text)
        self.on_configstring = None # async fn(client, index, value)

    # --- Public API ---

    async def connect(self):
        """Connect to the QuakeJS server."""
        logger.info(f"Connecting to {self.server_url}")
        self._ws = await websockets.connect(
            self.server_url,
            max_size=None,
            ping_interval=None,
        )
        self._begin_sent = False
        self.state = connstate_t.CA_CONNECTING
        await self._send_connectionless("getchallenge 0 Quake3Arena")

    async def disconnect(self):
        """Disconnect from the server."""
        self._running = False
        if self.state.value >= connstate_t.CA_CONNECTED.value:
            try:
                await self._send_connectionless("disconnect")
            except Exception:
                pass
        self.state = connstate_t.CA_DISCONNECTED
        self._begin_sent = False
        if self._ws:
            await self._ws.close()
            self._ws = None

    async def run(self, fps=20):
        """Main game loop. Receives packets and sends client frames at the given FPS."""
        self._running = True
        frame_time = 1.0 / fps

        while self._running:
            try:
                frame_start = asyncio.get_event_loop().time()

                # Drain all pending packets from the server
                for _ in range(5):
                    try:
                        data = await asyncio.wait_for(self._ws.recv(), timeout=0.005)
                        if isinstance(data, bytes):
                            await self._handle_packet(data)
                    except asyncio.TimeoutError:
                        break  # No more pending data

                # Send client frame if connected
                if self.state.value >= connstate_t.CA_CONNECTED.value:
                    frame = self._build_client_frame()
                    if frame:
                        await self._ws.send(frame)

                # Sleep for remaining frame time
                elapsed = asyncio.get_event_loop().time() - frame_start
                sleep_time = max(0.001, frame_time - elapsed)
                await asyncio.sleep(sleep_time)

            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"Connection closed: {e}")
                self._running = False
                self.state = connstate_t.CA_DISCONNECTED
                if self.on_disconnected:
                    await self.on_disconnected(self, str(e))
            except Exception as e:
                logger.error(f"Error in game loop: {e}", exc_info=True)
                await asyncio.sleep(0.1)

    def queue_command(self, command):
        """Queue a reliable command to send to the server. Returns command sequence."""
        command = self._normalize_console_command(command)
        if not command:
            return None
        assert 64 > self.reliable_seq - self.reliable_ack, "Reliable command overflow"
        self.reliable_seq += 1
        inx = self.reliable_seq % 64
        self.reliable_commands[inx] = command
        return self.reliable_seq

    def queue_commands(self, commands):
        """Queue multiple reliable commands at once (batched). Returns list of sequences."""
        seqs = []
        for cmd in commands:
            seqs.append(self.queue_command(cmd))
        return seqs

    def say(self, message):
        """Send a chat message to all players."""
        clean = str(message).replace('"', "'").strip()
        return self.queue_command(f'say "{clean}"')

    def say_team(self, message):
        """Send a team chat message."""
        clean = str(message).replace('"', "'").strip()
        return self.queue_command(f'say_team "{clean}"')

    @staticmethod
    def _normalize_console_command(command):
        """Normalize incoming console command text, accepting optional '/' prefix."""
        cmd = str(command).strip()
        while cmd.startswith('/'):
            cmd = cmd[1:].lstrip()
        return cmd

    def hold_move(self, forward=0, right=0, up=0, frames=DEFAULT_MOVE_FRAMES):
        """Hold movement axes for a short duration measured in client frames."""
        if forward:
            self._set_axis_hold("forward", forward, frames)
        if right:
            self._set_axis_hold("right", right, frames)
        if up:
            self._set_axis_hold("up", up, frames)

    def hold_forward(self, frames=DEFAULT_MOVE_FRAMES):
        self.hold_move(forward=127, frames=frames)

    def hold_back(self, frames=DEFAULT_MOVE_FRAMES):
        self.hold_move(forward=-127, frames=frames)

    def hold_left(self, frames=DEFAULT_MOVE_FRAMES):
        self.hold_move(right=-127, frames=frames)

    def hold_right(self, frames=DEFAULT_MOVE_FRAMES):
        self.hold_move(right=127, frames=frames)

    def jump(self, frames=DEFAULT_BUTTON_FRAMES):
        self.hold_move(up=127, frames=frames)

    def attack(self, frames=DEFAULT_BUTTON_FRAMES):
        self._held_attack_frames = max(self._held_attack_frames, frames)

    def select_weapon(self, weapon_num):
        self._pending_weapon = weapon_num & 0xFF

    def set_pure_checksums(self, cgame_checksum, ui_checksum, referenced_checksums):
        """Set pure checksum payload (checksums must be pure checksums, not sv_paks)."""
        refs = [int(x) for x in referenced_checksums]
        encoded = self.checksum_feed
        for value in refs:
            encoded ^= value
        encoded ^= len(refs)
        refs_part = " ".join(str(v) for v in refs)
        if refs_part:
            self._pure_checksums = f"{int(cgame_checksum)} {int(ui_checksum)} @ {refs_part} {int(encoded)}"
        else:
            self._pure_checksums = f"{int(cgame_checksum)} {int(ui_checksum)} @ {int(encoded)}"
        self._pure_sent = False

    def set_pure_checksums_raw(self, pure_checksums_payload):
        """Set raw payload for cp command: '<cgame> <ui> @ <refs...> <encoded>'."""
        self._pure_checksums = pure_checksums_payload.strip()
        self._pure_sent = False

    def set_viewangles(self, pitch=None, yaw=None, roll=None, frames=DEFAULT_VIEW_FRAMES):
        """Set absolute viewangles (degrees) for a short frame window."""
        current_pitch, current_yaw, current_roll = self._current_viewangles()
        new_pitch = current_pitch if pitch is None else self._normalize_pitch(pitch)
        new_yaw = current_yaw if yaw is None else self._normalize_yaw(yaw)
        new_roll = current_roll if roll is None else self._normalize_roll(roll)

        self._aim_angles = [new_pitch, new_yaw, new_roll]
        self._aim_frames = max(self._aim_frames, max(1, int(frames)))

    def turn(self, yaw_delta=0.0, pitch_delta=0.0, roll_delta=0.0, frames=DEFAULT_VIEW_FRAMES):
        """Apply relative angle deltas in degrees."""
        pitch, yaw, roll = self._current_viewangles()
        self.set_viewangles(
            pitch=pitch + float(pitch_delta),
            yaw=yaw + float(yaw_delta),
            roll=roll + float(roll_delta),
            frames=frames,
        )

    def _set_axis_hold(self, axis, value, frames):
        value = self._clamp_signed_char(value)
        frames = max(1, int(frames))

        if axis == "forward":
            self._held_forward = value
            self._held_forward_frames = max(self._held_forward_frames, frames)
        elif axis == "right":
            self._held_right = value
            self._held_right_frames = max(self._held_right_frames, frames)
        elif axis == "up":
            self._held_up = value
            self._held_up_frames = max(self._held_up_frames, frames)

    # --- Packet handling ---

    async def _handle_packet(self, data):
        """Handle a raw packet from the server."""
        if len(data) < 4:
            return

        # Read as unsigned to handle fragment bit correctly
        raw_seq = struct.unpack_from('<I', data, 0)[0]

        if raw_seq == 0xFFFFFFFF:
            # Connectionless packet
            await self._handle_connectionless(data)
        else:
            # Connected packet
            await self._handle_connected(raw_seq, data)

    async def _handle_connectionless(self, data):
        """Handle OOB (out-of-band) connectionless packet."""
        command, args = parse_connectionless(data)
        logger.debug(f"OOB: {command} {args[:80]}")

        if command == "challengeResponse":
            parts = args.split()
            self.challenge = int(parts[0]) if parts else 0
            self.state = connstate_t.CA_CHALLENGING
            logger.info(f"Got challenge: {self.challenge}")
            await self._send_connect()

        elif command == "connectResponse":
            self.state = connstate_t.CA_CONNECTED
            logger.info("Connected!")

        elif command == "print":
            logger.info(f"Server print: {args}")

        elif command == "disconnect":
            logger.info(f"Disconnected by server: {args}")
            self.state = connstate_t.CA_DISCONNECTED
            self._running = False
            if self.on_disconnected:
                await self.on_disconnected(self, args)

    async def _handle_connected(self, raw_seq, data):
        """Handle a connected (in-game) packet.

        Protocol 71 server packet format:
          4 bytes: sequence (LE uint32, bit 31 = fragment flag)
          4 bytes: checksum (LE uint32)
          N bytes: Huffman-coded payload (or fragment header + data if fragmented)

        raw_seq is already unsigned from _handle_packet.
        """
        if not self.state.value >= connstate_t.CA_CONNECTED.value:
            return

        # Strip fragment bit (bit 31)
        is_fragmented = bool(raw_seq & FRAGMENT_BIT)
        real_sequence = raw_seq & 0x7FFFFFFF

        if real_sequence <= self.message_seq:
            return  # Old/duplicate packet

        # For protocol 71, skip the 4-byte checksum after the sequence header
        if self.protocol_version == 71:
            payload = data[8:]  # skip 4-byte seq + 4-byte checksum
        else:
            payload = data[4:]  # skip 4-byte seq only

        # Handle fragmented packets
        if is_fragmented:
            await self._handle_fragment(real_sequence, payload)
            return

        # Parse the Huffman-coded payload
        if len(payload) < 4:
            # Too small to contain even a reliable_ack
            self.message_seq = real_sequence
            return

        buf = Buffer(payload)

        try:
            frame = parse_server_frame(
                buf, self.baselines, self.snapshots, self.server_commands,
                current_sequence=real_sequence,
            )
        except BufferOverflow as e:
            logger.warning(f"Buffer overflow parsing frame seq={real_sequence}: {e}")
            self.message_seq = real_sequence
            return
        except Exception as e:
            logger.error(f"Failed to parse server frame seq={real_sequence}: {e}")
            self.message_seq = real_sequence
            return

        self.message_seq = real_sequence
        await self._process_frame(frame)

    async def _process_frame(self, frame):
        """Process a parsed server frame: update state, handle events, fire callbacks."""
        self.reliable_ack = frame.reliable_ack

        # Handle gamestate (initial connect or map change)
        if frame.config_strings and frame.client_num >= 0:
            self._load_gamestate(frame)
            # Reset to CA_CONNECTED so the begin transition fires below
            if self.state.value > connstate_t.CA_CONNECTED.value:
                logger.info("New gamestate received mid-game, resetting to CA_CONNECTED")
                self.state = connstate_t.CA_CONNECTED

        # Handle commands
        for seq, text in frame.commands:
            if seq > self.command_seq:
                self.server_commands[seq % 64] = text
                await self._handle_server_command(seq, text)

        if frame.command_seq > self.command_seq:
            self.command_seq = frame.command_seq

        # Handle snapshot
        if frame.snapshot:
            self.current_snapshot = frame.snapshot
            self.server_time = frame.snapshot.server_time

            # Store in circular buffer indexed by (sequence & PACKET_MASK)
            snap_key = self.message_seq & PACKET_MASK
            self.snapshots[snap_key] = frame.snapshot

            if self.on_snapshot:
                await self.on_snapshot(self, frame.snapshot)

        # Transition to active state
        # CA_CONNECTED -> CA_PRIMED: after receiving gamestate
        if self.state == connstate_t.CA_CONNECTED and frame.config_strings and frame.client_num >= 0:
            self.state = connstate_t.CA_PRIMED
            logger.info(f"Gamestate received, primed (client_num={self.client_num})")
            # QuakeJS protocol 71 enters the world from usercmd traffic and does
            # not expose the vanilla "begin" client command.
            if self.protocol_version != 71:
                self.queue_command(f"begin {self.server_id}")
                logger.info(f"Sent begin for server_id={self.server_id}")
            else:
                logger.debug("Protocol 71 detected: skipping begin command")
        # CA_PRIMED -> CA_ACTIVE: after receiving first snapshot post-gamestate
        if self.state == connstate_t.CA_PRIMED and frame.snapshot:
            self.state = connstate_t.CA_ACTIVE
            logger.info("Game state active - in game!")
            if self.on_connected:
                await self.on_connected(self)

    async def _handle_fragment(self, sequence, payload):
        """Reassemble a fragmented packet.

        Fragment format (after sequence + checksum):
          2 bytes: fragment_start (offset into reassembled packet)
          2 bytes: fragment_length (bytes in this fragment)
          N bytes: fragment data

        When fragment_length < 1300, it's the last fragment. Reassemble and parse.
        """
        FRAGMENT_SIZE = 1300

        if sequence != self._frag_sequence:
            # New fragmented packet, reset buffer
            self._frag_sequence = sequence
            self._frag_buffer = bytearray()

        # Read fragment header using q3huff2.Reader (OOB-like, no Huffman)
        reader = q3huff2.Reader(bytes(payload))
        reader.oob = True  # fragment headers are not Huffman-coded
        frag_start = reader.read_short()
        frag_length = reader.read_short()
        frag_data = reader.read_data(frag_length)

        if len(self._frag_buffer) != frag_start:
            logger.warning(f"Fragment gap: expected offset {len(self._frag_buffer)}, got {frag_start}")
            self._frag_buffer = bytearray()
            return

        self._frag_buffer.extend(frag_data if isinstance(frag_data, (bytes, bytearray)) else frag_data.encode())

        if frag_length < FRAGMENT_SIZE:
            # Last fragment — process the reassembled packet
            logger.debug(f"Fragment reassembled: seq={sequence} total={len(self._frag_buffer)} bytes")
            buf = Buffer(bytes(self._frag_buffer))
            self._frag_buffer = bytearray()

            try:
                frame = parse_server_frame(
                    buf, self.baselines, self.snapshots, self.server_commands,
                    current_sequence=sequence,
                )
            except BufferOverflow as e:
                logger.warning(f"Buffer overflow parsing reassembled frame: {e}")
                return
            except Exception as e:
                logger.error(f"Failed to parse reassembled frame: {e}", exc_info=True)
                return

            self.message_seq = sequence
            await self._process_frame(frame)

    def _load_gamestate(self, frame):
        """Load full gamestate from a gamestate frame."""
        for index, value in frame.config_strings.items():
            self.config_strings[index] = value
            self._process_configstring(index, value)

        if frame.client_num >= 0:
            self.client_num = frame.client_num
        if frame.checksum_feed:
            self.checksum_feed = frame.checksum_feed

        self.command_seq = frame.command_seq
        logger.info(f"Gamestate loaded: client_num={self.client_num}, "
                     f"server_id={self.server_id}, "
                     f"{len(frame.config_strings)} config strings, "
                     f"{len(self.baselines)} baselines")

        self._maybe_send_pure_handshake()

    def _process_configstring(self, index, value):
        """Process a config string update."""
        if index == configstr_t.CS_SYSTEMINFO:
            # Parse system info for server_id
            pairs = self._parse_info_string(value)
            if 'sv_serverid' in pairs:
                self.server_id = int(pairs['sv_serverid'])
            if 'sv_pure' in pairs:
                try:
                    self.sv_pure = int(pairs['sv_pure'])
                except ValueError:
                    self.sv_pure = 0

    def _maybe_send_pure_handshake(self):
        """
        Send pure handshake if server requires it.

        For sv_pure=1, server ignores usercmd movement until it receives a valid
        'cp' command payload generated from the client's local pak set.
        """
        if self._pure_sent:
            return
        if self.sv_pure == 0:
            self._pure_sent = True
            return

        if self._pure_checksums:
            self.queue_command(f"cp {self.server_id} {self._pure_checksums}")
            self.queue_command("vdr")
            logger.info("Sent pure checksum handshake (cp/vdr)")
            self._pure_sent = True
        else:
            logger.warning(
                "Server requires pure checksums (sv_pure=1) but no pure checksum payload is configured; "
                "movement/spawn usercmds will be ignored until cp is sent."
            )

    def _parse_info_string(self, text):
        """Parse a Q3 info string (\\key\\value\\key2\\value2) into a dict."""
        text = text.strip('"')
        parts = text.split('\\')
        result = {}
        it = iter(parts[1:] if not parts[0] else parts)
        for key in it:
            try:
                result[key] = next(it)
            except StopIteration:
                break
        return result

    async def _handle_server_command(self, seq, text):
        """Handle a server command."""
        # Log print commands (contains kill messages, player events)
        if text.startswith("print "):
            logger.info(f"SERVER_PRINT: {text[6:120]}")
        if self.on_command:
            await self.on_command(self, seq, text)

        # Parse chat messages
        if text.startswith("chat ") or text.startswith("tchat "):
            parts = text.split('"')
            if len(parts) >= 2:
                message = parts[1]
                # Try to extract sender name
                if ': ' in message:
                    sender, msg = message.split(': ', 1)
                    sender = sender.strip('\x19')  # Strip Q3 color codes
                else:
                    sender = "?"
                    msg = message
                if self.on_chat:
                    await self.on_chat(self, sender, msg)

        # Handle disconnect
        if text.startswith("disconnect"):
            parts = text.split('"')
            reason = parts[1] if len(parts) >= 2 else "no reason"
            logger.info(f"Server disconnect: {reason}")
            self.state = connstate_t.CA_DISCONNECTED
            self._running = False
            if self.on_disconnected:
                await self.on_disconnected(self, reason)

    # --- Sending ---

    async def _send_connectionless(self, text):
        """Send a connectionless (OOB) packet."""
        data = b'\xff\xff\xff\xff' + text.encode('ascii')
        await self._ws.send(data)

    async def _send_connect(self):
        """Send the connect packet with Huffman-compressed userinfo.

        Protocol 71 (QuakeJS) requires the userinfo to be compressed using
        q3huff2. The format is: 2-byte big-endian uncompressed length prefix
        followed by Huffman-encoded data.
        """
        # Build userinfo string with protocol fields first
        userinfo = (
            f'"'
            f'\\protocol\\{self.protocol_version}'
            f'\\challenge\\{self.challenge}'
            f'\\qport\\{self.qport}'
        )
        for key, value in self.userinfo.items():
            userinfo += f'\\{key}\\{value}'
        userinfo += '"'

        # Compress using q3huff2 (2-byte BE length + Huffman bits)
        compressed = q3huff2.compress(userinfo.encode('ascii'))
        logger.debug(f"Connect userinfo: {len(userinfo)} chars -> {len(compressed)} bytes compressed")

        # OOB packet: \xff\xff\xff\xff + "connect " + compressed_userinfo
        packet = b'\xff\xff\xff\xff' + b'connect ' + compressed
        await self._ws.send(packet)

    def _build_client_frame(self):
        """Build a client frame packet to send to the server.

        Protocol 71 frame format:
          4 bytes: sequence number (LE int32)
          2 bytes: qport (LE uint16)
          4 bytes: checksum = challenge ^ (sequence * challenge) (LE uint32)
          N bytes: Huffman-encoded payload (serverid, acks, commands, usermove, EOF)
        """
        if self.state.value < connstate_t.CA_CONNECTED.value:
            return None

        writer = Buffer()

        # Huffman-coded payload
        writer.write_long(self.server_id)       # serverid
        writer.write_long(self.message_seq)     # messageAcknowledge
        writer.write_long(self.command_seq)      # reliableAcknowledge

        # Send pending reliable commands
        for i in range(self.reliable_ack + 1, self.reliable_seq + 1):
            inx = i % 64
            writer.write_byte(clc_ops_e.clc_clientCommand.value)
            writer.write_long(i)
            writer.write_string(self.reliable_commands[inx])

        # Send usermove with no delta baseline (clc_moveNoDelta).
        writer.write_byte(clc_ops_e.clc_moveNoDelta.value)
        writer.write_byte(1)  # command count
        cmd = self._next_usercmd()
        key = self._command_key()
        null_cmd = {
            "server_time": 0,
            "angles": [0, 0, 0],
            "forwardmove": 0,
            "rightmove": 0,
            "upmove": 0,
            "buttons": 0,
            "weapon": 0,
        }
        self._write_delta_usercmd(writer, key, null_cmd, cmd)
        self._last_usercmd = cmd

        writer.write_byte(clc_ops_e.clc_EOF.value)

        # Build final packet header
        seq_bytes = struct.pack('<i', self.outgoing_seq)
        qport_bytes = struct.pack('<H', self.qport)

        if self.protocol_version == 71:
            # Protocol 71: add checksum between qport and payload
            checksum = (self.challenge ^ (self.outgoing_seq * self.challenge)) & 0xFFFFFFFF
            checksum_bytes = struct.pack('<I', checksum)
            packet = bytearray(seq_bytes + qport_bytes + checksum_bytes + writer.encoded_data)
        else:
            # Protocol 68: no checksum, but encrypt payload
            packet = bytearray(seq_bytes + qport_bytes + writer.encoded_data)
            cmd = self.server_commands[self.command_seq % 64]
            key = (self.challenge ^ self.message_seq ^ self.server_id) & 0xFF
            self._encrypt_packet(packet, key, cmd + '\x00')

        self.outgoing_seq += 1
        return bytes(packet)

    def _next_usercmd(self):
        """Build the next usercmd from held input state."""
        if self.server_time:
            server_time = self.server_time + 50
        elif self._last_usercmd["server_time"]:
            server_time = self._last_usercmd["server_time"] + 50
        else:
            server_time = int(time.time() * 1000) & 0xFFFFFFFF

        if self._aim_angles and self._aim_frames > 0:
            angles = [self._angle_to_short(a) for a in self._aim_angles]
        else:
            player_state = self.player_state
            if player_state:
                angles = [self._angle_to_short(a) for a in player_state.viewangles]
            else:
                angles = list(self._last_usercmd["angles"])

        forward = self._held_forward if self._held_forward_frames > 0 else 0
        right = self._held_right if self._held_right_frames > 0 else 0
        up = self._held_up if self._held_up_frames > 0 else 0
        buttons = BUTTON_ATTACK if self._held_attack_frames > 0 else 0
        weapon = self._pending_weapon or self._last_usercmd["weapon"]

        self._consume_held_inputs()

        return {
            "server_time": server_time,
            "angles": angles,
            "forwardmove": forward & 0xFF,
            "rightmove": right & 0xFF,
            "upmove": up & 0xFF,
            "buttons": buttons & 0xFFFF,
            "weapon": weapon & 0xFF,
        }

    def _current_viewangles(self):
        if self._aim_angles and self._aim_frames > 0:
            return tuple(self._aim_angles)

        player_state = self.player_state
        if player_state:
            return tuple(float(v) for v in player_state.viewangles)

        return tuple(self._short_to_angle(v) for v in self._last_usercmd["angles"])

    def _consume_held_inputs(self):
        if self._held_forward_frames > 0:
            self._held_forward_frames -= 1
        if self._held_forward_frames == 0:
            self._held_forward = 0

        if self._held_right_frames > 0:
            self._held_right_frames -= 1
        if self._held_right_frames == 0:
            self._held_right = 0

        if self._held_up_frames > 0:
            self._held_up_frames -= 1
        if self._held_up_frames == 0:
            self._held_up = 0

        if self._held_attack_frames > 0:
            self._held_attack_frames -= 1

        if self._aim_frames > 0:
            self._aim_frames -= 1
        if self._aim_frames == 0:
            self._aim_angles = None

        # Weapon switch is one-shot; server keeps current weapon state.
        self._pending_weapon = 0

    def _command_key(self):
        """Compute Q3 delta key for usercmd encoding."""
        key = self.checksum_feed
        key ^= self.message_seq
        key ^= self._hash_key(self.server_commands[self.command_seq % MAX_RELIABLE_COMMANDS], 32)
        return key & 0xFFFFFFFF

    def _write_delta_usercmd(self, writer, key, old, new):
        """Write MSG_WriteDeltaUsercmdKey-compatible payload."""
        time_delta = (new["server_time"] - old["server_time"]) & 0xFFFFFFFF
        if old["server_time"] and time_delta < 256:
            writer.write_bits(1, 1)
            writer.write_bits(time_delta, 8)
        else:
            writer.write_bits(0, 1)
            writer.write_long(new["server_time"])

        changed = (
            old["angles"] != new["angles"] or
            old["forwardmove"] != new["forwardmove"] or
            old["rightmove"] != new["rightmove"] or
            old["upmove"] != new["upmove"] or
            old["buttons"] != new["buttons"] or
            old["weapon"] != new["weapon"]
        )

        writer.write_bits(1 if changed else 0, 1)
        if not changed:
            return

        # ioq3 MSG_WriteDeltaUsercmdKey mixes serverTime into the field key.
        keyed = (key ^ new["server_time"]) & 0xFFFFFFFF

        writer.write_delta_key(keyed, old["angles"][0], new["angles"][0], 16)
        writer.write_delta_key(keyed, old["angles"][1], new["angles"][1], 16)
        writer.write_delta_key(keyed, old["angles"][2], new["angles"][2], 16)
        writer.write_delta_key(keyed, old["forwardmove"], new["forwardmove"], 8)
        writer.write_delta_key(keyed, old["rightmove"], new["rightmove"], 8)
        writer.write_delta_key(keyed, old["upmove"], new["upmove"], 8)
        writer.write_delta_key(keyed, old["buttons"], new["buttons"], 16)
        writer.write_delta_key(keyed, old["weapon"], new["weapon"], 8)

    @staticmethod
    def _hash_key(text, max_len=32):
        if not text:
            return 0
        hash_value = 0
        for i, ch in enumerate(text[:max_len]):
            hash_value += ord(ch) * (119 + i)
        hash_value = hash_value ^ (hash_value >> 10) ^ (hash_value >> 20)
        return hash_value & 0xFFFFFFFF

    @staticmethod
    def _angle_to_short(angle):
        return int((float(angle) * 65536.0 / 360.0)) & 0xFFFF

    @staticmethod
    def _short_to_angle(value):
        return (float(value & 0xFFFF) * 360.0) / 65536.0

    @staticmethod
    def _normalize_pitch(value):
        return max(-89.0, min(89.0, float(value)))

    @staticmethod
    def _normalize_yaw(value):
        return float(value) % 360.0

    @staticmethod
    def _normalize_roll(value):
        value = float(value) % 360.0
        if value > 180.0:
            value -= 360.0
        return value

    @staticmethod
    def _clamp_signed_char(value):
        return max(-127, min(127, int(value)))

    def _encrypt_packet(self, packet, key, last_command):
        """XOR encrypt client packet (protocol 68)."""
        CL_ENCODE_START = 18  # After sequence(4) + qport(2) + serverid(4) + msgack(4) + cmdack(4)
        index = 0
        cmd = last_command.encode('ascii') if isinstance(last_command, str) else last_command

        for i in range(CL_ENCODE_START, len(packet)):
            if index >= len(cmd) or cmd[index] == 0:
                index = 0

            char = cmd[index]
            if char > 127 or char == ord('%'):
                char = ord('.')

            key ^= (char << (i & 1)) & 0xFF
            packet[i] = (packet[i] ^ key) & 0xFF
            index += 1

    # --- State queries ---

    @property
    def is_connected(self):
        return self.state.value >= connstate_t.CA_CONNECTED.value

    @property
    def is_active(self):
        return self.state == connstate_t.CA_ACTIVE

    @property
    def player_state(self):
        if self.current_snapshot:
            return self.current_snapshot.player_state
        return None

    def get_players(self):
        """Get all player entities from the current snapshot."""
        if self.current_snapshot:
            return self.current_snapshot.get_players()
        return {}

    def get_player_name(self, client_num):
        """Get a player's name from config strings."""
        cs_index = configstr_t.CS_PLAYERS + client_num
        cs = self.config_strings.get(cs_index)
        if cs:
            info = self._parse_info_string(cs)
            return info.get('n', f'Player{client_num}')
        return f'Player{client_num}'
