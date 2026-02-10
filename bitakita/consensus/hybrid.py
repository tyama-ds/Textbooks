"""
Hybrid PoW/PoS Consensus for BitAkita.

Combines Proof of Work and Proof of Stake:
- PoW provides Sybil resistance and fair coin distribution
- PoS provides energy efficiency, fast finality, and governance

Block production flow:
1. Miners compete via PoW to create blocks (like Bitcoin)
2. Every CHECKPOINT_INTERVAL blocks, PoS validators vote on finality
3. Once a checkpoint is finalized, those blocks cannot be reorganized
4. Validators earn staking rewards proportional to their stake
5. Misbehaving validators (equivocation) get slashed

This hybrid approach means:
- An attacker needs both >50% hash power AND >33% of stake
- Energy consumption is lower (difficulty can be reduced with PoS security)
- Finality is faster (checkpoints every ~10 minutes vs ~60 minutes)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from bitcoin.crypto.keys import PrivateKey, PublicKey
from bitakita import params
from .pos import StakePool, Validator
from .checkpoint import CheckpointManager, Checkpoint


class HybridConsensus:
    """
    Manages the combined PoW/PoS consensus mechanism.
    """

    def __init__(self):
        self.stake_pool = StakePool()
        self.checkpoint_mgr = CheckpointManager(self.stake_pool)

    def register_validator(
        self,
        pubkey: PublicKey,
        stake_amount: int,
        block_height: int,
    ) -> tuple[bool, str]:
        """Register a new PoS validator."""
        return self.stake_pool.add_validator(pubkey, stake_amount, block_height)

    def unregister_validator(
        self, pubkey_hash: bytes, current_height: int
    ) -> tuple[bool, str, int]:
        """Unregister a validator and return their stake."""
        return self.stake_pool.remove_validator(pubkey_hash, current_height)

    def on_new_block(self, block_height: int, block_hash: bytes) -> Optional[Checkpoint]:
        """
        Called when a new PoW block is added.

        Checks if a checkpoint should be created.
        Returns the new Checkpoint if one was created, else None.
        """
        # Distribute staking rewards
        self.stake_pool.distribute_rewards(block_height)

        # Create checkpoint if needed
        if self.checkpoint_mgr.should_checkpoint(block_height):
            return self.checkpoint_mgr.create_checkpoint(block_height, block_hash)
        return None

    def vote_checkpoint(
        self,
        block_height: int,
        block_hash: bytes,
        validator_privkey: PrivateKey,
    ) -> tuple[bool, str]:
        """Submit a validator's checkpoint vote."""
        return self.checkpoint_mgr.cast_vote(
            block_height, block_hash, validator_privkey
        )

    def is_finalized(self, block_height: int) -> bool:
        """Check if a block height is finalized."""
        return self.checkpoint_mgr.is_finalized(block_height)

    def slash_for_equivocation(
        self,
        block_height: int,
        validator_pubkey_hash: bytes,
        conflicting_hash: bytes,
    ) -> tuple[bool, int]:
        """
        Slash a validator for equivocation (signing conflicting checkpoints).

        Returns (was_slashed, amount_slashed).
        """
        if self.checkpoint_mgr.detect_equivocation(
            block_height, validator_pubkey_hash, conflicting_hash
        ):
            return self.stake_pool.slash_validator(validator_pubkey_hash)
        return False, 0

    @property
    def total_stake(self) -> int:
        return self.stake_pool.total_stake

    @property
    def validator_count(self) -> int:
        return len(self.stake_pool.active_validators)

    @property
    def finalized_height(self) -> int:
        return self.checkpoint_mgr.finalized_height
