"""
Quake 3 bit-level buffer for reading/writing Huffman-encoded network data.

Uses the q3huff2 C library for correct Huffman encoding/decoding that matches
what QuakeJS (ioquake3) uses. The pure Python Huffman tree (SAVED_TREE from
quake3-proxy-aimbot) does NOT produce compatible output.
"""

import struct
import logging
import q3huff2

logger = logging.getLogger('clawquake.buffers')


class BufferOverflow(Exception):
    """Raised when trying to read past the end of a buffer."""
    pass


class Buffer:
    """Bit-level read/write buffer with Huffman encoding for Q3 network protocol.

    For reading: wraps q3huff2.Reader which handles Huffman decoding natively.
    For writing: wraps q3huff2.Writer which handles Huffman encoding natively.
    """

    def __init__(self, source=None):
        if source is not None:
            self._reader = q3huff2.Reader(bytes(source))
            self._writer = None
            self.data = bytearray(source)
            self._data_len = len(source)
            self._bytes_read = 0
        else:
            self._reader = None
            self._writer = q3huff2.Writer()
            self.data = bytearray()
            self._data_len = 0
            self._bytes_read = 0

    @property
    def bits_remaining(self):
        """Estimate of remaining bits. Huffman coding makes exact tracking
        impossible (variable-length codes), but we track approximate bytes
        consumed to detect when we're clearly past the end."""
        if self._reader:
            # Each Huffman byte read consumes variable bits, but on average
            # about 5-8 bits per byte. We track bytes decoded as an approximation.
            remaining = (self._data_len - self._bytes_read) * 8
            return max(remaining, 0)
        return 0

    def _track_read(self, nbytes=1):
        """Track approximate bytes consumed for overflow detection."""
        self._bytes_read += nbytes

    # --- Reading (delegates to q3huff2.Reader with safety) ---

    def read_bit(self):
        self._track_read(0)  # sub-byte, minimal tracking
        try:
            return self._reader.read_bits(1)
        except Exception as e:
            raise BufferOverflow(f"read_bit failed: {e}")

    def read_raw_bits(self, nbits):
        self._track_read(max(1, nbits // 8))
        try:
            return self._reader.read_bits(nbits)
        except Exception as e:
            raise BufferOverflow(f"read_raw_bits({nbits}) failed: {e}")

    def read_bits(self, nbits):
        """Read nbits from the stream with Huffman decoding."""
        self._track_read(max(1, nbits // 8))
        try:
            return self._reader.read_bits(nbits)
        except Exception as e:
            raise BufferOverflow(f"read_bits({nbits}) failed: {e}")

    def read_byte(self):
        self._track_read(1)
        try:
            return self._reader.read_byte()
        except Exception as e:
            raise BufferOverflow(f"read_byte failed: {e}")

    def read_short(self):
        self._track_read(2)
        try:
            return self._reader.read_short()
        except Exception as e:
            raise BufferOverflow(f"read_short failed: {e}")

    def read_long(self):
        self._track_read(4)
        try:
            return self._reader.read_long()
        except Exception as e:
            raise BufferOverflow(f"read_long failed: {e}")

    def read_string(self):
        """Read a null-terminated Huffman-decoded string. Returns bytes."""
        try:
            text = self._reader.read_string()
            if isinstance(text, str):
                result = text.encode('ascii', errors='replace')
            else:
                result = text
            self._track_read(len(result) + 1)  # +1 for null terminator
            return result
        except Exception as e:
            raise BufferOverflow(f"read_string failed: {e}")

    def read_float(self):
        """Read a 4-byte IEEE float via Huffman decoding."""
        self._track_read(4)
        try:
            return self._reader.read_float()
        except Exception as e:
            raise BufferOverflow(f"read_float failed: {e}")

    def read_int_float(self):
        """Read a float stored as integer with bias (Q3 FLOAT_INT encoding)."""
        from .defs import FLOAT_INT_BITS, FLOAT_INT_BIAS
        self._track_read(2)
        try:
            return self._reader.read_bits(FLOAT_INT_BITS) - FLOAT_INT_BIAS
        except Exception as e:
            raise BufferOverflow(f"read_int_float failed: {e}")

    def read_delta_key(self, bits, old, key):
        """Read a delta-keyed field: if changed bit is set, read XORed with key."""
        self._track_read(max(1, bits // 8))
        try:
            return self._reader.read_delta_key(key, old, bits)
        except Exception as e:
            raise BufferOverflow(f"read_delta_key failed: {e}")

    # --- Writing (delegates to q3huff2.Writer) ---

    def write_raw_bits(self, value, nbits):
        self._writer.write_bits(value, nbits)

    def write_bit(self, value):
        self._writer.write_bits(value, 1)

    def write_bits(self, value, nbits):
        self._writer.write_bits(value, nbits)

    def write_byte(self, value):
        self._writer.write_byte(value)

    def write_long(self, value):
        self._writer.write_long(value)

    def write_string(self, string):
        if isinstance(string, bytes):
            string = string.decode('ascii', errors='replace')
        self._writer.write_string(string)

    @property
    def encoded_data(self):
        """Get the Huffman-encoded data from the writer."""
        if self._writer:
            return self._writer.data
        return bytes(self.data)
