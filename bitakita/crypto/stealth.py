"""
Stealth Addresses for BitAkita.

Stealth addresses provide transaction privacy by generating a unique
one-time address for each payment. External observers cannot link
payments to the recipient's public address.

Protocol (Diffie-Hellman based):
1. Recipient publishes a stealth meta-address: (scan_pubkey, spend_pubkey)
2. Sender generates an ephemeral key pair (r, R = r*G)
3. Sender computes shared secret: S = Hash(r * scan_pubkey)
4. Sender derives one-time pubkey: P = spend_pubkey + S*G
5. Sender sends funds to Hash160(P) and publishes R in the transaction
6. Recipient scans: S' = Hash(scan_privkey * R), P' = spend_pubkey + S'*G
7. If P' matches an output, recipient can spend with (spend_privkey + S')
"""

from __future__ import annotations

from dataclasses import dataclass

from ecdsa import SECP256k1, SigningKey, VerifyingKey, SECP256k1 as curve
from ecdsa.ellipticcurve import Point

from bitcoin.crypto.hash import sha256, hash160
from bitcoin.crypto.keys import PrivateKey, PublicKey
from bitakita.utils import base58check_encode, base58check_decode
from bitakita.params import STEALTH_VERSION


@dataclass
class StealthKeyPair:
    """
    A stealth key pair consisting of scan and spend keys.

    The scan key is used to detect incoming payments.
    The spend key is used to actually spend the received funds.
    """

    scan_private: PrivateKey
    scan_public: PublicKey
    spend_private: PrivateKey
    spend_public: PublicKey

    @classmethod
    def generate(cls) -> StealthKeyPair:
        """Generate a new stealth key pair."""
        scan_priv = PrivateKey.generate()
        spend_priv = PrivateKey.generate()
        return cls(
            scan_private=scan_priv,
            scan_public=scan_priv.public_key,
            spend_private=spend_priv,
            spend_public=spend_priv.public_key,
        )


class StealthAddress:
    """
    A stealth meta-address that can generate unlinkable one-time addresses.
    """

    def __init__(self, scan_public: PublicKey, spend_public: PublicKey):
        self.scan_public = scan_public
        self.spend_public = spend_public

    @classmethod
    def from_keypair(cls, keypair: StealthKeyPair) -> StealthAddress:
        return cls(keypair.scan_public, keypair.spend_public)

    def encode(self) -> str:
        """Encode as a Base58Check stealth address string."""
        payload = (
            self.scan_public.compressed_bytes()
            + self.spend_public.compressed_bytes()
        )
        return base58check_encode(STEALTH_VERSION, payload)

    @classmethod
    def decode(cls, address: str) -> StealthAddress:
        """Decode a stealth address string."""
        version, payload = base58check_decode(address)
        if version != STEALTH_VERSION:
            raise ValueError("Not a stealth address")
        if len(payload) != 66:
            raise ValueError("Invalid stealth address length")
        scan_pub = PublicKey.from_bytes(payload[:33])
        spend_pub = PublicKey.from_bytes(payload[33:66])
        return cls(scan_pub, spend_pub)

    def generate_one_time_address(self) -> tuple[bytes, bytes, PrivateKey]:
        """
        Generate a one-time address for a payment (sender side).

        Returns:
            (one_time_pubkey_hash, ephemeral_pubkey_bytes, ephemeral_privkey)

        The sender includes ephemeral_pubkey_bytes in the transaction
        (e.g., in an OP_RETURN output) so the recipient can find it.
        """
        # Generate ephemeral key pair
        ephemeral_priv = PrivateKey.generate()
        ephemeral_pub = ephemeral_priv.public_key

        # Compute shared secret: S = Hash(r * scan_pubkey)
        shared_secret = _ecdh_shared_secret(
            ephemeral_priv, self.scan_public
        )

        # Derive one-time public key: P = spend_pubkey + S*G
        one_time_pub = _derive_one_time_pubkey(
            self.spend_public, shared_secret
        )

        # The address is Hash160(one_time_pub)
        one_time_hash = hash160(one_time_pub)

        return one_time_hash, ephemeral_pub.compressed_bytes(), ephemeral_priv

    @staticmethod
    def recover_one_time_privkey(
        keypair: StealthKeyPair,
        ephemeral_pub_bytes: bytes,
    ) -> tuple[PrivateKey, bytes]:
        """
        Recover the one-time private key for spending (recipient side).

        Args:
            keypair: The recipient's stealth key pair
            ephemeral_pub_bytes: The ephemeral public key from the transaction

        Returns:
            (one_time_privkey, one_time_pubkey_hash)
        """
        ephemeral_pub = PublicKey.from_bytes(ephemeral_pub_bytes)

        # Compute shared secret: S = Hash(scan_privkey * R)
        shared_secret = _ecdh_shared_secret(
            keypair.scan_private, ephemeral_pub
        )

        # Derive one-time private key: p = spend_privkey + S
        one_time_priv = _derive_one_time_privkey(
            keypair.spend_private, shared_secret
        )

        one_time_pub_hash = hash160(
            one_time_priv.public_key.compressed_bytes()
        )

        return one_time_priv, one_time_pub_hash

    @staticmethod
    def scan_for_payments(
        keypair: StealthKeyPair,
        ephemeral_pub_bytes: bytes,
        output_pubkey_hashes: list[bytes],
    ) -> list[int]:
        """
        Scan transaction outputs to find payments to this stealth address.

        Args:
            keypair: The recipient's stealth key pair
            ephemeral_pub_bytes: Ephemeral public key from the tx
            output_pubkey_hashes: List of pubkey hashes from tx outputs

        Returns:
            List of output indices that belong to this stealth address.
        """
        ephemeral_pub = PublicKey.from_bytes(ephemeral_pub_bytes)

        shared_secret = _ecdh_shared_secret(
            keypair.scan_private, ephemeral_pub
        )

        expected_pub = _derive_one_time_pubkey(
            keypair.spend_public, shared_secret
        )
        expected_hash = hash160(expected_pub)

        return [
            i for i, h in enumerate(output_pubkey_hashes)
            if h == expected_hash
        ]


