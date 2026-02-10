"""
Bitcoin key management using ECDSA on the secp256k1 curve.

Bitcoin uses the secp256k1 elliptic curve for all digital signatures.
- Private key: 256-bit random number
- Public key: Point on the secp256k1 curve (33 bytes compressed, 65 bytes uncompressed)
- Signatures: DER-encoded ECDSA signatures
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass

from ecdsa import SECP256k1, SigningKey, VerifyingKey, BadSignatureError
from ecdsa.util import sigencode_der, sigdecode_der

from .hash import hash160


@dataclass
class Signature:
    """An ECDSA signature."""

    der_bytes: bytes

    def hex(self) -> str:
        return self.der_bytes.hex()

    @classmethod
    def from_hex(cls, hex_str: str) -> Signature:
        return cls(der_bytes=bytes.fromhex(hex_str))

    def __bytes__(self) -> bytes:
        return self.der_bytes


class PublicKey:
    """
    A secp256k1 public key.

    Public keys can be in compressed (33 bytes) or uncompressed (65 bytes) form.
    Compressed is the standard format used in modern Bitcoin.
    """

    def __init__(self, verifying_key: VerifyingKey):
        self._key = verifying_key

    @classmethod
    def from_bytes(cls, data: bytes) -> PublicKey:
        """Parse a public key from compressed or uncompressed bytes."""
        if len(data) == 33:
            vk = VerifyingKey.from_string(data, curve=SECP256k1)
        elif len(data) == 65:
            vk = VerifyingKey.from_string(data[1:], curve=SECP256k1)
        else:
            raise ValueError(f"Invalid public key length: {len(data)}")
        return cls(vk)

    def compressed_bytes(self) -> bytes:
        """Return the 33-byte compressed public key."""
        point = self._key.pubkey.point
        prefix = b"\x02" if point.y() % 2 == 0 else b"\x03"
        return prefix + point.x().to_bytes(32, "big")

    def uncompressed_bytes(self) -> bytes:
        """Return the 65-byte uncompressed public key (04 || x || y)."""
        point = self._key.pubkey.point
        return (
            b"\x04"
            + point.x().to_bytes(32, "big")
            + point.y().to_bytes(32, "big")
        )

    def hash160(self) -> bytes:
        """Compute Hash160 of the compressed public key (for address generation)."""
        return hash160(self.compressed_bytes())

    def verify(self, signature: Signature, message_hash: bytes) -> bool:
        """Verify an ECDSA signature against a 32-byte message hash."""
        try:
            self._key.verify_digest(
                signature.der_bytes, message_hash, sigdecode=sigdecode_der
            )
            return True
        except BadSignatureError:
            return False

    def hex(self) -> str:
        return self.compressed_bytes().hex()

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PublicKey):
            return NotImplemented
        return self.compressed_bytes() == other.compressed_bytes()

    def __hash__(self) -> int:
        return hash(self.compressed_bytes())

    def __bytes__(self) -> bytes:
        return self.compressed_bytes()


class PrivateKey:
    """
    A secp256k1 private key.

    The private key is a 256-bit number used to sign transactions.
    It must be kept secret - anyone with the private key can spend the funds.
    """

    def __init__(self, signing_key: SigningKey):
        self._key = signing_key

    @classmethod
    def generate(cls) -> PrivateKey:
        """Generate a new random private key."""
        sk = SigningKey.generate(curve=SECP256k1)
        return cls(sk)

    @classmethod
    def from_bytes(cls, data: bytes) -> PrivateKey:
        """Create a private key from 32 raw bytes."""
        sk = SigningKey.from_string(data, curve=SECP256k1)
        return cls(sk)

    @classmethod
    def from_hex(cls, hex_str: str) -> PrivateKey:
        """Create a private key from a hex string."""
        return cls.from_bytes(bytes.fromhex(hex_str))

    @property
    def public_key(self) -> PublicKey:
        """Derive the corresponding public key."""
        return PublicKey(self._key.get_verifying_key())

    def sign(self, message_hash: bytes) -> Signature:
        """
        Sign a 32-byte message hash using ECDSA.

        Returns a DER-encoded signature.
        """
        sig_bytes = self._key.sign_digest(
            message_hash, sigencode=sigencode_der
        )
        return Signature(der_bytes=sig_bytes)

    def to_bytes(self) -> bytes:
        """Return the raw 32-byte private key."""
        return self._key.to_string()

    def hex(self) -> str:
        return self.to_bytes().hex()
