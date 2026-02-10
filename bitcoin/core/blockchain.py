"""
Bitcoin Blockchain - manages the chain of blocks and UTXO set.

The blockchain enforces:
- Each block references the previous block's hash
- Proof of Work is valid for each block
- Transactions are valid (inputs reference existing UTXOs, scripts verify)
- Block reward follows the halving schedule
- No double-spending (each UTXO can only be spent once)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from bitcoin.core.block import Block, BlockHeader
from bitcoin.core.transaction import Transaction, CoinbaseTransaction, TxOutput
from bitcoin.script.script import ScriptInterpreter


# Bitcoin constants
INITIAL_REWARD = 50_0000_0000  # 50 BTC in satoshis
HALVING_INTERVAL = 210_000     # Blocks between reward halvings
MAX_SUPPLY = 21_000_000 * 100_000_000  # 21 million BTC in satoshis

# Target block time: 10 minutes
TARGET_BLOCK_TIME = 600  # seconds

# Difficulty adjustment interval: every 2016 blocks (~2 weeks)
DIFFICULTY_ADJUSTMENT_INTERVAL = 2016

# Default initial difficulty (very easy for testing)
DEFAULT_INITIAL_BITS = 0x2000FFFF


@dataclass
class UTXO:
    """An unspent transaction output."""
    tx_hash: bytes
    output_index: int
    output: TxOutput
    block_height: int


class Blockchain:
    """
    The Bitcoin blockchain.

    Maintains:
    - The ordered chain of blocks
    - The UTXO set (all currently spendable outputs)
    - The mempool (unconfirmed transactions)
    """

    def __init__(self, initial_bits: int = DEFAULT_INITIAL_BITS):
        self.chain: list[Block] = []
        self.utxo_set: dict[tuple[bytes, int], UTXO] = {}
        self.mempool: list[Transaction] = []
        self.initial_bits = initial_bits
        self._block_index: dict[bytes, int] = {}  # block_hash -> chain index

    @property
    def height(self) -> int:
        """Current blockchain height (number of blocks - 1, or -1 if empty)."""
        return len(self.chain) - 1

    @property
    def tip(self) -> Optional[Block]:
        """The latest block in the chain."""
        return self.chain[-1] if self.chain else None

    def get_block_reward(self, height: int) -> int:
        """
        Calculate the block reward for a given height.

        The reward starts at 50 BTC and halves every 210,000 blocks.
        """
        halvings = height // HALVING_INTERVAL
        if halvings >= 64:
            return 0
        return INITIAL_REWARD >> halvings

    def get_current_bits(self) -> int:
        """
        Get the current difficulty target bits.

        Difficulty adjusts every DIFFICULTY_ADJUSTMENT_INTERVAL blocks
        to maintain the TARGET_BLOCK_TIME average.
        """
        if not self.chain:
            return self.initial_bits

        current_height = len(self.chain)

        if current_height % DIFFICULTY_ADJUSTMENT_INTERVAL != 0:
            return self.chain[-1].header.bits

        # Time to adjust difficulty
        period_start = self.chain[-DIFFICULTY_ADJUSTMENT_INTERVAL]
        period_end = self.chain[-1]

        actual_time = period_end.header.timestamp - period_start.header.timestamp
        expected_time = TARGET_BLOCK_TIME * DIFFICULTY_ADJUSTMENT_INTERVAL

        # Clamp adjustment to 4x in either direction
        if actual_time < expected_time // 4:
            actual_time = expected_time // 4
        if actual_time > expected_time * 4:
            actual_time = expected_time * 4

        # Adjust target
        current_target = BlockHeader.target_from_bits(period_end.header.bits)
        new_target = current_target * actual_time // expected_time

        # Don't exceed maximum target
        max_target = BlockHeader.target_from_bits(self.initial_bits)
        if new_target > max_target:
            new_target = max_target

        return BlockHeader.bits_from_target(new_target)

    def add_genesis_block(self, genesis_block: Block) -> bool:
        """Add the genesis block (the first block in the chain)."""
        if self.chain:
            return False

        self.chain.append(genesis_block)
        self._block_index[genesis_block.hash()] = 0
        self._update_utxo_set(genesis_block, 0)
        return True

    def add_block(self, block: Block) -> tuple[bool, str]:
        """
        Add a block to the chain after validation.

        Returns (success, message).
        """
        if not self.chain:
            return False, "No genesis block; use add_genesis_block()"

        # Check previous block hash
        expected_prev = self.chain[-1].hash()
        if block.header.prev_block_hash != expected_prev:
            return False, "Previous block hash mismatch"

        # Validate block structure
        valid, msg = block.validate()
        if not valid:
            return False, msg

        # Validate transactions
        height = len(self.chain)
        valid, msg = self._validate_block_transactions(block, height)
        if not valid:
            return False, msg

        # Add to chain
        self.chain.append(block)
        self._block_index[block.hash()] = height
        self._update_utxo_set(block, height)

        # Remove confirmed transactions from mempool
        confirmed_txids = {tx.txid() for tx in block.transactions[1:]}
        self.mempool = [tx for tx in self.mempool if tx.txid() not in confirmed_txids]

        return True, "Block added successfully"

    def _validate_block_transactions(self, block: Block, height: int) -> tuple[bool, str]:
        """Validate all transactions in a block."""
        if not block.transactions:
            return False, "Block has no transactions"

        # Validate coinbase
        coinbase = block.transactions[0]
        total_fees = 0

        # Validate regular transactions and compute fees
        temp_spent: set[tuple[bytes, int]] = set()
        for i, tx in enumerate(block.transactions[1:], 1):
            input_total = 0
            for txin in tx.inputs:
                utxo_key = (txin.prev_tx_hash, txin.output_index)

                if utxo_key not in self.utxo_set:
                    return False, f"Tx {i}: input references non-existent UTXO"

                if utxo_key in temp_spent:
                    return False, f"Tx {i}: double-spend within block"

                utxo = self.utxo_set[utxo_key]

                # Verify script
                interpreter = ScriptInterpreter()
                tx_hash = tx.hash_for_signing(
                    tx.inputs.index(txin), utxo.output.script_pubkey
                )
                if not interpreter.verify(txin.script_sig, utxo.output.script_pubkey, tx_hash):
                    return False, f"Tx {i}: script verification failed"

                input_total += utxo.output.amount
                temp_spent.add(utxo_key)

            output_total = sum(txout.amount for txout in tx.outputs)
            if input_total < output_total:
                return False, f"Tx {i}: outputs exceed inputs"

            total_fees += input_total - output_total

        # Verify coinbase reward
        expected_reward = self.get_block_reward(height)
        coinbase_total = sum(txout.amount for txout in coinbase.outputs)
        if coinbase_total > expected_reward + total_fees:
            return False, "Coinbase reward exceeds allowed amount"

        return True, "Valid"

    def _update_utxo_set(self, block: Block, height: int) -> None:
        """Update the UTXO set with the transactions in a new block."""
        for tx in block.transactions:
            # Remove spent outputs
            if not tx.inputs[0].is_coinbase():
                for txin in tx.inputs:
                    utxo_key = (txin.prev_tx_hash, txin.output_index)
                    self.utxo_set.pop(utxo_key, None)

            # Add new outputs
            tx_hash = tx.txid()
            for i, txout in enumerate(tx.outputs):
                if txout.amount > 0:
                    self.utxo_set[(tx_hash, i)] = UTXO(
                        tx_hash=tx_hash,
                        output_index=i,
                        output=txout,
                        block_height=height,
                    )

    def add_to_mempool(self, tx: Transaction) -> tuple[bool, str]:
        """
        Add a transaction to the mempool after validation.

        Checks:
        1. All inputs reference existing UTXOs
        2. Scripts verify correctly
        3. Input values >= output values
        4. No double-spend with existing mempool transactions
        """
        mempool_spent = set()
        for mempool_tx in self.mempool:
            for txin in mempool_tx.inputs:
                mempool_spent.add((txin.prev_tx_hash, txin.output_index))

        input_total = 0
        for i, txin in enumerate(tx.inputs):
            utxo_key = (txin.prev_tx_hash, txin.output_index)

            if utxo_key not in self.utxo_set:
                return False, f"Input {i}: references non-existent UTXO"

            if utxo_key in mempool_spent:
                return False, f"Input {i}: conflicts with mempool transaction"

            utxo = self.utxo_set[utxo_key]

            # Verify script
            interpreter = ScriptInterpreter()
            tx_hash = tx.hash_for_signing(i, utxo.output.script_pubkey)
            if not interpreter.verify(txin.script_sig, utxo.output.script_pubkey, tx_hash):
                return False, f"Input {i}: script verification failed"

            input_total += utxo.output.amount

        output_total = sum(txout.amount for txout in tx.outputs)
        if input_total < output_total:
            return False, "Outputs exceed inputs"

        self.mempool.append(tx)
        return True, f"Transaction added to mempool (fee: {input_total - output_total} satoshis)"

    def get_balance(self, pubkey_hash: bytes) -> int:
        """Get the total balance for a public key hash."""
        from bitcoin.script.script import Script
        expected_script = Script.p2pkh_locking(pubkey_hash)
        total = 0
        for utxo in self.utxo_set.values():
            if utxo.output.script_pubkey.data == expected_script.data:
                total += utxo.output.amount
        return total

    def get_utxos_for(self, pubkey_hash: bytes) -> list[UTXO]:
        """Get all UTXOs for a public key hash."""
        from bitcoin.script.script import Script
        expected_script = Script.p2pkh_locking(pubkey_hash)
        result = []
        for utxo in self.utxo_set.values():
            if utxo.output.script_pubkey.data == expected_script.data:
                result.append(utxo)
        return result
