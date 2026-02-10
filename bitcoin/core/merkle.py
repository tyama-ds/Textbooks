"""
Merkle Tree for Bitcoin blocks.

A Merkle tree is a binary hash tree that efficiently summarizes all
transactions in a block into a single 32-byte root hash.

Construction:
1. Hash each transaction (leaf nodes)
2. Pair adjacent hashes and hash them together
3. If odd number of nodes, duplicate the last one
4. Repeat until a single root hash remains

This allows efficient SPV (Simplified Payment Verification) proofs:
a single transaction can be verified with O(log n) hashes.
"""

from bitcoin.crypto.hash import double_sha256


def merkle_root(tx_hashes: list[bytes]) -> bytes:
    """
    Compute the Merkle root from a list of transaction hashes.

    Args:
        tx_hashes: List of 32-byte transaction hashes

    Returns:
        The 32-byte Merkle root hash

    If the list is empty, returns 32 zero bytes.
    If the list has one element, that element is the root.
    """
    if not tx_hashes:
        return b"\x00" * 32

    # Work with a copy
    level = list(tx_hashes)

    while len(level) > 1:
        # If odd number of hashes, duplicate the last one
        if len(level) % 2 == 1:
            level.append(level[-1])

        next_level = []
        for i in range(0, len(level), 2):
            combined = level[i] + level[i + 1]
            next_level.append(double_sha256(combined))
        level = next_level

    return level[0]


def merkle_proof(tx_hashes: list[bytes], index: int) -> list[tuple[bytes, str]]:
    """
    Generate a Merkle proof for a transaction at the given index.

    Returns a list of (hash, side) tuples where side is 'left' or 'right',
    indicating which side the sibling hash should be placed during verification.
    """
    if not tx_hashes or index >= len(tx_hashes):
        return []

    level = list(tx_hashes)
    proof = []
    idx = index

    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])

        # Find sibling
        if idx % 2 == 0:
            sibling_idx = idx + 1
            side = "right"
        else:
            sibling_idx = idx - 1
            side = "left"

        proof.append((level[sibling_idx], side))

        # Move up one level
        next_level = []
        for i in range(0, len(level), 2):
            combined = level[i] + level[i + 1]
            next_level.append(double_sha256(combined))
        level = next_level
        idx = idx // 2

    return proof


def verify_merkle_proof(
    tx_hash: bytes,
    proof: list[tuple[bytes, str]],
    expected_root: bytes,
) -> bool:
    """
    Verify a Merkle proof for a transaction.

    Args:
        tx_hash: The hash of the transaction to verify
        proof: List of (sibling_hash, side) tuples
        expected_root: The expected Merkle root

    Returns:
        True if the proof is valid
    """
    current = tx_hash
    for sibling, side in proof:
        if side == "left":
            current = double_sha256(sibling + current)
        else:
            current = double_sha256(current + sibling)
    return current == expected_root
