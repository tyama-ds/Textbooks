"""
BitAkita Persistent Storage.

Saves blockchain and wallet data to disk as JSON files so the node
can be stopped and restarted without losing state.

Directory layout:
    <data_dir>/
    ├── blocks/
    │   ├── 000000.json   # block at height 0 (genesis)
    │   ├── 000001.json   # block at height 1
    │   └── ...
    ├── chain_state.json  # UTXO set, fee state, consensus state
    └── wallets/
        └── <address>.json  # encrypted wallet key
"""

from __future__ import annotations

import json
import os
import struct
from pathlib import Path
from typing import Optional

from bitcoin.crypto.hash import double_sha256
from bitcoin.crypto.keys import PrivateKey
from bitcoin.script.script import Script, encode_varint, decode_varint
from bitakita.core.block import Block, BlockHeader
from bitakita.core.transaction import (
    Transaction, CoinbaseTransaction, TxInput, TxOutput, TxType,
)
from bitakita.core.blockchain import Blockchain, UTXO
from bitakita import params


class BlockStore:
    """
    Persists blocks and chain state to disk.

    Each block is stored as a separate JSON file for easy inspection.
    Chain state (UTXO set, fee manager, etc.) is saved as a snapshot.
    """

    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.blocks_dir = self.data_dir / "blocks"
        self.blocks_dir.mkdir(parents=True, exist_ok=True)

    # --- Block Serialization ---

    def _serialize_tx(self, tx: Transaction) -> dict:
        return {
            "version": tx.version,
            "tx_type": tx.tx_type,
            "inputs": [
                {
                    "prev_tx_hash": txin.prev_tx_hash.hex(),
                    "output_index": txin.output_index,
                    "script_sig": txin.script_sig.data.hex(),
                    "sequence": txin.sequence,
                }
                for txin in tx.inputs
            ],
            "outputs": [
                {
                    "amount": txout.amount,
                    "script_pubkey": txout.script_pubkey.data.hex(),
                }
                for txout in tx.outputs
            ],
            "locktime": tx.locktime,
            "extra_data": tx.extra_data.hex(),
        }

    def _deserialize_tx(self, data: dict) -> Transaction:
        inputs = [
            TxInput(
                prev_tx_hash=bytes.fromhex(inp["prev_tx_hash"]),
                output_index=inp["output_index"],
                script_sig=Script(bytes.fromhex(inp["script_sig"])),
                sequence=inp["sequence"],
            )
            for inp in data["inputs"]
        ]
        outputs = [
            TxOutput(
                amount=out["amount"],
                script_pubkey=Script(bytes.fromhex(out["script_pubkey"])),
            )
            for out in data["outputs"]
        ]
        return Transaction(
            inputs=inputs,
            outputs=outputs,
            version=data["version"],
            locktime=data["locktime"],
            tx_type=TxType(data["tx_type"]),
            extra_data=bytes.fromhex(data["extra_data"]),
        )

    def _serialize_block(self, block: Block) -> dict:
        h = block.header
        return {
            "header": {
                "version": h.version,
                "prev_block_hash": h.prev_block_hash.hex(),
                "merkle_root": h.merkle_root.hex(),
                "timestamp": h.timestamp,
                "bits": h.bits,
                "nonce": h.nonce,
                "base_fee": h.base_fee,
                "block_size_limit": h.block_size_limit,
            },
            "transactions": [self._serialize_tx(tx) for tx in block.transactions],
        }

    def _deserialize_block(self, data: dict) -> Block:
        hd = data["header"]
        header = BlockHeader(
            version=hd["version"],
            prev_block_hash=bytes.fromhex(hd["prev_block_hash"]),
            merkle_root=bytes.fromhex(hd["merkle_root"]),
            timestamp=hd["timestamp"],
            bits=hd["bits"],
            nonce=hd["nonce"],
            base_fee=hd["base_fee"],
            block_size_limit=hd["block_size_limit"],
        )
        transactions = [self._deserialize_tx(tx) for tx in data["transactions"]]
        return Block(header=header, transactions=transactions)

    # --- Save / Load ---

    def save_block(self, block: Block, height: int) -> None:
        """Save a single block to disk."""
        filename = self.blocks_dir / f"{height:06d}.json"
        data = self._serialize_block(block)
        with open(filename, "w") as f:
            json.dump(data, f, indent=2)

    def load_block(self, height: int) -> Optional[Block]:
        """Load a single block from disk."""
        filename = self.blocks_dir / f"{height:06d}.json"
        if not filename.exists():
            return None
        with open(filename) as f:
            data = json.load(f)
        return self._deserialize_block(data)

    def get_stored_height(self) -> int:
        """Get the highest block height stored on disk."""
        files = sorted(self.blocks_dir.glob("*.json"))
        if not files:
            return -1
        return int(files[-1].stem)

    def save_chain_state(self, blockchain: Blockchain) -> None:
        """Save chain state snapshot (UTXO set, fee state)."""
        state = {
            "height": len(blockchain.chain) - 1,
            "total_supply": blockchain.total_supply,
            "total_burned": blockchain.total_burned,
            "base_fee": blockchain.fee_manager.base_fee,
            "fee_total_burned": blockchain.fee_manager.total_burned,
        }
        state_file = self.data_dir / "chain_state.json"
        with open(state_file, "w") as f:
            json.dump(state, f, indent=2)

    def load_chain(self, blockchain: Blockchain) -> int:
        """
        Load the full chain from disk into a Blockchain instance.

        Returns the number of blocks loaded.
        """
        stored = self.get_stored_height()
        if stored < 0:
            return 0

        loaded = 0
        for h in range(stored + 1):
            block = self.load_block(h)
            if block is None:
                break
            if h == 0:
                if not blockchain.add_genesis_block(block):
                    break
            else:
                success, msg = blockchain.add_block(block)
                if not success:
                    print(f"  Warning: failed to load block {h}: {msg}")
                    break
            loaded += 1

        return loaded

    def save_full_chain(self, blockchain: Blockchain) -> int:
        """Save the entire chain to disk."""
        for i, block in enumerate(blockchain.chain):
            self.save_block(block, i)
        self.save_chain_state(blockchain)
        return len(blockchain.chain)


