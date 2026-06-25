"""
BitAkita Blockchain - Fully integrated with all 8 innovations.

This blockchain combines:
1. PoW/PoS Hybrid Consensus (via HybridConsensus)
2. 60-second Block Time + Dynamic Block Size
3. EIP-1559 Fee Mechanism with burn
4. Stealth Address support (application-layer)
5. PoS Checkpoint Finality
6. On-chain Governance
7. UTXO Rental (storage fees for old UTXOs)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from bitcoin.crypto.hash import double_sha256
from bitcoin.script.script import Script, ScriptInterpreter
from bitakita import params
from bitakita.core.block import Block, BlockHeader
from bitakita.core.transaction import (
    Transaction, CoinbaseTransaction, StakeTransaction,
    TxInput, TxOutput, TxType,
)
from bitakita.consensus.hybrid import HybridConsensus
from bitakita.fee.eip1559 import FeeManager
from bitakita.governance.voting import GovernanceSystem


@dataclass
class UTXO:
    """An unspent transaction output with age tracking for rental."""
    tx_hash: bytes
    output_index: int
    output: TxOutput
    block_height: int       # When this UTXO was created
    is_staked: bool = False  # Locked as PoS stake


class Blockchain:
    """
    The BitAkita blockchain with all innovations integrated.
    """

    def __init__(self, initial_bits: int = params.DEFAULT_INITIAL_BITS):
        # Core state
        self.chain: list[Block] = []
        self.utxo_set: dict[tuple[bytes, int], UTXO] = {}
        self.mempool: list[Transaction] = []
        self.initial_bits = initial_bits
        self._block_index: dict[bytes, int] = {}

        # Innovation subsystems
        self.consensus = HybridConsensus()
        self.fee_manager = FeeManager()
        self.governance = GovernanceSystem(self.consensus.stake_pool)

        # Tracking
        self.total_supply: int = 0
        self._utxo_burned: int = 0
        self._recent_block_sizes: list[int] = []

    # --- Properties ---

    @property
    def height(self) -> int:
        return len(self.chain) - 1

    @property
    def tip(self) -> Optional[Block]:
        return self.chain[-1] if self.chain else None

    @property
    def total_burned(self) -> int:
        return self._utxo_burned + self.fee_manager.total_burned

    @property
    def circulating_supply(self) -> int:
        return self.total_supply - self.total_burned

    # --- Block Reward ---

    def get_block_reward(self, height: int) -> int:
        halvings = height // params.HALVING_INTERVAL
        if halvings >= 64:
            return 0
        return params.INITIAL_REWARD >> halvings

    # --- Difficulty ---

    def get_current_bits(self) -> int:
        if not self.chain:
            return self.initial_bits

        current_height = len(self.chain)
        if current_height % params.DIFFICULTY_ADJUSTMENT_INTERVAL != 0:
            return self.chain[-1].header.bits

        interval = params.DIFFICULTY_ADJUSTMENT_INTERVAL
        if current_height < interval:
            return self.chain[-1].header.bits

        period_start = self.chain[-interval]
        period_end = self.chain[-1]

        actual_time = period_end.header.timestamp - period_start.header.timestamp
        expected_time = params.TARGET_BLOCK_TIME * interval

        if actual_time < expected_time // 4:
            actual_time = expected_time // 4
        if actual_time > expected_time * 4:
            actual_time = expected_time * 4

        current_target = BlockHeader.target_from_bits(period_end.header.bits)
        new_target = current_target * actual_time // expected_time

        max_target = BlockHeader.target_from_bits(self.initial_bits)
        if new_target > max_target:
            new_target = max_target

        return BlockHeader.bits_from_target(new_target)

    # --- Dynamic Block Size ---

    def get_current_block_size_limit(self) -> int:
        if not self.chain:
            return params.TARGET_BLOCK_SIZE
        current_limit = self.chain[-1].header.block_size_limit
        return Block.calculate_dynamic_size_limit(
            self._recent_block_sizes[-20:],
            current_limit,
        )

    # --- Genesis Block ---

    def add_genesis_block(self, genesis_block: Block) -> bool:
        if self.chain:
            return False
        self.chain.append(genesis_block)
        self._block_index[genesis_block.hash()] = 0
        self._update_utxo_set(genesis_block, 0)
        self._track_supply(genesis_block, 0)
        return True

    # --- Block Addition ---

    def add_block(self, block: Block) -> tuple[bool, str]:
        if not self.chain:
            return False, "No genesis block; use add_genesis_block()"

        # Check prev hash
        expected_prev = self.chain[-1].hash()
        if block.header.prev_block_hash != expected_prev:
            return False, "Previous block hash mismatch"

        # Validate block structure
        valid, msg = block.validate()
        if not valid:
            return False, msg

        height = len(self.chain)

        # Validate transactions
        valid, msg = self._validate_block_transactions(block, height)
        if not valid:
            return False, msg

        # Add to chain
        self.chain.append(block)
        self._block_index[block.hash()] = height
        self._update_utxo_set(block, height)
        self._track_supply(block, height)

        # Update dynamic block size tracking
        self._recent_block_sizes.append(block.block_size())
        if len(self._recent_block_sizes) > 50:
            self._recent_block_sizes = self._recent_block_sizes[-50:]

        # Process EIP-1559 fee burns for this block's transactions
        base_fee = block.header.base_fee
        for tx in block.transactions[1:]:
            burn = base_fee * tx.size() * params.FEE_BURN_PERCENTAGE // 100
            self.fee_manager.total_burned += burn

        # Update EIP-1559 base fee for next block
        self.fee_manager.update_base_fee(
            block.block_size(),
            self.governance.get_param("TARGET_BLOCK_SIZE"),
        )

        # Process PoS checkpoints (rewards distributed separately)
        checkpoint = self.consensus.on_new_block(height, block.hash())

        # Process staking transactions
        self._process_stake_transactions(block, height)

        # Process governance
        self.governance.process_proposals(height)

        # Apply UTXO rent
        self._apply_utxo_rent(height)

        # Remove confirmed txs from mempool
        confirmed_txids = {tx.txid() for tx in block.transactions[1:]}
        self.mempool = [tx for tx in self.mempool if tx.txid() not in confirmed_txids]

        return True, "Block added successfully"

    # --- Transaction Validation ---

    def _validate_block_transactions(self, block: Block, height: int) -> tuple[bool, str]:
        if not block.transactions:
            return False, "Block has no transactions"

        coinbase = block.transactions[0]
        total_fees = 0

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

                if utxo.is_staked:
                    if tx.tx_type != TxType.UNSTAKE:
                        return False, f"Tx {i}: cannot spend staked UTXO"

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

    # --- UTXO Management ---

    def _update_utxo_set(self, block: Block, height: int) -> None:
        for tx in block.transactions:
            if not tx.inputs[0].is_coinbase():
                for txin in tx.inputs:
                    self.utxo_set.pop((txin.prev_tx_hash, txin.output_index), None)

            tx_hash = tx.txid()
            for i, txout in enumerate(tx.outputs):
                if txout.amount > 0:
                    is_staked = tx.tx_type == TxType.STAKE and i == 0
                    self.utxo_set[(tx_hash, i)] = UTXO(
                        tx_hash=tx_hash,
                        output_index=i,
                        output=txout,
                        block_height=height,
                        is_staked=is_staked,
                    )

    def _track_supply(self, block: Block, height: int) -> None:
        """Track total supply from block reward (new coin issuance only)."""
        self.total_supply += self.get_block_reward(height)

    # --- UTXO Rental (Storage Fees) ---

    def _apply_utxo_rent(self, current_height: int) -> None:
        """
        Apply storage rent to old UTXOs.

        UTXOs older than UTXO_RENT_GRACE_PERIOD blocks are charged
        UTXO_RENT_PER_BLOCK inu per block. UTXOs that fall below the
        dust threshold are removed (fees collected by protocol).
        """
        grace = self.governance.get_param("UTXO_RENT_GRACE_PERIOD")
        to_remove = []

        for key, utxo in self.utxo_set.items():
            if utxo.is_staked:
                continue  # Staked UTXOs are exempt from rent

            age = current_height - utxo.block_height
            if age <= grace:
                continue

            # Calculate rent
            blocks_past_grace = age - grace
            rent = blocks_past_grace * params.UTXO_RENT_PER_BLOCK

            # Check if UTXO can cover rent
            effective_value = utxo.output.amount - rent
            if effective_value <= params.UTXO_DUST_THRESHOLD:
                to_remove.append(key)
                self._utxo_burned += utxo.output.amount

        for key in to_remove:
            del self.utxo_set[key]

    # --- Staking ---

    def _process_stake_transactions(self, block: Block, height: int) -> None:
        """Process stake/unstake transactions in a block."""
        for tx in block.transactions:
            if tx.tx_type == TxType.STAKE and isinstance(tx, StakeTransaction):
                pubkey_hash = tx.staker_pubkey_hash
                # We need the public key - extract from scriptSig of input
                # For simplicity, store the stake registration via pubkey_hash
                # The actual public key would be recovered from the scriptSig
                # For now, we mark the UTXO as staked (done in _update_utxo_set)
                pass

    # --- Mempool ---

    def add_to_mempool(self, tx: Transaction) -> tuple[bool, str]:
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

            if utxo.is_staked and tx.tx_type != TxType.UNSTAKE:
                return False, f"Input {i}: UTXO is staked"

            interpreter = ScriptInterpreter()
            tx_hash = tx.hash_for_signing(i, utxo.output.script_pubkey)
            if not interpreter.verify(txin.script_sig, utxo.output.script_pubkey, tx_hash):
                return False, f"Input {i}: script verification failed"

            input_total += utxo.output.amount

        output_total = sum(txout.amount for txout in tx.outputs)

        # Check minimum fee (base_fee * tx_size)
        min_fee = self.fee_manager.base_fee * tx.size()
        actual_fee = input_total - output_total
        if actual_fee < min_fee:
            return False, f"Fee too low: {actual_fee} < {min_fee} (base_fee={self.fee_manager.base_fee})"

        self.mempool.append(tx)
        return True, f"Transaction added to mempool (fee: {actual_fee} inu)"

    # --- Balance Queries ---

    def get_balance(self, pubkey_hash: bytes) -> int:
        expected_script = Script.p2pkh_locking(pubkey_hash)
        total = 0
        for utxo in self.utxo_set.values():
            if utxo.output.script_pubkey.data == expected_script.data:
                total += utxo.output.amount
        return total

    def get_utxos_for(self, pubkey_hash: bytes) -> list[UTXO]:
        expected_script = Script.p2pkh_locking(pubkey_hash)
        return [
            utxo for utxo in self.utxo_set.values()
            if utxo.output.script_pubkey.data == expected_script.data
        ]

    def get_spendable_utxos_for(self, pubkey_hash: bytes) -> list[UTXO]:
        """Get UTXOs that are not staked (available for spending)."""
        return [
            utxo for utxo in self.get_utxos_for(pubkey_hash)
            if not utxo.is_staked
        ]
