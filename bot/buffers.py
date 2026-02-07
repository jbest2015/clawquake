"""
Quake 3 bit-level buffer for reading/writing Huffman-encoded network data.

Handles the Q3 wire format: bits are packed LSB-first, byte-aligned portions
are Huffman-coded using the fixed Q3 tree.
"""

import struct
from . import huffman


class Buffer:
    """Bit-level read/write buffer with Huffman encoding for Q3 network protocol."""

    def __init__(self, source=None):
        if source is not None:
            self.data = bytearray(source)
        else:
            self.data = bytearray()
        self.offset = 0  # bit offset

    @property
    def bits_remaining(self):
        return len(self.data) * 8 - self.offset

    # --- Raw bit I/O (no Huffman) ---

    def write_raw_bits(self, value, nbits):
        for i in range(nbits):
            if self.offset % 8 == 0:
                self.data += b'\x00'
            self.data[self.offset // 8] |= ((value >> i) & 1) << (self.offset % 8)
            self.offset += 1

    def read_raw_bits(self, nbits):
        value = 0
        for i in range(nbits):
            value |= ((self.data[self.offset // 8] >> (self.offset % 8)) & 1) << i
            self.offset += 1
        return value

    def write_bit(self, value):
        self.write_raw_bits(value, 1)

    def read_bit(self):
        return self.read_raw_bits(1)

    # --- Huffman-coded I/O ---

    def read_bits(self, nbits):
        """Read nbits from the stream. Byte-aligned portions are Huffman-decoded."""
        if nbits < 0:
            nbits = -nbits
            signed = True
        else:
            signed = False

        uneven_bits = nbits & 7
        value = self.read_raw_bits(uneven_bits)

        for i in range((nbits - uneven_bits) // 8):
            decoded = huffman.fixed_decoder.decode(self, 1)
            value += int.from_bytes(decoded, 'little') * (2 ** (uneven_bits + i * 8))

        if signed and value & (1 << (nbits - 1)):
            value -= 1 << nbits

        return value

    def write_bits(self, value, nbits):
        """Write nbits to the stream. Byte-aligned portions are Huffman-encoded."""
        if nbits < 0:
            nbits = -nbits

        uneven_bits = nbits & 7
        self.write_raw_bits(value, uneven_bits)
        value = value >> uneven_bits

        for _ in range((nbits - uneven_bits) // 8):
            huffman.fixed_decoder.encode(value & 0xff, self)
            value = value >> 8

    # --- High-level types ---

    def read_byte(self):
        return self.read_bits(8)

    def write_byte(self, value):
        self.write_bits(value, 8)

    def read_short(self):
        return self.read_bits(16)

    def read_long(self):
        return self.read_bits(32)

    def write_long(self, value):
        self.write_bits(value, 32)

    def read_string(self):
        """Read a null-terminated string."""
        chars = []
        while True:
            char = self.read_bits(8)
            if char == 0:
                break
            chars.append(char)
        return bytes(chars)

    def write_string(self, string):
        """Write a null-terminated string."""
        if isinstance(string, str):
            string = string.encode('ascii')
        for byte in string:
            self.write_bits(byte, 8)
        self.write_bits(0, 8)  # null terminator

    def read_float(self):
        """Read a 4-byte float via Huffman decoding."""
        raw = huffman.fixed_decoder.decode(self, 4)
        return struct.unpack('<f', raw)[0]

    def read_int_float(self):
        """Read a float stored as integer with bias (Q3 FLOAT_INT encoding)."""
        from .defs import FLOAT_INT_BITS, FLOAT_INT_BIAS
        return self.read_bits(FLOAT_INT_BITS) - FLOAT_INT_BIAS

    def read_delta_key(self, bits, old, key):
        """Read a delta-keyed field: if changed bit is set, read XORed with key."""
        if self.read_bit():
            return self.read_bits(bits) ^ (key & ((2 ** bits) - 1))
        return old

    def write_delta_key(self, value, old, bits, key):
        """Write a delta-keyed field."""
        if old is not None and (value & ((2 ** bits) - 1)) == (old & ((2 ** bits) - 1)):
            self.write_bit(0)
        else:
            self.write_bit(1)
            self.write_bits(value ^ (key & ((2 ** bits) - 1)), bits)

    # --- Packet encryption/decryption ---

    def xor_data(self, start_byte, key, last_command):
        """XOR encrypt/decrypt packet data (Q3 protocol 68 encryption)."""
        index = 0
        cmd = last_command if isinstance(last_command, bytes) else last_command.encode('ascii') + b'\x00'

        for i in range(start_byte, len(self.data)):
            if index >= len(cmd) or cmd[index] == 0:
                index = 0
            if cmd[index] > 127 or cmd[index] == ord('%'):
                key ^= ord('.') << (i & 1)
            else:
                key ^= cmd[index] << (i & 1)
            index += 1
            self.data[i] ^= key & 0xff