class WalletStore:
    """
    Persists wallet keys to disk.

    Keys are saved as hex strings. In production, these would be
    encrypted with a user password, but for educational purposes
    we keep them in plaintext.
    """

    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.wallets_dir = self.data_dir / "wallets"
        self.wallets_dir.mkdir(parents=True, exist_ok=True)

    def save_wallet(self, wallet) -> str:
        """Save wallet keys to a JSON file. Returns the filename."""
        from bitakita.wallet.wallet import Wallet

        keys_data = []
        for kp in wallet.keys:
            keys_data.append({
                "private_key": kp.private_key.hex(),
                "address": kp.address,
            })

        stealth_data = None
        if wallet.stealth_keypair:
            stealth_data = {
                "scan_private": wallet.stealth_keypair.scan_private.hex(),
                "spend_private": wallet.stealth_keypair.spend_private.hex(),
            }

        data = {
            "network": wallet.network,
            "keys": keys_data,
            "stealth": stealth_data,
        }

        address = wallet.get_address() if wallet.keys else "empty"
        filename = self.wallets_dir / f"{address}.json"
        with open(filename, "w") as f:
            json.dump(data, f, indent=2)
        return str(filename)

    def load_wallet(self, filepath: str):
        """Load a wallet from a JSON file."""
        from bitakita.wallet.wallet import Wallet
        from bitakita.crypto.stealth import StealthKeyPair, StealthAddress

        with open(filepath) as f:
            data = json.load(f)

        wallet = Wallet(network=data["network"])

        for key_data in data["keys"]:
            priv = PrivateKey.from_hex(key_data["private_key"])
            wallet.import_key(priv)

        if data.get("stealth"):
            sd = data["stealth"]
            scan_priv = PrivateKey.from_hex(sd["scan_private"])
            spend_priv = PrivateKey.from_hex(sd["spend_private"])
            wallet.stealth_keypair = StealthKeyPair(
                scan_private=scan_priv,
                scan_public=scan_priv.public_key,
                spend_private=spend_priv,
                spend_public=spend_priv.public_key,
            )
            wallet.stealth_address = StealthAddress.from_keypair(wallet.stealth_keypair)

        return wallet

    def list_wallets(self) -> list[str]:
        """List all wallet files."""
        return [str(f) for f in sorted(self.wallets_dir.glob("*.json"))]
