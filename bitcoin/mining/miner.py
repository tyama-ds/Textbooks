"""
Bitcoin Proof of Work Mining.

Miners compete to find a nonce such that the block header hash is below
the difficulty target. This is computationally expensive but easy to verify.

The mining process:
1. Collect transactions from the mempool
2. Create a coinbase transaction (block reward + fees)
3. Build a candidate block with the transactions
4. Iterate the nonce until the block hash meets the target
5. Broadcast the valid block to the network
"""

from __future__ import annotations

import time
from typing import Optional, Callable

from bitcoin.core.block import Block, BlockHeader
from bitcoin.core.blockchain import Blockchain
from bitcoin.core.transaction import Transaction, CoinbaseTransaction


class Miner:
    """
    A Bitcoin miner that performs Proof of Work.
    """

    def __init__(self, blockchain: Blockchain, miner_pubkey_hash: bytes):
        """
        Args:
            blockchain: The blockchain to mine on
            miner_pubkey_hash: Hash160 of the miner's public key (for reward)
        """
        self.blockchain = blockchain
        self.miner_pubkey_hash = miner_pubkey_hash

    def create_candidate_block(
        self,
        extra_transactions: Optional[list[Transaction]] = None,
        message: bytes = b"",
    ) -> Block:
        """
        Create a candidate block ready for mining.

        Includes transactions from the mempool plus any extra transactions.
        """
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

        # Create coinbase transaction
        coinbase = CoinbaseTransaction(
            block_height=height,
            reward=reward + total_fees,
            recipient_pubkey_hash=self.miner_pubkey_hash,
            message=message,
        )

        # Build block
        all_transactions = [coinbase] + transactions

        prev_hash = self.blockchain.chain[-1].hash() if self.blockchain.chain else b"\x00" * 32
        bits = self.blockchain.get_current_bits()

        header = BlockHeader(
            version=1,
            prev_block_hash=prev_hash,
            timestamp=int(time.time()),
            bits=bits,
            nonce=0,
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
        """
        Mine a block by finding a valid nonce.

        Args:
            block: Pre-built candidate block (or None to create one)
            message: Message to include in coinbase (if creating new block)
            max_nonce: Maximum nonce to try before giving up
            progress_callback: Called with (nonce, hashes_per_sec) periodically

        Returns:
            The mined block, or None if max_nonce reached without finding a solution.
        """
        if block is None:
            block = self.create_candidate_block(message=message)

        target = block.header.target()
        start_time = time.time()
        last_report = start_time

        for nonce in range(max_nonce):
            block.header.nonce = nonce
            block_hash = int.from_bytes(block.header.hash(), "big")

            if block_hash < target:
                return block

            # Progress reporting
            if progress_callback and nonce % 10000 == 0 and nonce > 0:
                elapsed = time.time() - start_time
                rate = nonce / elapsed if elapsed > 0 else 0
                progress_callback(nonce, int(rate))

        return None

    def mine_genesis_block(
        self,
        message: bytes = b"The Times 03/Jan/2009 Chancellor on brink of second bailout for banks",
        timestamp: int = 1231006505,
    ) -> Block:
        """
        Mine the genesis block (the first block in the chain).

        The default message matches Bitcoin's actual genesis block message.
        """
        height = 0
        reward = self.blockchain.get_block_reward(height)

        coinbase = CoinbaseTransaction(
            block_height=height,
            reward=reward,
            recipient_pubkey_hash=self.miner_pubkey_hash,
            message=message,
        )

        header = BlockHeader(
            version=1,
            prev_block_hash=b"\x00" * 32,
            timestamp=timestamp,
            bits=self.blockchain.initial_bits,
            nonce=0,
        )

        block = Block(header=header, transactions=[coinbase])
        block.update_merkle_root()

        # Mine it
        result = self.mine_block(block=block)
        if result is None:
            raise RuntimeError("Failed to mine genesis block")
        return result
