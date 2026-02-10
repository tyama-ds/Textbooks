"""
Base58 and Base58Check encoding used in Bitcoin addresses.

Base58 is a binary-to-text encoding designed by Satoshi Nakamoto.
It uses 58 alphanumeric characters, deliberately omitting:
- 0 (zero), O (uppercase o) - too similar
- I (uppercase i), l (lowercase L) - too similar
- + and / - not alphanumeric

Base58Check adds a 4-byte checksum to detect errors.
"""

from bitcoin.crypto.hash import double_sha256

# Bitcoin's Base58 alphabet
ALPHABET = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
ALPHABET_MAP = {c: i for i, c in enumerate(ALPHABET)}


def base58_encode(data: bytes) -> str:
    """Encode bytes to a Base58 string."""
    # Count leading zero bytes (they become '1' characters)
    leading_zeros = 0
    for byte in data:
        if byte == 0:
            leading_zeros += 1
        else:
            break

    # Convert bytes to a large integer
    n = int.from_bytes(data, "big")

    # Convert to base58
    result = bytearray()
    while n > 0:
        n, remainder = divmod(n, 58)
        result.append(ALPHABET[remainder])

    # Add '1' for each leading zero byte
    result.extend(b"1" * leading_zeros)

    # Reverse (we built it backwards)
    result.reverse()
    return result.decode("ascii")


def base58_decode(s: str) -> bytes:
    """Decode a Base58 string to bytes."""
    # Count leading '1' characters (they represent zero bytes)
    leading_ones = 0
    for c in s:
        if c == "1":
            leading_ones += 1
        else:
            break

    # Convert from base58 to integer
    n = 0
    for c in s.encode("ascii"):
        if c not in ALPHABET_MAP:
            raise ValueError(f"Invalid Base58 character: {chr(c)}")
        n = n * 58 + ALPHABET_MAP[c]

    # Convert integer to bytes
    if n == 0:
        result = b""
    else:
        result = n.to_bytes((n.bit_length() + 7) // 8, "big")

    return b"\x00" * leading_ones + result


def base58check_encode(version: bytes, payload: bytes) -> str:
    """
    Encode data with Base58Check encoding.

    Format: version (1 byte) || payload || checksum (4 bytes)
    The checksum is the first 4 bytes of double_sha256(version || payload).

    Used for Bitcoin addresses:
    - version 0x00: P2PKH address (mainnet)
    - version 0x05: P2SH address (mainnet)
    - version 0x6F: P2PKH address (testnet)
    """
    data = version + payload
    checksum = double_sha256(data)[:4]
    return base58_encode(data + checksum)


def base58check_decode(s: str) -> tuple[bytes, bytes]:
    """
    Decode a Base58Check-encoded string.

    Returns (version, payload).
    Raises ValueError if the checksum is invalid.
    """
    data = base58_decode(s)
    if len(data) < 5:
        raise ValueError("Base58Check data too short")

    payload_with_version = data[:-4]
    checksum = data[-4:]

    expected_checksum = double_sha256(payload_with_version)[:4]
    if checksum != expected_checksum:
        raise ValueError("Invalid Base58Check checksum")

    return payload_with_version[:1], payload_with_version[1:]
