"""
PoS Checkpoint Finality for BitAkita.

Checkpoints provide deterministic finality: once a checkpoint is confirmed,
the blocks it covers cannot be reorganized.

Process:
1. Every CHECKPOINT_INTERVAL blocks, a checkpoint round begins
2. Active validators sign the checkpoint (block hash at that height)
3. When signatures representing >= CHECKPOINT_QUORUM % of total stake
   are collected, the checkpoint is finalized
4. Finalized blocks cannot be reversed

This addresses Bitcoin's probabilistic finality problem where
even 6 confirmations only provide ~99.9% security.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from bitcoin.crypto.keys import PublicKey, PrivateKey, Signature
from bitcoin.crypto.hash import double_sha256
from bitakita import params
from .pos import StakePool, Validator


@dataclass
class CheckpointVote:
    """A validator's vote for a checkpoint."""

    validator_pubkey_hash: bytes
    block_height: int
    block_hash: bytes
    signature: Signature


@dataclass
class Checkpoint:
    """
    A finalized checkpoint in the chain.

    Once finalized, all blocks up to and including this height
    are considered irreversible.
    """

    block_height: int
    block_hash: bytes
    votes: list[CheckpointVote] = field(default_factory=list)
    total_voting_stake: int = 0
    required_stake: int = 0
    is_finalized: bool = False

    @property
    def stake_percentage(self) -> float:
        if self.required_stake == 0:
            return 0.0
        return (self.total_voting_stake / self.required_stake) * 100


class CheckpointManager:
    """
    Manages checkpoint creation, voting, and finalization.
    """

    def __init__(self, stake_pool: StakePool):
        self.stake_pool = stake_pool
        self.checkpoints: dict[int, Checkpoint] = {}  # height -> Checkpoint
        self.finalized_height: int = -1
        self._pending_votes: dict[int, list[CheckpointVote]] = {}

    def should_checkpoint(self, block_height: int) -> bool:
        """Check if a checkpoint should be created at this height."""
        return (
            block_height > 0
            and block_height % params.CHECKPOINT_INTERVAL == 0
        )

    def create_checkpoint(self, block_height: int, block_hash: bytes) -> Checkpoint:
        """Create a new checkpoint for voting."""
        total_stake = self.stake_pool.total_stake
        required_stake = total_stake * params.CHECKPOINT_QUORUM // 100

        cp = Checkpoint(
            block_height=block_height,
            block_hash=block_hash,
            required_stake=required_stake,
        )
        self.checkpoints[block_height] = cp
        self._pending_votes[block_height] = []
        return cp

    def cast_vote(
        self,
        block_height: int,
        block_hash: bytes,
        validator_privkey: PrivateKey,
    ) -> tuple[bool, str]:
        """
        Cast a checkpoint vote from a validator.

        The vote is a signature over (height || block_hash).
        """
        pubkey = validator_privkey.public_key
        pubkey_hash = pubkey.hash160()

        # Verify validator is active
        if pubkey_hash not in self.stake_pool.validators:
            return False, "Not a registered validator"

        validator = self.stake_pool.validators[pubkey_hash]
        if not validator.is_active or validator.slashed:
            return False, "Validator is not active"

        # Check checkpoint exists
        if block_height not in self.checkpoints:
            return False, "No checkpoint at this height"

        cp = self.checkpoints[block_height]

        if cp.is_finalized:
            return False, "Checkpoint already finalized"

        if cp.block_hash != block_hash:
            return False, "Block hash mismatch"

        # Check for duplicate votes
        for vote in cp.votes:
            if vote.validator_pubkey_hash == pubkey_hash:
                return False, "Already voted"

        # Sign the checkpoint
        message = block_height.to_bytes(8, "big") + block_hash
        sig = validator_privkey.sign(double_sha256(message))

        vote = CheckpointVote(
            validator_pubkey_hash=pubkey_hash,
            block_height=block_height,
            block_hash=block_hash,
            signature=sig,
        )

        cp.votes.append(vote)
        cp.total_voting_stake += validator.stake_amount

        # Check if quorum reached
        if cp.total_voting_stake >= cp.required_stake:
            cp.is_finalized = True
            self.finalized_height = max(self.finalized_height, block_height)
            return True, f"Checkpoint finalized at height {block_height}"

        return True, (
            f"Vote recorded ({cp.stake_percentage:.1f}% of required stake)"
        )

    def is_finalized(self, block_height: int) -> bool:
        """Check if a specific block height has been finalized."""
        return block_height <= self.finalized_height

    def detect_equivocation(
        self,
        block_height: int,
        validator_pubkey_hash: bytes,
        conflicting_hash: bytes,
    ) -> bool:
        """
        Detect if a validator has signed conflicting checkpoints (equivocation).

        This is a slashable offense.
        """
        if block_height not in self.checkpoints:
            return False

        cp = self.checkpoints[block_height]
        for vote in cp.votes:
            if vote.validator_pubkey_hash == validator_pubkey_hash:
                if vote.block_hash != conflicting_hash:
                    return True  # Equivocation detected
        return False
