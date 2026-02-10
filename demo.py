#!/usr/bin/env python3
"""
Bitcoin Demo - demonstrates the full Bitcoin workflow.

This script simulates a small Bitcoin network with:
1. Genesis block creation
2. Mining blocks
3. Sending transactions between wallets
4. Block propagation across nodes
5. Balance tracking
"""

import time
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from bitcoin.crypto.keys import PrivateKey
from bitcoin.core.blockchain import Blockchain
from bitcoin.core.block import Block
from bitcoin.mining.miner import Miner
from bitcoin.wallet.wallet import Wallet
from bitcoin.network.node import Node


def format_btc(satoshis: int) -> str:
    """Format satoshis as BTC."""
    return f"{satoshis / 1_0000_0000:.8f} BTC"


def main():
    print("=" * 70)
    print("  Bitcoin Implementation Demo")
    print("=" * 70)

    # --- Step 1: Create wallets ---
    print("\n[1] Creating wallets...")
    alice_wallet = Wallet()
    bob_wallet = Wallet()
    miner_wallet = Wallet()

    alice_kp = alice_wallet.generate_key()
    bob_kp = bob_wallet.generate_key()
    miner_kp = miner_wallet.generate_key()

    print(f"  Alice's address:  {alice_kp.address}")
    print(f"  Bob's address:    {bob_kp.address}")
    print(f"  Miner's address:  {miner_kp.address}")

    # --- Step 2: Set up network ---
    print("\n[2] Setting up network nodes...")
    # Use easy difficulty for demo (high target = easy mining)
    initial_bits = 0x2100FFFF

    blockchain_a = Blockchain(initial_bits=initial_bits)
    blockchain_b = Blockchain(initial_bits=initial_bits)

    node_a = Node("node-A", blockchain_a)
    node_b = Node("node-B", blockchain_b)
    node_a.connect(node_b)

    print(f"  {node_a}")
    print(f"  {node_b}")
    print(f"  Nodes connected: {node_a.peer_count} peers each")

    # --- Step 3: Mine genesis block ---
    print("\n[3] Mining genesis block...")
    miner = Miner(blockchain_a, miner_kp.pubkey_hash)
    genesis = miner.mine_genesis_block(
        message=b"Hello Bitcoin!",
        timestamp=int(time.time()),
    )
    blockchain_a.add_genesis_block(genesis)
    print(f"  Genesis block hash: {genesis.hash_hex()[:32]}...")
    print(f"  Miner reward: {format_btc(miner_wallet.get_balance(blockchain_a))}")

    # Sync node B
    synced = node_b.sync_with_peer(node_a)
    print(f"  Node B synced: {synced} block(s)")

    # --- Step 4: Mine a few more blocks for the miner ---
    print("\n[4] Mining blocks to accumulate coins...")
    for i in range(3):
        block = miner.create_candidate_block(
            message=f"Block {i+1}".encode()
        )
        mined = miner.mine_block(block=block)
        if mined:
            success, msg = blockchain_a.add_block(mined)
            if success:
                node_a.broadcast_block(mined)
                print(f"  Block {blockchain_a.height}: {mined.hash_hex()[:32]}...")

    miner_balance = miner_wallet.get_balance(blockchain_a)
    print(f"  Miner balance: {format_btc(miner_balance)} ({blockchain_a.height + 1} blocks mined)")

    # --- Step 5: Send coins from miner to Alice ---
    print("\n[5] Miner sends 25 BTC to Alice...")
    amount = 25_0000_0000  # 25 BTC
    fee = 10000  # 0.0001 BTC fee

    tx = miner_wallet.create_transaction(
        blockchain=blockchain_a,
        recipient_address=alice_kp.address,
        amount=amount,
        fee=fee,
    )
    print(f"  Transaction ID: {tx.txid_hex()[:32]}...")
    print(f"  Inputs: {len(tx.inputs)}, Outputs: {len(tx.outputs)}")

    # Add to mempool
    success, msg = blockchain_a.add_to_mempool(tx)
    print(f"  Mempool: {msg}")

    # Mine a block to confirm the transaction
    print("\n[6] Mining block to confirm transaction...")
    block = miner.create_candidate_block()
    mined = miner.mine_block(block=block)
    if mined:
        success, msg = blockchain_a.add_block(mined)
        if success:
            node_a.broadcast_block(mined)
            print(f"  Block {blockchain_a.height}: {msg}")

    alice_balance = alice_wallet.get_balance(blockchain_a)
    miner_balance = miner_wallet.get_balance(blockchain_a)
    print(f"  Alice balance: {format_btc(alice_balance)}")
    print(f"  Miner balance: {format_btc(miner_balance)}")

    # --- Step 6: Alice sends to Bob ---
    print("\n[7] Alice sends 10 BTC to Bob...")
    tx2 = alice_wallet.create_transaction(
        blockchain=blockchain_a,
        recipient_address=bob_kp.address,
        amount=10_0000_0000,
        fee=10000,
    )
    print(f"  Transaction ID: {tx2.txid_hex()[:32]}...")

    success, msg = blockchain_a.add_to_mempool(tx2)
    print(f"  Mempool: {msg}")

    # Mine another block
    print("\n[8] Mining block to confirm Alice->Bob transaction...")
    block = miner.create_candidate_block()
    mined = miner.mine_block(block=block)
    if mined:
        success, msg = blockchain_a.add_block(mined)
        if success:
            node_a.broadcast_block(mined)
            print(f"  Block {blockchain_a.height}: {msg}")

    # --- Step 7: Final balances ---
    print("\n[9] Final balances:")
    # Sync node B
    synced = node_b.sync_with_peer(node_a)
    print(f"  Node B synced: {synced} block(s)")

    for name, wallet, chain in [
        ("Alice", alice_wallet, blockchain_a),
        ("Bob", bob_wallet, blockchain_a),
        ("Miner", miner_wallet, blockchain_a),
    ]:
        bal = wallet.get_balance(chain)
        print(f"  {name:8s}: {format_btc(bal)}")

    # Cross-check with node B
    print("\n  Node B balances (cross-check):")
    for name, wallet in [("Alice", alice_wallet), ("Bob", bob_wallet), ("Miner", miner_wallet)]:
        bal = wallet.get_balance(blockchain_b)
        print(f"  {name:8s}: {format_btc(bal)}")

    # --- Step 8: Blockchain info ---
    print("\n[10] Blockchain info:")
    print(f"  Chain length: {len(blockchain_a.chain)} blocks")
    print(f"  UTXO set size: {len(blockchain_a.utxo_set)}")
    print(f"  Mempool size: {len(blockchain_a.mempool)}")
    print(f"  Block reward at current height: {format_btc(blockchain_a.get_block_reward(blockchain_a.height))}")

    print("\n  Block hashes:")
    for i, block in enumerate(blockchain_a.chain):
        n_txs = len(block.transactions)
        print(f"    [{i}] {block.hash_hex()[:40]}... ({n_txs} tx)")

    print("\n" + "=" * 70)
    print("  Demo complete!")
    print("=" * 70)


if __name__ == "__main__":
    main()
