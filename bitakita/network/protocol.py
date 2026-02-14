"""
BitAkita Wire Protocol.

Defines the binary message format for P2P communication over TCP.

Message format:
    [magic: 4 bytes][command: 12 bytes][payload_len: 4 bytes][checksum: 4 bytes][payload]

Commands:
    version    - Handshake: announce node info
    verack     - Handshake acknowledgement
    getblocks  - Request block hashes after a given hash
    inv        - Announce available blocks/txs
    getdata    - Request specific blocks/txs
    block      - A full block
    tx         - A transaction
    ping       - Keepalive
    pong       - Keepalive reply
    addr       - Share known peer addresses
"""

from __future__ import annotations

import struct
import json
import time
from enum import Enum
from dataclasses import dataclass, field
from typing import Any

from bitcoin.crypto.hash import double_sha256


# Magic bytes identify the BitAkita network (prevents cross-network messages)
MAGIC = b"\xb1\x7a\x01\x7a"  # "BITA" in leet-speak


class Command(str, Enum):
    VERSION = "version"
    VERACK = "verack"
    GETBLOCKS = "getblocks"
    INV = "inv"
    GETDATA = "getdata"
    BLOCK = "block"
    TX = "tx"
    PING = "ping"
    PONG = "pong"
    ADDR = "addr"


@dataclass
class Message:
    """A wire protocol message."""

    command: Command
    payload: dict = field(default_factory=dict)

    def serialize(self) -> bytes:
        """Serialize to wire format."""
        payload_bytes = json.dumps(self.payload).encode("utf-8")
        command_bytes = self.command.value.encode("ascii").ljust(12, b"\x00")
        payload_len = struct.pack("<I", len(payload_bytes))
        checksum = double_sha256(payload_bytes)[:4]
        return MAGIC + command_bytes + payload_len + checksum + payload_bytes

    @classmethod
    def deserialize(cls, data: bytes) -> tuple[Message, int]:
        """
        Deserialize from wire format.

        Returns (message, total_bytes_consumed).
        Raises ValueError if data is incomplete or invalid.
        """
        HEADER_SIZE = 24  # 4 + 12 + 4 + 4

        if len(data) < HEADER_SIZE:
            raise ValueError("Incomplete header")

        magic = data[:4]
        if magic != MAGIC:
            raise ValueError(f"Bad magic: {magic.hex()}")

        command_raw = data[4:16].rstrip(b"\x00").decode("ascii")
        try:
            command = Command(command_raw)
        except ValueError:
            raise ValueError(f"Unknown command: {command_raw}")

        payload_len = struct.unpack("<I", data[16:20])[0]
        checksum = data[20:24]

        total_size = HEADER_SIZE + payload_len
        if len(data) < total_size:
            raise ValueError("Incomplete payload")

        payload_bytes = data[24 : 24 + payload_len]

        expected_checksum = double_sha256(payload_bytes)[:4]
        if checksum != expected_checksum:
            raise ValueError("Checksum mismatch")

        payload = json.loads(payload_bytes.decode("utf-8")) if payload_bytes else {}
        return cls(command=command, payload=payload), total_size


# --- Message Constructors ---

def msg_version(height: int, listen_port: int, node_id: str) -> Message:
    return Message(Command.VERSION, {
        "version": 1,
        "height": height,
        "timestamp": int(time.time()),
        "listen_port": listen_port,
        "node_id": node_id,
    })


def msg_verack() -> Message:
    return Message(Command.VERACK)


def msg_ping(nonce: int) -> Message:
    return Message(Command.PING, {"nonce": nonce})


def msg_pong(nonce: int) -> Message:
    return Message(Command.PONG, {"nonce": nonce})


def msg_getblocks(start_height: int) -> Message:
    return Message(Command.GETBLOCKS, {"start_height": start_height})


def msg_inv(inv_type: str, hashes: list[str]) -> Message:
    return Message(Command.INV, {"type": inv_type, "hashes": hashes})


def msg_getdata(inv_type: str, hashes: list[str]) -> Message:
    return Message(Command.GETDATA, {"type": inv_type, "hashes": hashes})


def msg_block(block_data: dict) -> Message:
    return Message(Command.BLOCK, block_data)


def msg_tx(tx_data: dict) -> Message:
    return Message(Command.TX, tx_data)


def msg_addr(addresses: list[tuple[str, int]]) -> Message:
    return Message(Command.ADDR, {
        "addresses": [{"host": h, "port": p} for h, p in addresses],
    })
