"""
BitAkita TCP P2P Node.

A real network node that communicates over TCP sockets.
This replaces the in-process simulation with actual network I/O.

Usage:
    node = TcpNode(blockchain, host="0.0.0.0", port=18333)
    node.start()           # Start listening + connecting
    node.connect_to("peer_host", 18333)  # Connect to a peer
    node.stop()            # Graceful shutdown
"""

from __future__ import annotations

import json
import socket
import threading
import time
import logging
from typing import Optional, Callable

from bitakita.core.block import Block, BlockHeader
from bitakita.core.blockchain import Blockchain
from bitakita.core.transaction import Transaction, TxInput, TxOutput, TxType
from bitakita.storage.store import BlockStore
from bitakita.network.protocol import (
    Message, Command, MAGIC,
    msg_version, msg_verack, msg_ping, msg_pong,
    msg_getblocks, msg_inv, msg_getdata, msg_block, msg_tx, msg_addr,
)
from bitcoin.script.script import Script


logger = logging.getLogger("bitakita.node")

DEFAULT_PORT = 18333


class PeerConnection:
    """Manages a single TCP connection to a peer."""

    def __init__(
        self,
        sock: socket.socket,
        address: tuple[str, int],
        node: TcpNode,
        inbound: bool = False,
    ):
        self.sock = sock
        self.address = address
        self.node = node
        self.inbound = inbound
        self.node_id: Optional[str] = None
        self.height: int = 0
        self.handshake_done = False
        self._running = False
        self._buffer = b""
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._thread.start()
        if not self.inbound:
            self._send_version()

    def stop(self) -> None:
        self._running = False
        try:
            self.sock.close()
        except OSError:
            pass

    def send(self, msg: Message) -> None:
        try:
            self.sock.sendall(msg.serialize())
        except OSError:
            self._running = False

    def _send_version(self) -> None:
        height = len(self.node.blockchain.chain) - 1
        self.send(msg_version(height, self.node.port, self.node.node_id))

    def _recv_loop(self) -> None:
        self.sock.settimeout(1.0)
        while self._running:
            try:
                data = self.sock.recv(65536)
                if not data:
                    break
                self._buffer += data
                self._process_buffer()
            except socket.timeout:
                continue
            except OSError:
                break

        self.node._remove_peer(self)

    def _process_buffer(self) -> None:
        while len(self._buffer) >= 24:
            try:
                msg, consumed = Message.deserialize(self._buffer)
                self._buffer = self._buffer[consumed:]
                self._handle_message(msg)
            except ValueError:
                break

    def _handle_message(self, msg: Message) -> None:
        handler = {
            Command.VERSION: self._on_version,
            Command.VERACK: self._on_verack,
            Command.PING: self._on_ping,
            Command.PONG: self._on_pong,
            Command.GETBLOCKS: self._on_getblocks,
            Command.INV: self._on_inv,
            Command.GETDATA: self._on_getdata,
            Command.BLOCK: self._on_block,
            Command.TX: self._on_tx,
            Command.ADDR: self._on_addr,
        }.get(msg.command)

        if handler:
            try:
                handler(msg.payload)
            except Exception as e:
                logger.error(f"Error handling {msg.command}: {e}")

    # --- Handshake ---

    def _on_version(self, payload: dict) -> None:
        self.node_id = payload.get("node_id", "unknown")
        self.height = payload.get("height", -1)
        self.send(msg_verack())
        if self.inbound:
            self._send_version()
        logger.info(f"Peer {self.address} version: id={self.node_id}, height={self.height}")

    def _on_verack(self, payload: dict) -> None:
        self.handshake_done = True
        logger.info(f"Handshake complete with {self.address}")
        # Request blocks if peer is ahead
        my_height = len(self.node.blockchain.chain)
        if self.height >= my_height:
            self.send(msg_getblocks(my_height))

    # --- Keepalive ---

    def _on_ping(self, payload: dict) -> None:
        self.send(msg_pong(payload.get("nonce", 0)))

    def _on_pong(self, payload: dict) -> None:
        pass

    # --- Block Sync ---

    def _on_getblocks(self, payload: dict) -> None:
        start = payload.get("start_height", 0)
        chain = self.node.blockchain.chain
        hashes = []
        for i in range(start, min(start + 500, len(chain))):
            hashes.append(chain[i].hash().hex())
        if hashes:
            self.send(msg_inv("block", hashes))

    def _on_inv(self, payload: dict) -> None:
        inv_type = payload.get("type", "")
        hashes = payload.get("hashes", [])
        if inv_type == "block":
            needed = [
                h for h in hashes
                if bytes.fromhex(h) not in self.node.blockchain._block_index
            ]
            if needed:
                self.send(msg_getdata("block", needed))
        elif inv_type == "tx":
            known = {tx.txid().hex() for tx in self.node.blockchain.mempool}
            needed = [h for h in hashes if h not in known]
            if needed:
                self.send(msg_getdata("tx", needed))

    def _on_getdata(self, payload: dict) -> None:
        inv_type = payload.get("type", "")
        hashes = payload.get("hashes", [])

        if inv_type == "block":
            for h_hex in hashes:
                h_bytes = bytes.fromhex(h_hex)
                if h_bytes in self.node.blockchain._block_index:
                    idx = self.node.blockchain._block_index[h_bytes]
                    block = self.node.blockchain.chain[idx]
                    block_data = self.node.block_store._serialize_block(block)
                    block_data["_height"] = idx
                    self.send(msg_block(block_data))
        elif inv_type == "tx":
            for h_hex in hashes:
                for tx in self.node.blockchain.mempool:
                    if tx.txid().hex() == h_hex:
                        tx_data = self.node.block_store._serialize_tx(tx)
                        self.send(msg_tx(tx_data))

    def _on_block(self, payload: dict) -> None:
        block = self.node.block_store._deserialize_block(payload)
        height_hint = payload.get("_height")

        if block.hash() in self.node.blockchain._block_index:
            return

        if not self.node.blockchain.chain:
            if self.node.blockchain.add_genesis_block(block):
                self.node.block_store.save_block(block, 0)
                logger.info(f"Genesis block received from {self.address}")
                self.node._broadcast_except(
                    msg_inv("block", [block.hash().hex()]), self
                )
        else:
            success, m = self.node.blockchain.add_block(block)
            if success:
                h = len(self.node.blockchain.chain) - 1
                self.node.block_store.save_block(block, h)
                self.node.block_store.save_chain_state(self.node.blockchain)
                logger.info(f"Block {h} received from {self.address}")
                self.node._broadcast_except(
                    msg_inv("block", [block.hash().hex()]), self
                )
                if self.node.on_block_callback:
                    self.node.on_block_callback(block)
            else:
                # Might be out of order, request more
                my_height = len(self.node.blockchain.chain)
                self.send(msg_getblocks(my_height))

    def _on_tx(self, payload: dict) -> None:
        tx = self.node.block_store._deserialize_tx(payload)
        success, m = self.node.blockchain.add_to_mempool(tx)
        if success:
            self.node._broadcast_except(
                msg_inv("tx", [tx.txid().hex()]), self
            )
            if self.node.on_tx_callback:
                self.node.on_tx_callback(tx)

    def _on_addr(self, payload: dict) -> None:
        for addr in payload.get("addresses", []):
            host, port = addr["host"], addr["port"]
            self.node.connect_to(host, port)


