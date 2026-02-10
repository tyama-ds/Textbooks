"""
Bitcoin Block and Block Header.

A block consists of:
1. Block Header (80 bytes):
   - Version (4 bytes)
   - Previous block hash (32 bytes)
   - Merkle root (32 bytes)
   - Timestamp (4 bytes)
   - Difficulty target (4 bytes, "bits" compact format)
   - Nonce (4 bytes)
2. Transaction count (varint)
3. Transactions

The block header hash (double SHA-256) must be below the difficulty target
for the block to be valid (Proof of Work).
"""

from __future__ import annotations

import struct
import time
from dataclasses import dataclass, field
from typing import Optional

from bitcoin.crypto.hash import double_sha256
from bitcoin.core.transaction import Transaction
from bitcoin.core.merkle import merkle_root


@dataclass
class BlockHeader:
    """
    The 80-byte block header.

    The block hash is the double-SHA256 of these 80 bytes.
    Miners iterate the nonce to find a hash below the target.
    """

    version: int = 1
    prev_block_hash: bytes = b"\x00" * 32
    merkle_root: bytes = b"\x00" * 32
    timestamp: int = 0
    bits: int = 0x1D00FFFF  # Difficulty target in compact format
    nonce: int = 0

    def serialize(self) -> bytes:
        """Serialize the block header to 80 bytes."""
        return (
            struct.pack("<I", self.version)
            + self.prev_block_hash[::-1]  # Little-endian
            + self.merkle_root[::-1]      # Little-endian
            + struct.pack("<I", self.timestamp)
            + struct.pack("<I", self.bits)
            + struct.pack("<I", self.nonce)
        )

    def hash(self) -> bytes:
        """Compute the block hash (double SHA-256 of the header)."""
        return double_sha256(self.serialize())

    def hash_hex(self) -> str:
        """Return block hash as hex string in display order (reversed)."""
        return self.hash()[::-1].hex()

    @staticmethod
    def target_from_bits(bits: int) -> int:
        """
        Convert compact "bits" format to the full 256-bit target.

        Format: 0xAABBBBBB where:
        - AA is the number of bytes in the target
        - BBBBBB is the coefficient
        - target = coefficient * 2^(8 * (exponent - 3))
        """
        exponent = bits >> 24
        coefficient = bits & 0x007FFFFF
        if exponent <= 3:
            target = coefficient >> (8 * (3 - exponent))
        else:
            target = coefficient << (8 * (exponent - 3))
        return target

    @staticmethod
    def bits_from_target(target: int) -> int:
        """Convert a 256-bit target to compact "bits" format."""
        target_bytes = target.to_bytes(32, "big").lstrip(b"\x00")
        if not target_bytes:
            return 0
        exponent = len(target_bytes)
        if target_bytes[0] >= 0x80:
            # Avoid negative coefficient
            exponent += 1
            coefficient = int.from_bytes(target_bytes[:2], "big")
            coefficient <<= 8
        else:
            coefficient = int.from_bytes(target_bytes[:3], "big") if len(target_bytes) >= 3 else int.from_bytes(target_bytes, "big") << (8 * (3 - len(target_bytes)))
        return (exponent << 24) | (coefficient & 0x007FFFFF)

    def target(self) -> int:
        """Get the full target value for this block's difficulty."""
        return self.target_from_bits(self.bits)

    def meets_target(self) -> bool:
        """Check if this block's hash meets the difficulty target."""
        block_hash = int.from_bytes(self.hash(), "big")
        return block_hash < self.target()


class Block:
    """
    A full Bitcoin block containing a header and transactions.
    """

    def __init__(
        self,
        header: Optional[BlockHeader] = None,
        transactions: Optional[list[Transaction]] = None,
    ):
        self.header = header or BlockHeader()
        self.transactions = transactions or []

    def compute_merkle_root(self) -> bytes:
        """Compute the Merkle root from this block's transactions."""
        tx_hashes = [tx.txid() for tx in self.transactions]
        return merkle_root(tx_hashes)

    def update_merkle_root(self) -> None:
        """Recalculate and set the Merkle root in the header."""
        self.header.merkle_root = self.compute_merkle_root()

    def hash(self) -> bytes:
        return self.header.hash()

    def hash_hex(self) -> str:
        return self.header.hash_hex()

    def validate(self) -> tuple[bool, str]:
        """
        Validate this block.

        Checks:
        1. Block has at least one transaction (coinbase)
        2. First transaction is a coinbase transaction
        3. Merkle root matches transactions
        4. Block hash meets the difficulty target
        """
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

        return True, "Valid"

    @property
    def height(self) -> Optional[int]:
        """Extract block height from coinbase transaction if available."""
        if self.transactions and self.transactions[0].inputs[0].is_coinbase():
            from bitcoin.core.transaction import CoinbaseTransaction
            if isinstance(self.transactions[0], CoinbaseTransaction):
                return self.transactions[0].block_height
        return None

    def __repr__(self) -> str:
        return (
            f"Block(hash={self.hash_hex()[:16]}..., "
            f"txs={len(self.transactions)})"
        )
