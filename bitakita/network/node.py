"""
BitAkita P2P Network Node.

Extends Bitcoin's simplified node with:
- Checkpoint propagation between validators
- Governance proposal broadcasting
- Stealth transaction scanning relay
"""

from __future__ import annotations

from typing import Optional, Callable

from bitakita.core.block import Block
from bitakita.core.blockchain import Blockchain
from bitakita.core.transaction import Transaction
from bitakita.consensus.checkpoint import Checkpoint


class Node:
    """A BitAkita network node."""

    def __init__(self, node_id: str, blockchain: Optional[Blockchain] = None):
        self.node_id = node_id
        self.blockchain = blockchain or Blockchain()
        self.peers: dict[str, Node] = {}
        self._on_block: Optional[Callable[[Block], None]] = None
        self._on_transaction: Optional[Callable[[Transaction], None]] = None
        self._on_checkpoint: Optional[Callable[[Checkpoint], None]] = None

    def connect(self, peer: Node) -> None:
        if peer.node_id == self.node_id:
            return
        if peer.node_id not in self.peers:
            self.peers[peer.node_id] = peer
        if self.node_id not in peer.peers:
            peer.peers[self.node_id] = self

    def disconnect(self, peer_id: str) -> None:
        if peer_id in self.peers:
            peer = self.peers.pop(peer_id)
            peer.peers.pop(self.node_id, None)

    def broadcast_block(self, block: Block) -> int:
        accepted = 0
        for peer in list(self.peers.values()):
            if peer.receive_block(block):
                accepted += 1
        return accepted

    def receive_block(self, block: Block) -> bool:
        if block.hash() in self.blockchain._block_index:
            return False

        if not self.blockchain.chain:
            if self.blockchain.add_genesis_block(block):
                if self._on_block:
                    self._on_block(block)
                self.broadcast_block(block)
                return True
            return False

        success, msg = self.blockchain.add_block(block)
        if success:
            if self._on_block:
                self._on_block(block)
            self.broadcast_block(block)
            return True
        return False

    def broadcast_transaction(self, tx: Transaction) -> int:
        accepted = 0
        for peer in list(self.peers.values()):
            if peer.receive_transaction(tx):
                accepted += 1
        return accepted

    def receive_transaction(self, tx: Transaction) -> bool:
        for mempool_tx in self.blockchain.mempool:
            if mempool_tx.txid() == tx.txid():
                return False

        success, msg = self.blockchain.add_to_mempool(tx)
        if success:
            if self._on_transaction:
                self._on_transaction(tx)
            self.broadcast_transaction(tx)
            return True
        return False

    def broadcast_checkpoint(self, checkpoint: Checkpoint) -> int:
        """Broadcast a finalized checkpoint to peers."""
        accepted = 0
        for peer in list(self.peers.values()):
            if peer.receive_checkpoint(checkpoint):
                accepted += 1
        return accepted

    def receive_checkpoint(self, checkpoint: Checkpoint) -> bool:
        """Receive a checkpoint from a peer."""
        height = checkpoint.block_height
        if height in self.blockchain.consensus.checkpoint_mgr.checkpoints:
            existing = self.blockchain.consensus.checkpoint_mgr.checkpoints[height]
            if existing.is_finalized:
                return False

        self.blockchain.consensus.checkpoint_mgr.checkpoints[height] = checkpoint
        if checkpoint.is_finalized:
            self.blockchain.consensus.checkpoint_mgr.finalized_height = max(
                self.blockchain.consensus.checkpoint_mgr.finalized_height,
                height,
            )
            if self._on_checkpoint:
                self._on_checkpoint(checkpoint)
            self.broadcast_checkpoint(checkpoint)
            return True
        return False

    def sync_with_peer(self, peer: Node) -> int:
        my_height = len(self.blockchain.chain)
        peer_height = len(peer.blockchain.chain)

        if peer_height <= my_height:
            return 0

        blocks_added = 0
        for i in range(my_height, peer_height):
            block = peer.blockchain.chain[i]
            if i == 0 and not self.blockchain.chain:
                self.blockchain.add_genesis_block(block)
                blocks_added += 1
            else:
                success, _ = self.blockchain.add_block(block)
                if success:
                    blocks_added += 1
                else:
                    break

        return blocks_added

    def on_block(self, callback: Callable[[Block], None]) -> None:
        self._on_block = callback

    def on_transaction(self, callback: Callable[[Transaction], None]) -> None:
        self._on_transaction = callback

    def on_checkpoint(self, callback: Callable[[Checkpoint], None]) -> None:
        self._on_checkpoint = callback

    @property
    def height(self) -> int:
        return self.blockchain.height

    def __repr__(self) -> str:
        return (
            f"Node(id={self.node_id}, height={self.height}, "
            f"peers={len(self.peers)})"
        )