class TcpNode:
    """
    A full BitAkita node that communicates over TCP.

    This is the production-ready version that replaces the
    in-process Node class for real network deployment.
    """

    def __init__(
        self,
        blockchain: Blockchain,
        block_store: BlockStore,
        host: str = "0.0.0.0",
        port: int = DEFAULT_PORT,
        node_id: Optional[str] = None,
    ):
        self.blockchain = blockchain
        self.block_store = block_store
        self.host = host
        self.port = port
        self.node_id = node_id or f"node-{port}"
        self.peers: list[PeerConnection] = []
        self._lock = threading.Lock()
        self._running = False
        self._server_sock: Optional[socket.socket] = None
        self._accept_thread: Optional[threading.Thread] = None

        # Callbacks
        self.on_block_callback: Optional[Callable] = None
        self.on_tx_callback: Optional[Callable] = None

    def start(self) -> None:
        """Start listening for incoming connections."""
        self._running = True
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.settimeout(1.0)
        self._server_sock.bind((self.host, self.port))
        self._server_sock.listen(16)

        self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._accept_thread.start()
        logger.info(f"Node {self.node_id} listening on {self.host}:{self.port}")

    def stop(self) -> None:
        """Gracefully shut down the node."""
        self._running = False
        with self._lock:
            for peer in self.peers:
                peer.stop()
            self.peers.clear()
        if self._server_sock:
            try:
                self._server_sock.close()
            except OSError:
                pass
        # Save state
        self.block_store.save_chain_state(self.blockchain)
        logger.info(f"Node {self.node_id} stopped")

    def connect_to(self, host: str, port: int) -> bool:
        """Connect to a remote peer."""
        addr = (host, port)
        with self._lock:
            for p in self.peers:
                if p.address == addr:
                    return False

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            sock.connect(addr)
            sock.settimeout(None)
            peer = PeerConnection(sock, addr, self, inbound=False)
            with self._lock:
                self.peers.append(peer)
            peer.start()
            logger.info(f"Connected to {host}:{port}")
            return True
        except OSError as e:
            logger.warning(f"Failed to connect to {host}:{port}: {e}")
            return False

    def broadcast_block(self, block: Block) -> None:
        """Broadcast a newly mined block to all peers."""
        block_hash = block.hash().hex()
        msg = msg_inv("block", [block_hash])
        with self._lock:
            for peer in self.peers:
                peer.send(msg)

    def broadcast_transaction(self, tx: Transaction) -> None:
        """Broadcast a transaction to all peers."""
        tx_hash = tx.txid().hex()
        msg = msg_inv("tx", [tx_hash])
        with self._lock:
            for peer in self.peers:
                peer.send(msg)

    @property
    def peer_count(self) -> int:
        with self._lock:
            return len(self.peers)

    # --- Internal ---

    def _accept_loop(self) -> None:
        while self._running:
            try:
                sock, addr = self._server_sock.accept()
                peer = PeerConnection(sock, addr, self, inbound=True)
                with self._lock:
                    self.peers.append(peer)
                peer.start()
                logger.info(f"Inbound connection from {addr}")
            except socket.timeout:
                continue
            except OSError:
                break

    def _remove_peer(self, peer: PeerConnection) -> None:
        with self._lock:
            if peer in self.peers:
                self.peers.remove(peer)
                logger.info(f"Peer {peer.address} disconnected")

    def _broadcast_except(self, msg: Message, exclude: PeerConnection) -> None:
        with self._lock:
            for peer in self.peers:
                if peer is not exclude:
                    peer.send(msg)
