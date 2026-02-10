"""
Proof of Stake (PoS) system for BitAkita.

Validators lock (stake) their BITA to participate in consensus.
Staking provides:
- Checkpoint voting rights (weighted by stake)
- Annual stake rewards
- Governance voting power

Misbehavior (e.g., signing conflicting checkpoints) results in slashing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from bitcoin.crypto.keys import PrivateKey, PublicKey, Signature
from bitcoin.crypto.hash import double_sha256
from bitakita import params


@dataclass
class Validator:
    """A PoS validator who has staked BITA."""

    pubkey: PublicKey
    pubkey_hash: bytes
    stake_amount: int        # Amount staked in inu
    stake_height: int        # Block height when staked
    is_active: bool = True
    accumulated_rewards: int = 0
    slashed: bool = False

    @property
    def can_unstake(self) -> bool:
        """Placeholder: actual check requires current height."""
        return self.is_active and not self.slashed

    def voting_power(self, total_stake: int) -> float:
        """This validator's share of total stake (0.0 to 1.0)."""
        if total_stake == 0:
            return 0.0
        return self.stake_amount / total_stake


class StakePool:
    """
    Manages the set of active validators and their stakes.
    """

    def __init__(self):
        self.validators: dict[bytes, Validator] = {}  # pubkey_hash -> Validator
        self._total_stake: int = 0

    @property
    def total_stake(self) -> int:
        return self._total_stake

    @property
    def active_validators(self) -> list[Validator]:
        return [v for v in self.validators.values() if v.is_active and not v.slashed]

    def add_validator(
        self,
        pubkey: PublicKey,
        stake_amount: int,
        block_height: int,
    ) -> tuple[bool, str]:
        """
        Register a new validator by staking BITA.

        The stake is locked for STAKE_LOCK_PERIOD blocks.
        """
        pubkey_hash = pubkey.hash160()

        if pubkey_hash in self.validators:
            # Allow adding more stake to existing validator
            existing = self.validators[pubkey_hash]
            if existing.slashed:
                return False, "Validator was slashed and cannot re-stake"
            existing.stake_amount += stake_amount
            self._total_stake += stake_amount
            return True, f"Added {stake_amount} inu to existing stake"

        if stake_amount < params.MIN_STAKE_AMOUNT:
            return False, (
                f"Minimum stake is {params.MIN_STAKE_AMOUNT} inu "
                f"({params.MIN_STAKE_AMOUNT / 1_0000_0000:.0f} BITA)"
            )

        validator = Validator(
            pubkey=pubkey,
            pubkey_hash=pubkey_hash,
            stake_amount=stake_amount,
            stake_height=block_height,
        )
        self.validators[pubkey_hash] = validator
        self._total_stake += stake_amount
        return True, "Validator registered"

    def remove_validator(
        self, pubkey_hash: bytes, current_height: int
    ) -> tuple[bool, str, int]:
        """
        Remove a validator and return their stake.

        Returns (success, message, amount_returned).
        """
        if pubkey_hash not in self.validators:
            return False, "Validator not found", 0

        validator = self.validators[pubkey_hash]

        if not validator.is_active:
            return False, "Validator already inactive", 0

        if validator.slashed:
            return False, "Validator was slashed", 0

        lock_expiry = validator.stake_height + params.STAKE_LOCK_PERIOD
        if current_height < lock_expiry:
            return False, f"Stake locked until block {lock_expiry}", 0

        amount = validator.stake_amount + validator.accumulated_rewards
        validator.is_active = False
        self._total_stake -= validator.stake_amount
        return True, "Validator removed", amount

    def slash_validator(self, pubkey_hash: bytes) -> tuple[bool, int]:
        """
        Slash a misbehaving validator.

        Removes SLASH_PERCENTAGE of their stake.
        Returns (success, amount_slashed).
        """
        if pubkey_hash not in self.validators:
            return False, 0

        validator = self.validators[pubkey_hash]
        if validator.slashed:
            return False, 0

        slash_amount = validator.stake_amount * params.SLASH_PERCENTAGE // 100
        validator.stake_amount -= slash_amount
        self._total_stake -= slash_amount
        validator.slashed = True
        validator.is_active = False
        return True, slash_amount

    def distribute_rewards(self, current_height: int) -> dict[bytes, int]:
        """
        Calculate per-block stake rewards for all active validators.

        Rewards are proportional to stake amount.
        Annual rate: ANNUAL_STAKE_REWARD_RATE % of stake.
        Distributed every block.

        Returns dict of pubkey_hash -> reward_amount.
        """
        # Approximate: blocks per year at 60s block time
        blocks_per_year = 365 * 24 * 60  # 525,600
        rewards = {}

        for v in self.active_validators:
            # Per-block reward = stake * annual_rate / blocks_per_year
            reward = (
                v.stake_amount
                * params.ANNUAL_STAKE_REWARD_RATE
                // (100 * blocks_per_year)
            )
            if reward > 0:
                v.accumulated_rewards += reward
                rewards[v.pubkey_hash] = reward

        return rewards
