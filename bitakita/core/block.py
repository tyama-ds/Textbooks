"""
BitAkita Block with dynamic block size.

Differences from Bitcoin:
- Dynamic block size: adjusts based on network demand
- Block header includes base_fee for EIP-1559
- 60-second target block time
"""

from __future__ import annotations

import struct
import time
from dataclasses import dataclass
from typing import Optional

from bitcoin.crypto.hash import double_sha256
from bitcoin.core.merkle import merkle_root
from bitakita.core.transaction import Transaction
from bitakita import params


@dataclass
class BlockHeader:
    """
    BitAkita block header.

    Extends Bitcoin's 80-byte header with:
    - base_fee: Current EIP-1559 base fee (4 bytes)
    - block_size_limit: Dynamic size limit for this block (4 bytes)
    Total: 88 bytes
    """

    version: int = 2
    prev_block_hash: bytes = b"\x00" * 32
    merkle_root: bytes = b"\x00" * 32
    timestamp: int = 0
    bits: int = params.DEFAULT_INITIAL_BITS
    nonce: int = 0
    base_fee: int = params.INITIAL_BASE_FEE
    block_size_limit: int = params.TARGET_BLOCK_SIZE

    def serialize(self) -> bytes:
        return (
            struct.pack("<I", self.version)
            + self.prev_block_hash[::-1]
            + self.merkle_root[::-1]
            + struct.pack("<I", self.timestamp)
            + struct.pack("<I", self.bits)
            + struct.pack("<I", self.nonce)
            + struct.pack("<I", self.base_fee)
            + struct.pack("<I", self.block_size_limit)
        )

    def hash(self) -> bytes:
        return double_sha256(self.serialize())

    def hash_hex(self) -> str:
        return self.hash()[::-1].hex()

    @staticmethod
    def target_from_bits(bits: int) -> int:
        exponent = bits >> 24
        coefficient = bits & 0x007FFFFF
        if exponent <= 3:
            target = coefficient >> (8 * (3 - exponent))
        else:
            target = coefficient << (8 * (exponent - 3))
        return target

    @staticmethod
    def bits_from_target(target: int) -> int:
        target_bytes = target.to_bytes(32, "big").lstrip(b"\x00")
        if not target_bytes:
            return 0
        exponent = len(target_bytes)
        if target_bytes[0] >= 0x80:
            exponent += 1
            coefficient = int.from_bytes(target_bytes[:2], "big") << 8
        else:
            coefficient = (
                int.from_bytes(target_bytes[:3], "big")
                if len(target_bytes) >= 3
                else int.from_bytes(target_bytes, "big") << (8 * (3 - len(target_bytes)))
            )
        return (exponent << 24) | (coefficient & 0x007FFFFF)

    def target(self) -> int:
        return self.target_from_bits(self.bits)

    def meets_target(self) -> bool:
        block_hash = int.from_bytes(self.hash(), "big")
        return block_hash < self.target()


class Block:
    """A BitAkita block with dynamic sizing."""

    def __init__(
        self,
        header: Optional[BlockHeader] = None,
        transactions: Optional[list[Transaction]] = None,
    ):
        self.header = header or BlockHeader()
        self.transactions = transactions or []

    def compute_merkle_root(self) -> bytes:
        tx_hashes = [tx.txid() for tx in self.transactions]
        return merkle_root(tx_hashes)

    def update_merkle_root(self) -> None:
        self.header.merkle_root = self.compute_merkle_root()

    def block_size(self) -> int:
        """Total block size in bytes."""
        size = 88  # header
        for tx in self.transactions:
            size += tx.size()
        return size

    def hash(self) -> bytes:
        return self.header.hash()

    def hash_hex(self) -> str:
        return self.header.hash_hex()

    def validate(self) -> tuple[bool, str]:
        if not self.transactions:
            return False, "Block has no transactions"

        if not self.transactions[0].inputs[0].is_coinbase():
            return False, "First transaction is not a coinbase"

        for i in range(1, len(self.transactions)):
            if self.transactions[i].inputs and self.transactions[i].inputs[0].is_coinbase():
                return False, f"Non-first transaction {i} is a coinbase"

        expected_merkle = self.compute_merkle_root()
        if self.header.merkle_root != expected_merkle:
            return False, "Merkle root mismatch"

        if not self.header.meets_target():
            return False, "Block hash does not meet difficulty target"

        # Dynamic block size check
        if self.block_size() > self.header.block_size_limit:
            return False, "Block exceeds size limit"

        return True, "Valid"

    @staticmethod
    def calculate_dynamic_size_limit(
        recent_sizes: list[int],
        current_limit: int,
    ) -> int:
        """
        Calculate the next block's size limit based on recent utilization.

        If blocks are consistently full: increase limit (up to MAX)
        If blocks are consistently empty: decrease limit (down to MIN)
        """
        if not recent_sizes:
            return current_limit

        avg_size = sum(recent_sizes) // len(recent_sizes)
        target = params.TARGET_BLOCK_SIZE

        if avg_size > target:
            # Increase limit
            delta = (avg_size - target) * current_limit // (target * params.BLOCK_SIZE_ADJUSTMENT_FACTOR)
            new_limit = current_limit + max(1, delta)
        elif avg_size < target // 2:
            # Decrease limit
            delta = (target - avg_size) * current_limit // (target * params.BLOCK_SIZE_ADJUSTMENT_FACTOR)
            new_limit = current_limit - max(1, delta)
        else:
            new_limit = current_limit

        return max(params.MIN_BLOCK_SIZE, min(new_limit, params.MAX_BLOCK_SIZE))

    def __repr__(self) -> str:
        return (
            f"Block(hash={self.hash_hex()[:16]}..., "
            f"txs={len(self.transactions)}, "
            f"size={self.block_size()})"
        )
