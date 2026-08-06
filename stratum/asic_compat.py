"""ESP-Miner/NerdQaxe++ compatible helpers.

Der Haupt-Stratum in server.py validiert bereits NerdQaxe-kompatibel
(prevhash word-order). Diese Datei bleibt als Referenz / optionale Patches.
"""

from __future__ import annotations

import binascii
import hashlib
import struct
from typing import Optional


def _reverse_endianness_per_word(data: bytes) -> bytes:
    if len(data) % 4:
        raise ValueError("32-bit word transform requires a multiple of 4 bytes")
    return b"".join(data[i : i + 4][::-1] for i in range(0, len(data), 4))


def sha256d(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def build_asic_header(prevhash_be_hex: str, merkle_root: bytes, ntime: int, nonce: int, version: int, nbits_hex: str) -> bytes:
    stratum_prevhash = binascii.unhexlify(prevhash_be_hex)[::-1]
    asic_prevhash = _reverse_endianness_per_word(stratum_prevhash)
    return (
        struct.pack("<I", version & 0xFFFFFFFF)
        + asic_prevhash
        + merkle_root
        + struct.pack("<I", ntime & 0xFFFFFFFF)
        + struct.pack("<I", int(nbits_hex, 16) & 0xFFFFFFFF)
        + struct.pack("<I", nonce & 0xFFFFFFFF)
    )