def _ecdh_shared_secret(private_key: PrivateKey, public_key: PublicKey) -> bytes:
    """
    Compute an ECDH shared secret and hash it.

    shared_secret = SHA-256(privkey * pubkey)
    """
    # Get raw scalar and point
    priv_int = int.from_bytes(private_key.to_bytes(), "big")
    pub_vk = public_key._key
    point = pub_vk.pubkey.point

    # Scalar multiplication
    shared_point = point * priv_int

    # Hash the x-coordinate as the shared secret
    x_bytes = shared_point.x().to_bytes(32, "big")
    return sha256(x_bytes)


def _derive_one_time_pubkey(spend_pubkey: PublicKey, shared_secret: bytes) -> bytes:
    """
    Derive a one-time public key: P = spend_pubkey + Hash(S) * G

    Returns the compressed public key bytes.
    """
    # Convert shared secret to a scalar
    secret_int = int.from_bytes(shared_secret, "big") % SECP256k1.order

    # secret_int * G (generator point)
    G = SECP256k1.generator
    secret_point = G * secret_int

    # spend_pubkey point + secret_point
    spend_point = spend_pubkey._key.pubkey.point
    one_time_point = spend_point + secret_point

    # Convert to compressed pubkey bytes
    prefix = b"\x02" if one_time_point.y() % 2 == 0 else b"\x03"
    return prefix + one_time_point.x().to_bytes(32, "big")


def _derive_one_time_privkey(spend_privkey: PrivateKey, shared_secret: bytes) -> PrivateKey:
    """
    Derive the one-time private key: p = spend_privkey + Hash(S) mod n

    The corresponding public key is P = spend_pubkey + Hash(S) * G.
    """
    spend_int = int.from_bytes(spend_privkey.to_bytes(), "big")
    secret_int = int.from_bytes(shared_secret, "big") % SECP256k1.order

    one_time_int = (spend_int + secret_int) % SECP256k1.order

    one_time_bytes = one_time_int.to_bytes(32, "big")
    return PrivateKey.from_bytes(one_time_bytes)
