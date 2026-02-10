"""
Bitcoin Transaction Model.

Bitcoin uses an Unspent Transaction Output (UTXO) model:
- Each transaction consumes previous outputs (inputs) and creates new outputs.
- An output specifies an amount and a locking script (scriptPubKey).
- An input references a previous output and provides an unlocking script (scriptSig).
- A transaction's ID (txid) is the double-SHA256 of its serialized form.

Special case: Coinbase transactions have no real inputs and create new coins (block reward).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Optional

from bitcoin.crypto.hash import double_sha256
from bitcoin.script.script import Script, encode_varint, decode_varint


@dataclass
class TxInput:
    """
    A transaction input that references a previous output.

    Attributes:
        prev_tx_hash: Hash of the transaction containing the output being spent (32 bytes)
        output_index: Index of the output in the previous transaction
        script_sig: Unlocking script proving the spender's authorization
        sequence: Sequence number (0xFFFFFFFF by default)
    """

    prev_tx_hash: bytes
    output_index: int
    script_sig: Script = field(default_factory=Script)
    sequence: int = 0xFFFFFFFF

    def serialize(self) -> bytes:
        """Serialize this input to bytes."""
        result = self.prev_tx_hash[::-1]  # Little-endian tx hash
        result += struct.pack("<I", self.output_index)
        result += self.script_sig.serialize()
        result += struct.pack("<I", self.sequence)
        return result

    def is_coinbase(self) -> bool:
        """Check if this is a coinbase input (all zeros prev_tx_hash)."""
        return self.prev_tx_hash == b"\x00" * 32 and self.output_index == 0xFFFFFFFF


@dataclass
class TxOutput:
    """
    A transaction output specifying an amount and spending condition.

    Attributes:
        amount: Value in satoshis (1 BTC = 100,000,000 satoshis)
        script_pubkey: Locking script defining who can spend this output
    """

    amount: int  # In satoshis
    script_pubkey: Script = field(default_factory=Script)

    def serialize(self) -> bytes:
        """Serialize this output to bytes."""
        result = struct.pack("<q", self.amount)
        result += self.script_pubkey.serialize()
        return result


class Transaction:
    """
    A Bitcoin transaction.

    A transaction moves value from inputs to outputs. The sum of input values
    must be >= the sum of output values. The difference is the transaction fee
    collected by the miner.
    """

    def __init__(
        self,
        inputs: Optional[list[TxInput]] = None,
        outputs: Optional[list[TxOutput]] = None,
        version: int = 1,
        locktime: int = 0,
    ):
        self.version = version
        self.inputs = inputs or []
        self.outputs = outputs or []
        self.locktime = locktime

    def serialize(self) -> bytes:
        """Serialize the transaction to bytes (for hashing and transmission)."""
        result = struct.pack("<I", self.version)
        result += encode_varint(len(self.inputs))
        for txin in self.inputs:
            result += txin.serialize()
        result += encode_varint(len(self.outputs))
        for txout in self.outputs:
            result += txout.serialize()
        result += struct.pack("<I", self.locktime)
        return result

    def txid(self) -> bytes:
        """
        Compute the transaction ID (double SHA-256 of serialized tx).

        The txid is displayed in reverse byte order by convention.
        """
        return double_sha256(self.serialize())

    def txid_hex(self) -> str:
        """Return the txid as a hex string in display order (reversed)."""
        return self.txid()[::-1].hex()

    def hash_for_signing(self, input_index: int, script_pubkey: Script, hash_type: int = 1) -> bytes:
        """
        Compute the hash to be signed for a specific input.

        This implements simplified SIGHASH_ALL:
        1. Copy the transaction
        2. Clear all input scripts
        3. Set the script of the input being signed to the referenced output's scriptPubKey
        4. Serialize and double-SHA256

        Args:
            input_index: Index of the input being signed
            script_pubkey: The scriptPubKey of the output being spent
            hash_type: SIGHASH type (1 = SIGHASH_ALL)
        """
        # Create a copy with cleared scripts
        tx_copy = Transaction(version=self.version, locktime=self.locktime)
        for i, txin in enumerate(self.inputs):
            if i == input_index:
                new_script = script_pubkey
            else:
                new_script = Script()
            tx_copy.inputs.append(
                TxInput(
                    prev_tx_hash=txin.prev_tx_hash,
                    output_index=txin.output_index,
                    script_sig=new_script,
                    sequence=txin.sequence,
                )
            )
        tx_copy.outputs = self.outputs[:]

        serialized = tx_copy.serialize()
        serialized += struct.pack("<I", hash_type)
        return double_sha256(serialized)

    def __repr__(self) -> str:
        return (
            f"Transaction(txid={self.txid_hex()[:16]}..., "
            f"inputs={len(self.inputs)}, outputs={len(self.outputs)})"
        )


class CoinbaseTransaction(Transaction):
    """
    A coinbase transaction - the first transaction in every block.

    Coinbase transactions:
    - Have exactly one input with prev_tx_hash = 0x00*32 and output_index = 0xFFFFFFFF
    - The input scriptSig can contain arbitrary data (e.g., block height, miner message)
    - Create new bitcoins (the block reward + collected fees)
    """

    def __init__(
        self,
        block_height: int,
        reward: int,
        recipient_pubkey_hash: bytes,
        message: bytes = b"",
    ):
        # Build coinbase script: block height + optional message
        height_bytes = block_height.to_bytes(
            (block_height.bit_length() + 7) // 8 if block_height > 0 else 1,
            "little",
        )
        coinbase_script_data = (
            bytes([len(height_bytes)]) + height_bytes + message
        )

        coinbase_input = TxInput(
            prev_tx_hash=b"\x00" * 32,
            output_index=0xFFFFFFFF,
            script_sig=Script(coinbase_script_data),
        )

        reward_output = TxOutput(
            amount=reward,
            script_pubkey=Script.p2pkh_locking(recipient_pubkey_hash),
        )

        super().__init__(inputs=[coinbase_input], outputs=[reward_output])
        self.block_height = block_height
