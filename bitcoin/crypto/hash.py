"""
Bitcoin hashing functions.

Bitcoin uses several hash functions:
- SHA-256: The primary hash function
- Double SHA-256 (SHA-256d): Used for block hashes, transaction IDs, etc.
- RIPEMD-160: Used in combination with SHA-256 for address generation (Hash160)
"""

import hashlib


def sha256(data: bytes) -> bytes:
    """Compute SHA-256 hash."""
    return hashlib.sha256(data).digest()


def double_sha256(data: bytes) -> bytes:
    """
    Compute SHA-256(SHA-256(data)).

    Bitcoin uses double SHA-256 extensively for:
    - Block header hashing (proof of work)
    - Transaction ID computation
    - Merkle tree construction
    """
    return sha256(sha256(data))


def ripemd160(data: bytes) -> bytes:
    """Compute RIPEMD-160 hash."""
    h = hashlib.new("ripemd160")
    h.update(data)
    return h.digest()


def hash160(data: bytes) -> bytes:
    """
    Compute RIPEMD-160(SHA-256(data)).

    Used to create the 20-byte hash that forms the core of a Bitcoin address.
    Public key -> SHA-256 -> RIPEMD-160 -> 20-byte address hash
    """
    return ripemd160(sha256(data))
