#!/usr/bin/env python3
"""
bitakitad - BitAkita Daemon

常駐プロセスとしてノードを起動する。
ブロックチェーンをディスクに保存し、TCP で他のノードと通信する。
RPC サーバーで bitakita-cli からの操作を受け付ける。

使い方:
    python bitakitad.py --port 18333 --data-dir ./data --mine
    python bitakitad.py --port 18334 --data-dir ./data2 --connect 127.0.0.1:18333
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bitakita.core.blockchain import Blockchain
from bitakita.core.block import Block
from bitakita.core.transaction import Transaction
from bitakita.wallet.wallet import Wallet
from bitakita.mining.miner import Miner
from bitakita.storage.store import BlockStore, WalletStore
from bitakita.network.tcp_node import TcpNode
from bitakita import params

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("bitakitad")


class RpcServer:
    """
    Simple JSON-RPC server for bitakita-cli to communicate with the daemon.

    Listens on localhost only (not exposed to network).
    """

    def __init__(self, daemon: BitAkitaDaemon, port: int):
        self.daemon = daemon
        self.port = port
        self._running = False
        self._sock: socket.socket = None
        self._thread: threading.Thread = None

    def start(self) -> None:
        self._running = True
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.settimeout(1.0)
        self._sock.bind(("127.0.0.1", self.port))
        self._sock.listen(4)
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()
        logger.info(f"RPC server on 127.0.0.1:{self.port}")

    def stop(self) -> None:
        self._running = False
        if self._sock:
            self._sock.close()

    def _accept_loop(self) -> None:
        while self._running:
            try:
                conn, addr = self._sock.accept()
                threading.Thread(
                    target=self._handle, args=(conn,), daemon=True
                ).start()
            except socket.timeout:
                continue
            except OSError:
                break

    def _handle(self, conn: socket.socket) -> None:
        try:
            data = b""
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
                if b"\n" in data:
                    break

            if not data:
                return

            request = json.loads(data.decode())
            method = request.get("method", "")
            p = request.get("params", {})

            result = self._dispatch(method, p)
            response = json.dumps({"result": result, "error": None}) + "\n"
            conn.sendall(response.encode())
        except Exception as e:
            try:
                err = json.dumps({"result": None, "error": str(e)}) + "\n"
                conn.sendall(err.encode())
            except OSError:
                pass
        finally:
            conn.close()

    def _dispatch(self, method: str, p: dict) -> dict:
        d = self.daemon
        bc = d.blockchain

        if method == "getinfo":
            return {
                "height": bc.height,
                "peers": d.node.peer_count,
                "mempool": len(bc.mempool),
                "utxo_count": len(bc.utxo_set),
                "total_supply": bc.total_supply,
                "total_burned": bc.total_burned,
                "circulating": bc.circulating_supply,
                "base_fee": bc.fee_manager.base_fee,
                "mining": d.mining,
                "validators": bc.consensus.validator_count,
                "finalized_height": bc.consensus.finalized_height,
            }

        elif method == "getbalance":
            balance = d.wallet.get_balance(bc)
            spendable = d.wallet.get_spendable_balance(bc)
            return {
                "balance": balance,
                "spendable": spendable,
                "balance_bita": balance / 1_0000_0000,
                "spendable_bita": spendable / 1_0000_0000,
            }

        elif method == "getaddress":
            return {
                "address": d.wallet.get_address(),
                "all_addresses": d.wallet.get_all_addresses(),
            }

        elif method == "newaddress":
            kp = d.wallet.generate_key()
            d.wallet_store.save_wallet(d.wallet)
            return {"address": kp.address}

        elif method == "send":
            to = p["to"]
            amount = int(p["amount"])
            tx = d.wallet.create_transaction(bc, to, amount)
            success, msg = bc.add_to_mempool(tx)
            if success:
                d.node.broadcast_transaction(tx)
            return {"success": success, "message": msg, "txid": tx.txid_hex()}

        elif method == "getblock":
            height = int(p.get("height", bc.height))
            if 0 <= height < len(bc.chain):
                block = bc.chain[height]
                return {
                    "height": height,
                    "hash": block.hash_hex(),
                    "prev_hash": block.header.prev_block_hash.hex(),
                    "timestamp": block.header.timestamp,
                    "nonce": block.header.nonce,
                    "tx_count": len(block.transactions),
                    "size": block.block_size(),
                    "base_fee": block.header.base_fee,
                }
            return {"error": "Block not found"}

        elif method == "getmempool":
            txs = []
            for tx in bc.mempool:
                txs.append({
                    "txid": tx.txid_hex(),
                    "size": tx.size(),
                    "inputs": len(tx.inputs),
                    "outputs": len(tx.outputs),
                })
            return {"count": len(txs), "transactions": txs}

        elif method == "mine":
            count = int(p.get("count", 1))
            mined = 0
            for _ in range(count):
                block = d.miner.mine_block()
                if block:
                    success, msg = bc.add_block(block)
                    if success:
                        h = len(bc.chain) - 1
                        d.block_store.save_block(block, h)
                        d.block_store.save_chain_state(bc)
                        d.node.broadcast_block(block)
                        mined += 1
            return {"mined": mined, "height": bc.height}

        elif method == "startmining":
            d.start_mining()
            return {"mining": True}

        elif method == "stopmining":
            d.stop_mining()
            return {"mining": False}

        elif method == "connect":
            host = p["host"]
            port = int(p["port"])
            ok = d.node.connect_to(host, port)
            return {"connected": ok, "peer": f"{host}:{port}"}

        elif method == "getpeers":
            peers = []
            for peer in d.node.peers:
                peers.append({
                    "address": f"{peer.address[0]}:{peer.address[1]}",
                    "node_id": peer.node_id,
                    "height": peer.height,
                    "inbound": peer.inbound,
                })
            return {"count": len(peers), "peers": peers}

        elif method == "getutxos":
            utxos = d.wallet.get_utxos(bc)
            items = []
            for u in utxos:
                items.append({
                    "txid": u.tx_hash[::-1].hex(),
                    "index": u.output_index,
                    "amount": u.output.amount,
                    "amount_bita": u.output.amount / 1_0000_0000,
                    "block_height": u.block_height,
                })
            return {"count": len(items), "utxos": items}

        else:
            raise ValueError(f"Unknown method: {method}")


class BitAkitaDaemon:
    """The main BitAkita daemon process."""

    def __init__(self, args):
        self.data_dir = args.data_dir
        self.p2p_port = args.port
        self.rpc_port = args.rpc_port
        self.connect_peers = args.connect or []
        self.mining = False
        self._mine_thread: threading.Thread = None
        self._running = False

        # Initialize components
        self.block_store = BlockStore(self.data_dir)
        self.wallet_store = WalletStore(self.data_dir)
        self.blockchain = Blockchain()

        # Load or create wallet
        wallet_files = self.wallet_store.list_wallets()
        if wallet_files:
            self.wallet = self.wallet_store.load_wallet(wallet_files[0])
            logger.info(f"Wallet loaded: {self.wallet.get_address()}")
        else:
            self.wallet = Wallet()
            self.wallet.generate_key()
            self.wallet_store.save_wallet(self.wallet)
            logger.info(f"New wallet created: {self.wallet.get_address()}")

        # Load chain from disk
        loaded = self.block_store.load_chain(self.blockchain)
        if loaded > 0:
            logger.info(f"Loaded {loaded} blocks from disk (height={self.blockchain.height})")
        else:
            logger.info("No existing chain found, starting fresh")

        # Miner
        self.miner = Miner(self.blockchain, self.wallet.get_pubkey_hash())

        # TCP Node
        self.node = TcpNode(
            self.blockchain,
            self.block_store,
            host="0.0.0.0",
            port=self.p2p_port,
            node_id=f"node-{self.p2p_port}",
        )
        self.node.on_block_callback = self._on_new_block

        # RPC Server
        self.rpc = RpcServer(self, self.rpc_port)

    def start(self) -> None:
        self._running = True

        # Start P2P node
        self.node.start()

        # Start RPC server
        self.rpc.start()

        # Connect to initial peers
        for peer_str in self.connect_peers:
            host, port = peer_str.split(":")
            self.node.connect_to(host, int(port))

        logger.info(
            f"BitAkita daemon started\n"
            f"  P2P port:  {self.p2p_port}\n"
            f"  RPC port:  {self.rpc_port}\n"
            f"  Data dir:  {self.data_dir}\n"
            f"  Address:   {self.wallet.get_address()}\n"
            f"  Height:    {self.blockchain.height}"
        )

    def stop(self) -> None:
        self._running = False
        self.stop_mining()
        self.node.stop()
        self.rpc.stop()
        self.block_store.save_chain_state(self.blockchain)
        self.wallet_store.save_wallet(self.wallet)
        logger.info("Daemon stopped. Data saved to disk.")

    def start_mining(self) -> None:
        if self.mining:
            return
        self.mining = True
        self._mine_thread = threading.Thread(target=self._mining_loop, daemon=True)
        self._mine_thread.start()
        logger.info("Mining started")

    def stop_mining(self) -> None:
        self.mining = False
        logger.info("Mining stopped")

    def _mining_loop(self) -> None:
        while self.mining and self._running:
            block = self.miner.mine_block()
            if block:
                success, msg = self.blockchain.add_block(block)
                if success:
                    h = len(self.blockchain.chain) - 1
                    self.block_store.save_block(block, h)
                    self.block_store.save_chain_state(self.blockchain)
                    self.node.broadcast_block(block)
                    balance = self.wallet.get_balance(self.blockchain)
                    logger.info(
                        f"Mined block {h} | "
                        f"Balance: {balance / 1_0000_0000:.2f} BITA"
                    )
            # Small delay to prevent 100% CPU
            time.sleep(0.01)

    def _on_new_block(self, block: Block) -> None:
        """Called when a new block is received from the network."""
        h = self.blockchain.height
        logger.info(f"New block {h} from network | hash={block.hash_hex()[:16]}...")


    def mine_genesis_if_needed(self) -> None:
        """Mine genesis block if chain is empty and no peers."""
        if self.blockchain.chain:
            return
        if self.connect_peers:
            # Will sync from peers instead
            return
        logger.info("Mining genesis block...")
        genesis = self.miner.mine_genesis_block()
        self.blockchain.add_genesis_block(genesis)
        self.block_store.save_block(genesis, 0)
        self.block_store.save_chain_state(self.blockchain)
        logger.info(f"Genesis block mined: {genesis.hash_hex()[:32]}...")


def main():
    parser = argparse.ArgumentParser(description="BitAkita Daemon")
    parser.add_argument("--port", type=int, default=18333, help="P2P listen port")
    parser.add_argument("--rpc-port", type=int, default=18332, help="RPC listen port")
    parser.add_argument("--data-dir", default="./bitakita-data", help="Data directory")
    parser.add_argument("--connect", nargs="*", help="Peers to connect to (host:port)")
    parser.add_argument("--mine", action="store_true", help="Start mining immediately")
    args = parser.parse_args()

    daemon = BitAkitaDaemon(args)
    daemon.mine_genesis_if_needed()
    daemon.start()

    if args.mine:
        daemon.start_mining()

    # Handle Ctrl+C
    def signal_handler(sig, frame):
        print("\nShutting down...")
        daemon.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Keep main thread alive
    print("BitAkita daemon running. Press Ctrl+C to stop.")
    while daemon._running:
        try:
            time.sleep(1)
        except KeyboardInterrupt:
            break

    daemon.stop()


if __name__ == "__main__":
    main()
