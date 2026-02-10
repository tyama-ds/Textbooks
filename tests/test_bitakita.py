"""Tests for BitAkita - all 8 innovations."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest

from bitcoin.crypto.hash import sha256, double_sha256, hash160
from bitcoin.crypto.keys import PrivateKey, PublicKey, Signature
from bitcoin.utils.encoding import base58check_encode, base58check_decode
from bitcoin.core.merkle import merkle_root, merkle_proof, verify_merkle_proof

from bitakita.core.blockchain import Blockchain
from bitakita.core.transaction import Transaction, TxType
from bitakita.core.block import Block, BlockHeader
from bitakita.wallet.wallet import Wallet
from bitakita.mining.miner import Miner
from bitakita.network.node import Node
from bitakita.crypto.stealth import StealthAddress, StealthKeyPair
from bitakita.consensus.pos import StakePool
from bitakita.consensus.checkpoint import CheckpointManager
from bitakita.consensus.hybrid import HybridConsensus
from bitakita.fee.eip1559 import FeeManager
from bitakita.governance.voting import GovernanceSystem
from bitakita import params


class TestCrypto(unittest.TestCase):
    """Test cryptographic primitives."""

    def test_sha256(self):
        h = sha256(b"hello")
        self.assertEqual(len(h), 32)
        self.assertEqual(
            h.hex(),
            "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
        )

    def test_double_sha256(self):
        h = double_sha256(b"hello")
        self.assertEqual(len(h), 32)
        self.assertNotEqual(h, sha256(b"hello"))

    def test_hash160(self):
        h = hash160(b"hello")
        self.assertEqual(len(h), 20)

    def test_key_generation(self):
        priv = PrivateKey.generate()
        pub = priv.public_key
        self.assertEqual(len(priv.to_bytes()), 32)
        self.assertEqual(len(pub.compressed_bytes()), 33)
        self.assertEqual(len(pub.uncompressed_bytes()), 65)

    def test_sign_verify(self):
        priv = PrivateKey.generate()
        pub = priv.public_key
        msg_hash = double_sha256(b"test message")
        sig = priv.sign(msg_hash)
        self.assertTrue(pub.verify(sig, msg_hash))

        # Wrong message should fail
        wrong_hash = double_sha256(b"wrong message")
        self.assertFalse(pub.verify(sig, wrong_hash))

    def test_base58check(self):
        version = b"\x00"
        payload = b"\x01" * 20
        encoded = base58check_encode(version, payload)
        dec_version, dec_payload = base58check_decode(encoded)
        self.assertEqual(dec_version, version)
        self.assertEqual(dec_payload, payload)


class TestMerkleTree(unittest.TestCase):
    """Test Merkle tree."""

    def test_single_tx(self):
        hashes = [double_sha256(b"tx1")]
        root = merkle_root(hashes)
        self.assertEqual(root, hashes[0])

    def test_two_txs(self):
        h1 = double_sha256(b"tx1")
        h2 = double_sha256(b"tx2")
        root = merkle_root([h1, h2])
        expected = double_sha256(h1 + h2)
        self.assertEqual(root, expected)

    def test_proof_verify(self):
        hashes = [double_sha256(f"tx{i}".encode()) for i in range(4)]
        root = merkle_root(hashes)
        for i in range(4):
            proof = merkle_proof(hashes, i)
            self.assertTrue(verify_merkle_proof(hashes[i], proof, root))

    def test_empty(self):
        root = merkle_root([])
        self.assertEqual(root, b"\x00" * 32)


class TestBlockchain(unittest.TestCase):
    """Test BitAkita blockchain basics."""

    def setUp(self):
        self.blockchain = Blockchain()
        self.wallet = Wallet()
        self.wallet.generate_key()
        self.miner = Miner(self.blockchain, self.wallet.get_pubkey_hash())

    def test_genesis_block(self):
        genesis = self.miner.mine_genesis_block()
        self.assertTrue(self.blockchain.add_genesis_block(genesis))
        self.assertEqual(self.blockchain.height, 0)
        self.assertEqual(
            self.wallet.get_balance(self.blockchain),
            params.INITIAL_REWARD,
        )

    def test_mine_multiple_blocks(self):
        genesis = self.miner.mine_genesis_block()
        self.blockchain.add_genesis_block(genesis)

        for _ in range(5):
            block = self.miner.mine_block()
            self.assertIsNotNone(block)
            success, msg = self.blockchain.add_block(block)
            self.assertTrue(success, msg)

        self.assertEqual(self.blockchain.height, 5)

    def test_transaction(self):
        genesis = self.miner.mine_genesis_block()
        self.blockchain.add_genesis_block(genesis)

        # Mine a block so miner has funds
        block = self.miner.mine_block()
        self.blockchain.add_block(block)

        # Create recipient
        recipient = Wallet()
        recipient.generate_key()

        # Send coins
        tx = self.wallet.create_transaction(
            self.blockchain,
            recipient.get_address(),
            5_0000_0000,  # 5 BITA
        )
        success, msg = self.blockchain.add_to_mempool(tx)
        self.assertTrue(success, msg)

        # Mine the transaction
        block = self.miner.mine_block()
        success, msg = self.blockchain.add_block(block)
        self.assertTrue(success, msg)

        self.assertEqual(
            recipient.get_balance(self.blockchain),
            5_0000_0000,
        )

    def test_double_spend_rejected(self):
        genesis = self.miner.mine_genesis_block()
        self.blockchain.add_genesis_block(genesis)

        # Mine several blocks so miner has ample balance
        for _ in range(3):
            block = self.miner.mine_block()
            self.blockchain.add_block(block)

        recipient1 = Wallet()
        recipient1.generate_key()
        recipient2 = Wallet()
        recipient2.generate_key()

        # Send a significant portion to recipient1
        tx1 = self.wallet.create_transaction(
            self.blockchain,
            recipient1.get_address(),
            50_0000_0000,
        )
        success, msg = self.blockchain.add_to_mempool(tx1)
        self.assertTrue(success, msg)

        # Try to double-spend same UTXOs to recipient2
        tx2 = self.wallet.create_transaction(
            self.blockchain,
            recipient2.get_address(),
            50_0000_0000,
        )
        success, _ = self.blockchain.add_to_mempool(tx2)
        self.assertFalse(success)


class TestStealthAddress(unittest.TestCase):
    """Test stealth address privacy feature."""

    def test_generate_and_scan(self):
        keypair = StealthKeyPair.generate()
        stealth = StealthAddress.from_keypair(keypair)

        # Sender generates one-time address
        one_time_hash, ephemeral_pub, _ = stealth.generate_one_time_address()

        # Recipient scans and finds the payment
        matches = StealthAddress.scan_for_payments(
            keypair, ephemeral_pub, [one_time_hash]
        )
        self.assertEqual(matches, [0])

    def test_wrong_recipient_no_match(self):
        keypair1 = StealthKeyPair.generate()
        keypair2 = StealthKeyPair.generate()
        stealth1 = StealthAddress.from_keypair(keypair1)

        one_time_hash, ephemeral_pub, _ = stealth1.generate_one_time_address()

        # Different recipient should not find the payment
        matches = StealthAddress.scan_for_payments(
            keypair2, ephemeral_pub, [one_time_hash]
        )
        self.assertEqual(matches, [])

    def test_key_recovery(self):
        keypair = StealthKeyPair.generate()
        stealth = StealthAddress.from_keypair(keypair)

        one_time_hash, ephemeral_pub, _ = stealth.generate_one_time_address()

        # Recover the private key
        one_time_priv, recovered_hash = StealthAddress.recover_one_time_privkey(
            keypair, ephemeral_pub
        )
        self.assertEqual(recovered_hash, one_time_hash)

    def test_encode_decode(self):
        keypair = StealthKeyPair.generate()
        stealth = StealthAddress.from_keypair(keypair)

        encoded = stealth.encode()
        decoded = StealthAddress.decode(encoded)

        self.assertEqual(
            stealth.scan_public.compressed_bytes(),
            decoded.scan_public.compressed_bytes(),
        )
        self.assertEqual(
            stealth.spend_public.compressed_bytes(),
            decoded.spend_public.compressed_bytes(),
        )


class TestPoSAndCheckpoints(unittest.TestCase):
    """Test PoS staking and checkpoint finality."""

    def test_validator_registration(self):
        pool = StakePool()
        priv = PrivateKey.generate()
        pub = priv.public_key

        success, msg = pool.add_validator(pub, params.MIN_STAKE_AMOUNT, 0)
        self.assertTrue(success)
        self.assertEqual(pool.total_stake, params.MIN_STAKE_AMOUNT)
        self.assertEqual(len(pool.active_validators), 1)

    def test_minimum_stake_enforced(self):
        pool = StakePool()
        priv = PrivateKey.generate()
        success, msg = pool.add_validator(priv.public_key, 100, 0)
        self.assertFalse(success)

    def test_checkpoint_finality(self):
        pool = StakePool()
        priv = PrivateKey.generate()
        pool.add_validator(priv.public_key, params.MIN_STAKE_AMOUNT, 0)

        mgr = CheckpointManager(pool)
        block_hash = double_sha256(b"block10")

        cp = mgr.create_checkpoint(10, block_hash)
        self.assertFalse(cp.is_finalized)

        success, msg = mgr.cast_vote(10, block_hash, priv)
        self.assertTrue(success)
        self.assertTrue(cp.is_finalized)
        self.assertTrue(mgr.is_finalized(10))
        self.assertTrue(mgr.is_finalized(5))
        self.assertFalse(mgr.is_finalized(15))

    def test_slashing(self):
        pool = StakePool()
        priv = PrivateKey.generate()
        pool.add_validator(priv.public_key, params.MIN_STAKE_AMOUNT, 0)

        pubkey_hash = priv.public_key.hash160()
        success, amount = pool.slash_validator(pubkey_hash)
        self.assertTrue(success)
        expected_slash = params.MIN_STAKE_AMOUNT * params.SLASH_PERCENTAGE // 100
        self.assertEqual(amount, expected_slash)

        # Slashed validator is inactive
        self.assertEqual(len(pool.active_validators), 0)


class TestEIP1559Fees(unittest.TestCase):
    """Test EIP-1559 fee mechanism."""

    def test_initial_base_fee(self):
        fm = FeeManager()
        self.assertEqual(fm.base_fee, params.INITIAL_BASE_FEE)

    def test_fee_increases_with_full_blocks(self):
        fm = FeeManager()
        initial = fm.base_fee
        # Simulate a full block (2x target size)
        fm.update_base_fee(params.TARGET_BLOCK_SIZE * 2)
        self.assertGreater(fm.base_fee, initial)

    def test_fee_decreases_with_empty_blocks(self):
        fm = FeeManager()
        initial = fm.base_fee
        # Simulate an empty block
        fm.update_base_fee(0)
        self.assertLess(fm.base_fee, initial)

    def test_minimum_fee(self):
        fm = FeeManager(initial_base_fee=params.MIN_BASE_FEE)
        fm.update_base_fee(0)
        self.assertGreaterEqual(fm.base_fee, params.MIN_BASE_FEE)

    def test_fee_breakdown(self):
        fm = FeeManager()
        breakdown = fm.calculate_fee(250, priority_fee_per_byte=10)
        self.assertEqual(
            breakdown.total_fee,
            breakdown.base_fee + breakdown.priority_fee,
        )
        self.assertEqual(
            breakdown.total_fee,
            breakdown.burned_amount + breakdown.miner_reward,
        )
        self.assertGreater(breakdown.burned_amount, 0)


class TestGovernance(unittest.TestCase):
    """Test on-chain governance."""

    def test_create_and_vote_proposal(self):
        pool = StakePool()
        priv = PrivateKey.generate()
        pool.add_validator(priv.public_key, params.MIN_STAKE_AMOUNT, 0)

        gov = GovernanceSystem(pool)
        pubkey_hash = priv.public_key.hash160()

        success, msg, proposal = gov.create_proposal(
            proposer_pubkey_hash=pubkey_hash,
            param_name="TARGET_BLOCK_SIZE",
            new_value=4_000_000,
            current_height=100,
        )
        self.assertTrue(success)
        self.assertIsNotNone(proposal)

        # Cast vote
        success, msg = gov.cast_vote(proposal.proposal_id, pubkey_hash, True)
        self.assertTrue(success)
        self.assertEqual(proposal.approval_percentage, 100.0)

    def test_proposal_execution(self):
        pool = StakePool()
        priv = PrivateKey.generate()
        pool.add_validator(priv.public_key, params.MIN_STAKE_AMOUNT, 0)

        gov = GovernanceSystem(pool)
        pubkey_hash = priv.public_key.hash160()

        success, _, proposal = gov.create_proposal(
            proposer_pubkey_hash=pubkey_hash,
            param_name="TARGET_BLOCK_SIZE",
            new_value=4_000_000,
            current_height=100,
        )
        gov.cast_vote(proposal.proposal_id, pubkey_hash, True)

        # Process after voting period ends
        changes = gov.process_proposals(100 + params.GOVERNANCE_VOTING_PERIOD)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0], ("TARGET_BLOCK_SIZE", params.TARGET_BLOCK_SIZE, 4_000_000))
        self.assertEqual(gov.get_param("TARGET_BLOCK_SIZE"), 4_000_000)

    def test_invalid_param_rejected(self):
        pool = StakePool()
        priv = PrivateKey.generate()
        pool.add_validator(priv.public_key, params.MIN_STAKE_AMOUNT, 0)

        gov = GovernanceSystem(pool)
        pubkey_hash = priv.public_key.hash160()

        success, msg, _ = gov.create_proposal(
            proposer_pubkey_hash=pubkey_hash,
            param_name="INVALID_PARAM",
            new_value=1,
            current_height=100,
        )
        self.assertFalse(success)


class TestDynamicBlockSize(unittest.TestCase):
    """Test dynamic block size."""

    def test_size_increases_when_full(self):
        full_sizes = [params.TARGET_BLOCK_SIZE * 2] * 10
        new_limit = Block.calculate_dynamic_size_limit(
            full_sizes, params.TARGET_BLOCK_SIZE
        )
        self.assertGreater(new_limit, params.TARGET_BLOCK_SIZE)

    def test_size_decreases_when_empty(self):
        empty_sizes = [100] * 10
        new_limit = Block.calculate_dynamic_size_limit(
            empty_sizes, params.TARGET_BLOCK_SIZE
        )
        self.assertLess(new_limit, params.TARGET_BLOCK_SIZE)

    def test_size_bounds(self):
        # Should not exceed MAX
        huge_sizes = [params.MAX_BLOCK_SIZE * 2] * 10
        new_limit = Block.calculate_dynamic_size_limit(
            huge_sizes, params.MAX_BLOCK_SIZE
        )
        self.assertLessEqual(new_limit, params.MAX_BLOCK_SIZE)


class TestNetwork(unittest.TestCase):
    """Test P2P networking."""

    def test_node_connection(self):
        n1 = Node("n1")
        n2 = Node("n2")
        n1.connect(n2)
        self.assertIn("n2", n1.peers)
        self.assertIn("n1", n2.peers)

    def test_block_sync(self):
        blockchain1 = Blockchain()
        wallet = Wallet()
        wallet.generate_key()
        miner = Miner(blockchain1, wallet.get_pubkey_hash())

        genesis = miner.mine_genesis_block()
        blockchain1.add_genesis_block(genesis)

        for _ in range(3):
            block = miner.mine_block()
            blockchain1.add_block(block)

        n1 = Node("n1", blockchain1)
        n2 = Node("n2")
        n1.connect(n2)

        synced = n2.sync_with_peer(n1)
        self.assertEqual(synced, 4)  # genesis + 3 blocks
        self.assertEqual(n2.height, n1.height)


class TestHybridConsensus(unittest.TestCase):
    """Test the full hybrid PoW/PoS flow."""

    def test_full_flow(self):
        blockchain = Blockchain()
        wallet = Wallet()
        wallet.generate_key()
        miner = Miner(blockchain, wallet.get_pubkey_hash())

        # Mine genesis
        genesis = miner.mine_genesis_block()
        blockchain.add_genesis_block(genesis)

        # Mine blocks
        for _ in range(9):
            block = miner.mine_block()
            success, msg = blockchain.add_block(block)
            self.assertTrue(success, msg)

        self.assertEqual(blockchain.height, 9)

        # Register validator
        validator_pub = wallet.keys[0].public_key
        success, msg = blockchain.consensus.register_validator(
            validator_pub, params.MIN_STAKE_AMOUNT, blockchain.height
        )
        self.assertTrue(success)

        # Mine to checkpoint (height 10)
        block = miner.mine_block()
        success, msg = blockchain.add_block(block)
        self.assertTrue(success, msg)

        # Create and finalize checkpoint
        cp = blockchain.consensus.checkpoint_mgr.create_checkpoint(
            10, blockchain.chain[10].hash()
        )
        success, msg = blockchain.consensus.vote_checkpoint(
            10, blockchain.chain[10].hash(), wallet.keys[0].private_key
        )
        self.assertTrue(success)
        self.assertTrue(blockchain.consensus.is_finalized(10))


if __name__ == "__main__":
    unittest.main()
