"""
BitAkita Miner - PoW mining with EIP-1559 fee integration.

The miner:
1. Collects transactions from the mempool
2. Creates a coinbase tx (block reward + miner's share of fees + stake rewards)
3. Sets the dynamic block size limit and base fee in the header
4. Mines via PoW (finding a valid nonce)
"""

from __future__ import annotations

import time
from typing import Optional, Callable

from bitakita.core.block import Block, BlockHeader
from bitakita.core.blockchain import Blockchain
from bitakita.core.transaction import Transaction, CoinbaseTransaction
from bitakita import params


class Miner:
    """BitAkita Proof of Work miner."""

    def __init__(self, blockchain: Blockchain, miner_pubkey_hash: bytes):
        self.blockchain = blockchain
        self.miner_pubkey_hash = miner_pubkey_hash

    def create_candidate_block(
        self,
        extra_transactions: Optional[list[Transaction]] = None,
        message: bytes = b"",
    ) -> Block:
        height = len(self.blockchain.chain)
        reward = self.blockchain.get_block_reward(height)

        # Collect transactions from mempool
        transactions = list(extra_transactions or [])
        transactions.extend(self.blockchain.mempool)

        # Calculate fees
        total_fees = 0
        for tx in transactions:
            input_total = 0
            for txin in tx.inputs:
                utxo_key = (txin.prev_tx_hash, txin.output_index)
                if utxo_key in self.blockchain.utxo_set:
                    input_total += self.blockchain.utxo_set[utxo_key].output.amount
            output_total = sum(txout.amount for txout in tx.outputs)
            total_fees += max(0, input_total - output_total)

        # Fee burn calculation
        fee_data = []
        for tx in transactions:
            fee_data.append((tx.size(), 0))
        miner_fee_share, burned = self.blockchain.fee_manager.process_block_fees(fee_data)

        # Staking rewards
        stake_rewards = self.blockchain.consensus.stake_pool.distribute_rewards(height)

        # Create coinbase
        coinbase = CoinbaseTransaction(
            block_height=height,
            reward=reward + miner_fee_share,
            recipient_pubkey_hash=self.miner_pubkey_hash,
            message=message,
            stake_rewards=stake_rewards if stake_rewards else None,
        )

        all_transactions = [coinbase] + transactions

        # Build header
        prev_hash = self.blockchain.chain[-1].hash() if self.blockchain.chain else b"\x00" * 32
        bits = self.blockchain.get_current_bits()
        base_fee = self.blockchain.fee_manager.base_fee
        size_limit = self.blockchain.get_current_block_size_limit()

        header = BlockHeader(
            version=2,
            prev_block_hash=prev_hash,
            timestamp=int(time.time()),
            bits=bits,
            nonce=0,
            base_fee=base_fee,
            block_size_limit=size_limit,
        )

        block = Block(header=header, transactions=all_transactions)
        block.update_merkle_root()
        return block

    def mine_block(
        self,
        block: Optional[Block] = None,
        message: bytes = b"",
        max_nonce: int = 2**32,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> Optional[Block]:
        if block is None:
            block = self.create_candidate_block(message=message)

        target = block.header.target()
        start_time = time.time()

        for nonce in range(max_nonce):
            block.header.nonce = nonce
            block_hash = int.from_bytes(block.header.hash(), "big")

            if block_hash < target:
                return block

            if progress_callback and nonce % 10000 == 0 and nonce > 0:
                elapsed = time.time() - start_time
                rate = nonce / elapsed if elapsed > 0 else 0
                progress_callback(nonce, int(rate))

        return None

    def mine_genesis_block(
        self,
        message: bytes = b"BitAkita genesis - a better Bitcoin for everyone",
        timestamp: int = None,
    ) -> Block:
        if timestamp is None:
            timestamp = int(time.time())

        height = 0
        reward = self.blockchain.get_block_reward(height)

        coinbase = CoinbaseTransaction(
            block_height=height,
            reward=reward,
            recipient_pubkey_hash=self.miner_pubkey_hash,
            message=message,
        )

        header = BlockHeader(
            version=2,
            prev_block_hash=b"\x00" * 32,
            timestamp=timestamp,
            bits=self.blockchain.initial_bits,
            nonce=0,
            base_fee=params.INITIAL_BASE_FEE,
            block_size_limit=params.TARGET_BLOCK_SIZE,
        )

        block = Block(header=header, transactions=[coinbase])
        block.update_merkle_root()

        result = self.mine_block(block=block)
        if result is None:
            raise RuntimeError("Failed to mine genesis block")
        return result
