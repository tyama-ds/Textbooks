"""
Simplified Bitcoin P2P Network Node.

In the real Bitcoin network, nodes communicate over TCP using a binary protocol.
This is a simplified in-process simulation that demonstrates the key concepts:
- Peer discovery and connection
- Block propagation
- Transaction broadcasting
- Chain synchronization (longest chain rule)

This implementation uses direct method calls instead of network sockets,
making it suitable for educational purposes and local simulation.
"""

from __future__ import annotations

import time
from typing import Optional, Callable
from dataclasses import dataclass, field

from bitcoin.core.block import Block
from bitcoin.core.blockchain import Blockchain
from bitcoin.core.transaction import Transaction


@dataclass
class PeerInfo:
    """Information about a connected peer."""
    node_id: str
    height: int = 0


class Node:
    """
    A simplified Bitcoin network node.

    Each node maintains its own blockchain and communicates
    with peers to stay synchronized.
    """

    def __init__(self, node_id: str, blockchain: Optional[Blockchain] = None):
        self.node_id = node_id
        self.blockchain = blockchain or Blockchain()
        self.peers: dict[str, Node] = {}
        self._on_block: Optional[Callable[[Block], None]] = None
        self._on_transaction: Optional[Callable[[Transaction], None]] = None

    def connect(self, peer: Node) -> None:
        """Establish a bidirectional connection with a peer."""
        if peer.node_id == self.node_id:
            return
        if peer.node_id not in self.peers:
            self.peers[peer.node_id] = peer
        if self.node_id not in peer.peers:
            peer.peers[self.node_id] = self

    def disconnect(self, peer_id: str) -> None:
        """Disconnect from a peer."""
        if peer_id in self.peers:
            peer = self.peers.pop(peer_id)
            peer.peers.pop(self.node_id, None)

    def broadcast_block(self, block: Block) -> int:
        """
        Broadcast a new block to all connected peers.

        Returns the number of peers that accepted the block.
        """
        accepted = 0
        for peer in list(self.peers.values()):
            success = peer.receive_block(block)
            if success:
                accepted += 1
        return accepted

    def receive_block(self, block: Block) -> bool:
        """
        Receive a block from a peer.

        Validates and adds to the chain if valid.
        """
        # Check if we already have this block
        if block.hash() in self.blockchain._block_index:
            return False

        # If this is a genesis block
        if not self.blockchain.chain:
            if self.blockchain.add_genesis_block(block):
                if self._on_block:
                    self._on_block(block)
                self.broadcast_block(block)
                return True
            return False

        # Try to add the block
        success, msg = self.blockchain.add_block(block)
        if success:
            if self._on_block:
                self._on_block(block)
            # Relay to other peers
            self.broadcast_block(block)
            return True
        return False

    def broadcast_transaction(self, tx: Transaction) -> int:
        """
        Broadcast a transaction to all connected peers.

        Returns the number of peers that accepted the transaction.
        """
        accepted = 0
        for peer in list(self.peers.values()):
            success = peer.receive_transaction(tx)
            if success:
                accepted += 1
        return accepted

    def receive_transaction(self, tx: Transaction) -> bool:
        """
        Receive a transaction from a peer.

        Validates and adds to mempool if valid.
        """
        # Check if we already have this transaction
        for mempool_tx in self.blockchain.mempool:
            if mempool_tx.txid() == tx.txid():
                return False

        success, msg = self.blockchain.add_to_mempool(tx)
        if success:
            if self._on_transaction:
                self._on_transaction(tx)
            # Relay to other peers
            self.broadcast_transaction(tx)
            return True
        return False

    def sync_with_peer(self, peer: Node) -> int:
        """
        Synchronize blockchain with a peer (download missing blocks).

        Implements a simplified version of the Bitcoin sync protocol.
        Returns the number of blocks downloaded.
        """
        my_height = len(self.blockchain.chain)
        peer_height = len(peer.blockchain.chain)

        if peer_height <= my_height:
            return 0

        blocks_added = 0

        # Find common ancestor (simplified: check from our tip)
        start_index = my_height
        if my_height > 0:
            # Verify our chains match up to our height
            for i in range(min(my_height, peer_height)):
                if self.blockchain.chain[i].hash() != peer.blockchain.chain[i].hash():
                    # Fork detected - in a real implementation, we'd handle reorgs
                    start_index = i
                    break

        # Download blocks from peer
        for i in range(start_index, peer_height):
            block = peer.blockchain.chain[i]
            if i == 0 and not self.blockchain.chain:
                self.blockchain.add_genesis_block(block)
                blocks_added += 1
            else:
                success, msg = self.blockchain.add_block(block)
                if success:
                    blocks_added += 1
                else:
                    break

        return blocks_added

    def on_block(self, callback: Callable[[Block], None]) -> None:
        """Register a callback for when a new block is received."""
        self._on_block = callback

    def on_transaction(self, callback: Callable[[Transaction], None]) -> None:
        """Register a callback for when a new transaction is received."""
        self._on_transaction = callback

    @property
    def height(self) -> int:
        return self.blockchain.height

    @property
    def peer_count(self) -> int:
        return len(self.peers)

    def __repr__(self) -> str:
        return (
            f"Node(id={self.node_id}, height={self.height}, "
            f"peers={self.peer_count})"
        )
