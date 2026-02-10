"""
EIP-1559 Style Fee Mechanism for BitAkita.

Bitcoin's fee model is a simple first-price auction: users bid for block space,
and miners include the highest-fee transactions. This leads to:
- Unpredictable fees during congestion
- Overpayment by users who don't know the "right" fee
- All fees go to miners, creating no deflationary pressure

BitAkita's fee model (inspired by Ethereum's EIP-1559):
1. Each block has a BASE_FEE determined algorithmically
2. Base fee adjusts up/down based on block utilization vs target
3. A portion (FEE_BURN_PERCENTAGE) of the base fee is burned (destroyed)
4. Users can add a PRIORITY_FEE (tip) to incentivize miners
5. Miners receive: priority_fee + (1 - burn%) of base_fee

Benefits:
- More predictable fees
- Deflationary pressure from burning
- Better UX (users just need to set a max fee)
"""

from __future__ import annotations

from dataclasses import dataclass
from bitakita import params


@dataclass
class FeeBreakdown:
    """Breakdown of fees for a transaction."""
    base_fee: int          # Per-byte base fee (in inu)
    priority_fee: int      # User-set tip for the miner (in inu)
    total_fee: int         # Total fee paid
    burned_amount: int     # Amount burned (removed from supply)
    miner_reward: int      # Amount going to the miner


class FeeManager:
    """
    Manages the EIP-1559-style base fee mechanism.
    """

    def __init__(self, initial_base_fee: int = params.INITIAL_BASE_FEE):
        self.base_fee = initial_base_fee
        self.total_burned: int = 0
        self._history: list[int] = [initial_base_fee]

    def calculate_next_base_fee(self, block_size: int, target_size: int) -> int:
        """
        Calculate the base fee for the next block.

        If the block is larger than target: base fee increases
        If the block is smaller than target: base fee decreases
        Max change: 1/BASE_FEE_MAX_CHANGE_DENOMINATOR per block (12.5%)
        """
        if target_size == 0:
            return self.base_fee

        if block_size == target_size:
            return self.base_fee

        max_change = max(
            1, self.base_fee // params.BASE_FEE_MAX_CHANGE_DENOMINATOR
        )

        if block_size > target_size:
            # Block too full -> increase base fee
            delta = max_change * (block_size - target_size) // target_size
            new_fee = self.base_fee + max(1, delta)
        else:
            # Block too empty -> decrease base fee
            delta = max_change * (target_size - block_size) // target_size
            new_fee = self.base_fee - min(delta, max_change)

        # Enforce minimum
        new_fee = max(new_fee, params.MIN_BASE_FEE)

        return new_fee

    def update_base_fee(self, block_size: int, target_size: int = params.TARGET_BLOCK_SIZE) -> int:
        """Update the base fee based on the latest block's size."""
        self.base_fee = self.calculate_next_base_fee(block_size, target_size)
        self._history.append(self.base_fee)
        return self.base_fee

    def calculate_fee(
        self, tx_size: int, priority_fee_per_byte: int = 0
    ) -> FeeBreakdown:
        """
        Calculate the fee breakdown for a transaction.

        Args:
            tx_size: Transaction size in bytes
            priority_fee_per_byte: Optional priority fee (tip) per byte

        Returns:
            FeeBreakdown with all fee components.
        """
        base_total = self.base_fee * tx_size
        priority_total = priority_fee_per_byte * tx_size
        total = base_total + priority_total

        burned = base_total * params.FEE_BURN_PERCENTAGE // 100
        miner_reward = total - burned

        return FeeBreakdown(
            base_fee=base_total,
            priority_fee=priority_total,
            total_fee=total,
            burned_amount=burned,
            miner_reward=miner_reward,
        )

    def process_block_fees(
        self, transactions_fees: list[tuple[int, int]]
    ) -> tuple[int, int]:
        """
        Process all transaction fees in a block.

        Args:
            transactions_fees: List of (tx_size, priority_fee_per_byte)

        Returns:
            (total_miner_reward, total_burned)
        """
        total_miner = 0
        total_burned = 0

        for tx_size, priority_per_byte in transactions_fees:
            breakdown = self.calculate_fee(tx_size, priority_per_byte)
            total_miner += breakdown.miner_reward
            total_burned += breakdown.burned_amount

        self.total_burned += total_burned
        return total_miner, total_burned

    @property
    def effective_supply_reduction(self) -> int:
        """Total supply reduction from fee burning."""
        return self.total_burned
