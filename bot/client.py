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
    connstate_t, svc_ops_e, clc_ops_e, configstr_t,
    CONNECTIONLESS_MARKER, FRAGMENT_BIT, MAX_RELIABLE_COMMANDS,
    MAX_CONFIGSTRINGS,
)
from .buffers import Buffer
from .protocol import parse_connectionless, parse_server_frame, ServerFrame
from .snapshot import Snapshot, PlayerState, EntityState

logger = logging.getLogger('clawquake.client')


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

    def __init__(self, server_url, name="ClawBot", protocol=71):
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
        self.snapshots = {}         # message_num -> Snapshot (recent)
        self.current_snapshot = None
        self.server_time = 0

        # WebSocket
        self._ws = None
        self._running = False

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
        if self._ws:
            await self._ws.close()
            self._ws = None

    async def run(self, fps=20):
        """Main game loop. Receives packets and sends client frames at the given FPS."""
        self._running = True
        frame_time = 1.0 / fps

        while self._running:
            try:
                # Receive all pending packets (non-blocking)
                try:
                    data = await asyncio.wait_for(self._ws.recv(), timeout=frame_time)
                    if isinstance(data, bytes):
                        await self._handle_packet(data)
                except asyncio.TimeoutError:
                    pass

                # Send client frame if connected
                if self.state.value >= connstate_t.CA_CONNECTED.value:
                    frame = self._build_client_frame()
                    if frame:
                        await self._ws.send(frame)

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
        return self.queue_command(f'say "{message}"')

    def say_team(self, message):
        """Send a team chat message."""
        return self.queue_command(f'say_team "{message}"')

    # --- Packet handling ---

    async def _handle_packet(self, data):
        """Handle a raw packet from the server."""
        if len(data) < 4:
            return

        sequence = struct.unpack_from('<i', data, 0)[0]

        if sequence == -1:
            # Connectionless packet
            await self._handle_connectionless(data)
        else:
            # Connected packet
            await self._handle_connected(sequence, data)

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

    async def _handle_connected(self, sequence, data):
        """Handle a connected (in-game) packet."""
        if not self.state.value >= connstate_t.CA_CONNECTED.value:
            return

        # Strip fragment bit
        is_fragmented = bool(sequence & FRAGMENT_BIT)
        sequence = sequence & ~FRAGMENT_BIT

        if sequence <= self.message_seq:
            return  # Old/duplicate packet

        if is_fragmented:
            # TODO: implement defragmentation for large packets
            logger.debug("Fragmented packet - skipping")
            return

        # Parse the Huffman-coded payload (skip 4-byte sequence header)
        buf = Buffer(data[4:])

        # For protocol 68, we need to decrypt
        if self.protocol_version == 68:
            reliable_ack_peek = buf.read_long()
            # XOR decrypt
            cmd = self.reliable_commands[reliable_ack_peek % 64]
            key = (self.challenge ^ sequence) & 0xFF
            buf_data = Buffer(data[4:])
            buf_data.xor_data(4, key, cmd + '\x00')  # 4 bytes after reliable_ack (Huffman start)
            buf = buf_data
        else:
            # Protocol 71 - no encryption, already plaintext after checksum
            pass

        # Parse the server frame
        try:
            frame = parse_server_frame(buf, self.baselines, self.snapshots, self.server_commands)
        except Exception as e:
            logger.error(f"Failed to parse server frame: {e}", exc_info=True)
            return

        # Update state
        self.message_seq = sequence
        self.reliable_ack = frame.reliable_ack

        # Handle gamestate (initial connect)
        if frame.config_strings and frame.client_num >= 0:
            self._load_gamestate(frame)

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
            self.snapshots[self.message_seq] = frame.snapshot

            # Keep only recent snapshots
            old_keys = [k for k in self.snapshots if k < self.message_seq - 32]
            for k in old_keys:
                del self.snapshots[k]

            if self.on_snapshot:
                await self.on_snapshot(self, frame.snapshot)

        # Transition to active state
        if self.state == connstate_t.CA_CONNECTED:
            self.state = connstate_t.CA_PRIMED
        if self.state == connstate_t.CA_PRIMED and frame.snapshot:
            self.state = connstate_t.CA_ACTIVE
            logger.info("Game state active - in game!")
            if self.on_connected:
                await self.on_connected(self)

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

    def _process_configstring(self, index, value):
        """Process a config string update."""
        if index == configstr_t.CS_SYSTEMINFO:
            # Parse system info for server_id
            pairs = self._parse_info_string(value)
            if 'sv_serverid' in pairs:
                self.server_id = int(pairs['sv_serverid'])

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
        """Build a client frame packet to send to the server."""
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
            writer.write_byte(clc_ops_e.clc_clientCommand)
            writer.write_long(i)
            writer.write_string(self.reliable_commands[inx])

        # Send usermove (minimal - just keepalive)
        writer.write_byte(clc_ops_e.clc_moveNoDelta)
        writer.write_byte(1)  # command count

        if self.server_time == 0:
            writer.write_raw_bits(1, 1)   # time delta bit
            writer.write_raw_bits(1, 8)   # delta value
        else:
            writer.write_raw_bits(0, 1)   # no time delta
            writer.write_long(self.server_time + 100)

        writer.write_raw_bits(0, 1)  # no movement changes

        writer.write_byte(clc_ops_e.clc_EOF)

        # Build final packet: sequence + qport + huffman payload
        packet = bytearray(
            struct.pack('<i', self.outgoing_seq)
            + struct.pack('<H', self.qport)
            + writer.data
        )

        # For protocol 68, encrypt the payload
        if self.protocol_version == 68:
            cmd = self.server_commands[self.command_seq % 64]
            key = (self.challenge ^ self.message_seq ^ self.server_id) & 0xFF
            self._encrypt_packet(packet, key, cmd + '\x00')

        self.outgoing_seq += 1
        return bytes(packet)

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
