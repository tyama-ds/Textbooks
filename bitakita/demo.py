#!/usr/bin/env python3
"""
BitAkita Demo - Full workflow demonstrating all 8 innovations.

This script simulates a BitAkita network with:
1. Genesis block mining
2. Wallet creation and key generation
3. PoW mining with dynamic fees
4. Transaction creation and signing
5. Stealth address payments
6. PoS validator registration and checkpoint finality
7. On-chain governance voting
8. UTXO rental demonstration
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bitakita.core.blockchain import Blockchain
from bitakita.core.transaction import Transaction, TxType
from bitakita.wallet.wallet import Wallet
from bitakita.mining.miner import Miner
from bitakita.network.node import Node
from bitakita.crypto.stealth import StealthAddress
from bitakita.consensus.hybrid import HybridConsensus
from bitakita import params


def separator(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")


def format_bita(inu: int) -> str:
    return f"{inu / 1_0000_0000:.8f} BITA"


def main():
    print("BitAkita - Next-Generation Cryptocurrency Demo")
    print("=" * 60)

    # ============================================================
    # 1. Setup: Create wallets and blockchain
    # ============================================================
    separator("1. Setup: Wallets and Blockchain")

    alice_wallet = Wallet(network="mainnet")
    alice_wallet.generate_key()
    print(f"Alice's address: {alice_wallet.get_address()}")

    bob_wallet = Wallet(network="mainnet")
    bob_wallet.generate_key()
    print(f"Bob's address:   {bob_wallet.get_address()}")

    miner_wallet = Wallet(network="mainnet")
    miner_wallet.generate_key()
    print(f"Miner's address: {miner_wallet.get_address()}")

    blockchain = Blockchain()
    miner = Miner(blockchain, miner_wallet.get_pubkey_hash())

    # ============================================================
    # 2. Mine Genesis Block
    # ============================================================
    separator("2. Mine Genesis Block")

    genesis = miner.mine_genesis_block()
    blockchain.add_genesis_block(genesis)
    print(f"Genesis block mined!")
    print(f"  Hash:   {genesis.hash_hex()[:32]}...")
    print(f"  Reward: {format_bita(params.INITIAL_REWARD)}")
    print(f"  Miner balance: {format_bita(miner_wallet.get_balance(blockchain))}")

    # ============================================================
    # 3. Mine More Blocks (demonstrates PoW + dynamic fees)
    # ============================================================
    separator("3. Mine Blocks (PoW + Dynamic Fees)")

    for i in range(5):
        block = miner.mine_block()
        if block:
            success, msg = blockchain.add_block(block)
            if success:
                print(f"  Block {blockchain.height}: hash={block.hash_hex()[:16]}... "
                      f"base_fee={blockchain.fee_manager.base_fee} inu")

    print(f"\nMiner balance after 6 blocks: {format_bita(miner_wallet.get_balance(blockchain))}")
    print(f"Blockchain height: {blockchain.height}")

    # ============================================================
    # 4. Regular Transaction (Alice receives from Miner)
    # ============================================================
    separator("4. Regular Transaction")

    tx = miner_wallet.create_transaction(
        blockchain,
        alice_wallet.get_address(),
        10_0000_0000,  # 10 BITA
    )
    success, msg = blockchain.add_to_mempool(tx)
    print(f"Tx to Alice: {msg}")

    block = miner.mine_block()
    if block:
        success, msg = blockchain.add_block(block)
        print(f"Block mined: {msg}")

    print(f"Alice balance: {format_bita(alice_wallet.get_balance(blockchain))}")
    print(f"Miner balance: {format_bita(miner_wallet.get_balance(blockchain))}")

    # ============================================================
    # 5. Stealth Address Payment (private payment to Bob)
    # ============================================================
    separator("5. Stealth Address Payment")

    bob_stealth = bob_wallet.generate_stealth_address()
    stealth_str = bob_wallet.get_stealth_address_string()
    print(f"Bob's stealth address: {stealth_str[:40]}...")

    # Alice sends to Bob's stealth address
    one_time_hash, ephemeral_pub, _ = bob_stealth.generate_one_time_address()
    print(f"One-time address hash: {one_time_hash.hex()[:32]}...")
    print(f"Ephemeral pubkey:      {ephemeral_pub.hex()[:32]}...")

    # Bob scans and finds the payment
    matches = bob_wallet.scan_stealth_transaction(
        ephemeral_pub,
        [one_time_hash],
    )
    print(f"Bob found {len(matches)} stealth payment(s) at output index: {matches}")
    print("  -> External observers cannot link this to Bob's public address!")

    # ============================================================
    # 6. PoS Validator Registration + Checkpoint Finality
    # ============================================================
    separator("6. PoS Staking + Checkpoint Finality")

    # Register miner as a validator
    validator_key = miner_wallet.keys[0]
    success, msg = blockchain.consensus.register_validator(
        validator_key.public_key,
        params.MIN_STAKE_AMOUNT,
        blockchain.height,
    )
    print(f"Validator registration: {msg}")
    print(f"Total stake: {format_bita(blockchain.consensus.total_stake)}")
    print(f"Active validators: {blockchain.consensus.validator_count}")

    # Mine blocks until a checkpoint
    blocks_to_checkpoint = params.CHECKPOINT_INTERVAL - (blockchain.height % params.CHECKPOINT_INTERVAL)
    if blocks_to_checkpoint == params.CHECKPOINT_INTERVAL:
        blocks_to_checkpoint = params.CHECKPOINT_INTERVAL

    print(f"\nMining {blocks_to_checkpoint} blocks to reach checkpoint...")
    for i in range(blocks_to_checkpoint):
        block = miner.mine_block()
        if block:
            success, msg = blockchain.add_block(block)

    cp_height = blockchain.height
    cp_hash = blockchain.chain[-1].hash()

    # Create and vote on checkpoint
    checkpoint = blockchain.consensus.checkpoint_mgr.create_checkpoint(cp_height, cp_hash)
    success, msg = blockchain.consensus.vote_checkpoint(
        cp_height, cp_hash, validator_key.private_key
    )
    print(f"Checkpoint vote at height {cp_height}: {msg}")
    print(f"Finalized height: {blockchain.consensus.finalized_height}")
    print("  -> Blocks up to this height are now irreversible!")

    # ============================================================
    # 7. On-chain Governance
    # ============================================================
    separator("7. On-chain Governance")

    # Propose increasing the target block size
    success, msg, proposal = blockchain.governance.create_proposal(
        proposer_pubkey_hash=validator_key.pubkey_hash,
        param_name="TARGET_BLOCK_SIZE",
        new_value=4_000_000,  # 4 MB
        current_height=blockchain.height,
    )
    print(f"Proposal created: {msg}")
    if proposal:
        print(f"  Parameter: TARGET_BLOCK_SIZE")
        print(f"  Current:   {params.TARGET_BLOCK_SIZE:,} bytes")
        print(f"  Proposed:  4,000,000 bytes")

        # Vote on the proposal
        success, msg = blockchain.governance.cast_vote(
            proposal.proposal_id,
            validator_key.pubkey_hash,
            approve=True,
        )
        print(f"Vote: {msg}")
        print(f"  Approval: {proposal.approval_percentage:.1f}%")

    # ============================================================
    # 8. EIP-1559 Fee Mechanism
    # ============================================================
    separator("8. EIP-1559 Fee Mechanism")

    print(f"Current base fee: {blockchain.fee_manager.base_fee} inu/byte")
    print(f"Total burned:     {format_bita(blockchain.fee_manager.total_burned)}")

    breakdown = blockchain.fee_manager.calculate_fee(250, priority_fee_per_byte=2)
    print(f"\nFee estimate for 250-byte tx:")
    print(f"  Base fee:     {breakdown.base_fee} inu")
    print(f"  Priority fee: {breakdown.priority_fee} inu")
    print(f"  Total fee:    {breakdown.total_fee} inu")
    print(f"  Burned:       {breakdown.burned_amount} inu ({params.FEE_BURN_PERCENTAGE}%)")
    print(f"  Miner gets:   {breakdown.miner_reward} inu")

    # ============================================================
    # 9. UTXO Rental Info
    # ============================================================
    separator("9. UTXO Rental (Storage Fees)")

    utxo_count = len(blockchain.utxo_set)
    print(f"Current UTXO set size: {utxo_count}")
    print(f"Grace period: {params.UTXO_RENT_GRACE_PERIOD:,} blocks "
          f"(~{params.UTXO_RENT_GRACE_PERIOD * params.TARGET_BLOCK_TIME / 86400:.0f} days)")
    print(f"Rent per block: {params.UTXO_RENT_PER_BLOCK} inu/UTXO")
    print(f"Dust threshold: {params.UTXO_DUST_THRESHOLD} inu")
    print("  -> Old, unused UTXOs will slowly lose value and be pruned")

    # ============================================================
    # 10. Network Simulation
    # ============================================================
    separator("10. P2P Network Simulation")

    node1 = Node("node-1", blockchain)
    node2 = Node("node-2")
    node3 = Node("node-3")

    node1.connect(node2)
    node2.connect(node3)

    print(f"Node 1: height={node1.height}, peers={len(node1.peers)}")
    print(f"Node 2: height={node2.height}, peers={len(node2.peers)}")
    print(f"Node 3: height={node3.height}, peers={len(node3.peers)}")

    # Sync nodes
    synced = node2.sync_with_peer(node1)
    print(f"\nNode 2 synced {synced} blocks from Node 1")

    synced = node3.sync_with_peer(node2)
    print(f"Node 3 synced {synced} blocks from Node 2")

    print(f"\nAfter sync:")
    print(f"  Node 1 height: {node1.height}")
    print(f"  Node 2 height: {node2.height}")
    print(f"  Node 3 height: {node3.height}")

    # ============================================================
    # Summary
    # ============================================================
    separator("Summary: BitAkita vs Bitcoin")

    print(f"{'Feature':<30} {'Bitcoin':<25} {'BitAkita':<25}")
    print("-" * 80)
    comparisons = [
        ("Consensus", "PoW only", "PoW/PoS Hybrid"),
        ("Block time", "10 min", f"{params.TARGET_BLOCK_TIME}s"),
        ("Block size", "1 MB fixed", "Dynamic (0.5-8 MB)"),
        ("Fee model", "First-price auction", "EIP-1559 + burn"),
        ("Privacy", "Pseudonymous", "Stealth addresses"),
        ("Finality", "Probabilistic (~60m)", f"Checkpoint ({params.CHECKPOINT_INTERVAL} blocks)"),
        ("Governance", "Off-chain", "On-chain voting"),
        ("UTXO bloat", "Uncontrolled", "Rental fees"),
        ("Supply", "21M BTC", "21M BITA"),
        ("Smallest unit", "satoshi", "inu"),
    ]
    for feature, btc, bita in comparisons:
        print(f"{feature:<30} {btc:<25} {bita:<25}")

    print(f"\nBlockchain stats:")
    print(f"  Height:             {blockchain.height}")
    print(f"  Total supply:       {format_bita(blockchain.total_supply)}")
    print(f"  Total burned:       {format_bita(blockchain.total_burned)}")
    print(f"  Circulating:        {format_bita(blockchain.circulating_supply)}")
    print(f"  UTXO count:         {len(blockchain.utxo_set)}")
    print(f"  Validators:         {blockchain.consensus.validator_count}")
    print(f"  Finalized height:   {blockchain.consensus.finalized_height}")

    print("\nBitAkita demo complete!")


if __name__ == "__main__":
    main()
