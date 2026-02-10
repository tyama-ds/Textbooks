"""
BitAkita Transaction Model.

Extends Bitcoin's UTXO transaction model with:
- Stake/Unstake transactions for PoS participation
- Governance vote transactions
- Stealth address metadata (ephemeral pubkey in OP_RETURN)
- Fee burn tracking
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional

from bitcoin.crypto.hash import double_sha256
from bitcoin.script.script import Script, OpCode, encode_varint


class TxType(IntEnum):
    """Transaction types in BitAkita."""
    REGULAR = 0
    COINBASE = 1
    STAKE = 2          # Lock coins as PoS stake
    UNSTAKE = 3        # Withdraw PoS stake
    GOVERNANCE = 4     # Governance vote


@dataclass
class TxInput:
    """A transaction input referencing a previous output."""
    prev_tx_hash: bytes
    output_index: int
    script_sig: Script = field(default_factory=Script)
    sequence: int = 0xFFFFFFFF

    def serialize(self) -> bytes:
        result = self.prev_tx_hash[::-1]
        result += struct.pack("<I", self.output_index)
        result += self.script_sig.serialize()
        result += struct.pack("<I", self.sequence)
        return result

    def is_coinbase(self) -> bool:
        return self.prev_tx_hash == b"\x00" * 32 and self.output_index == 0xFFFFFFFF


@dataclass
class TxOutput:
    """A transaction output with amount and locking script."""
    amount: int
    script_pubkey: Script = field(default_factory=Script)

    def serialize(self) -> bytes:
        result = struct.pack("<q", self.amount)
        result += self.script_pubkey.serialize()
        return result


class Transaction:
    """
    A BitAkita transaction.

    Supports multiple transaction types beyond simple value transfer.
    """

    def __init__(
        self,
        inputs: Optional[list[TxInput]] = None,
        outputs: Optional[list[TxOutput]] = None,
        version: int = 2,
        locktime: int = 0,
        tx_type: TxType = TxType.REGULAR,
        extra_data: bytes = b"",
    ):
        self.version = version
        self.inputs = inputs or []
        self.outputs = outputs or []
        self.locktime = locktime
        self.tx_type = tx_type
        self.extra_data = extra_data  # For governance votes, stealth metadata, etc.

    def serialize(self) -> bytes:
        result = struct.pack("<I", self.version)
        result += struct.pack("<B", self.tx_type)
        result += encode_varint(len(self.inputs))
        for txin in self.inputs:
            result += txin.serialize()
        result += encode_varint(len(self.outputs))
        for txout in self.outputs:
            result += txout.serialize()
        result += struct.pack("<I", self.locktime)
        if self.extra_data:
            result += encode_varint(len(self.extra_data))
            result += self.extra_data
        else:
            result += encode_varint(0)
        return result

    def txid(self) -> bytes:
        return double_sha256(self.serialize())

    def txid_hex(self) -> str:
        return self.txid()[::-1].hex()

    def size(self) -> int:
        """Transaction size in bytes."""
        return len(self.serialize())

    def hash_for_signing(self, input_index: int, script_pubkey: Script, hash_type: int = 1) -> bytes:
        """Compute the hash to be signed for a specific input (SIGHASH_ALL)."""
        tx_copy = Transaction(
            version=self.version,
            locktime=self.locktime,
            tx_type=self.tx_type,
            extra_data=self.extra_data,
        )
        for i, txin in enumerate(self.inputs):
            sig_script = script_pubkey if i == input_index else Script()
            tx_copy.inputs.append(
                TxInput(
                    prev_tx_hash=txin.prev_tx_hash,
                    output_index=txin.output_index,
                    script_sig=sig_script,
                    sequence=txin.sequence,
                )
            )
        tx_copy.outputs = self.outputs[:]

        serialized = tx_copy.serialize()
        serialized += struct.pack("<I", hash_type)
        return double_sha256(serialized)

    def __repr__(self) -> str:
        return (
            f"Transaction(type={self.tx_type.name}, txid={self.txid_hex()[:16]}..., "
            f"ins={len(self.inputs)}, outs={len(self.outputs)})"
        )


class CoinbaseTransaction(Transaction):
    """Coinbase transaction creating new BITA."""

    def __init__(
        self,
        block_height: int,
        reward: int,
        recipient_pubkey_hash: bytes,
        message: bytes = b"",
        stake_rewards: Optional[dict[bytes, int]] = None,
    ):
        height_bytes = block_height.to_bytes(
            (block_height.bit_length() + 7) // 8 if block_height > 0 else 1,
            "little",
        )
        coinbase_script_data = bytes([len(height_bytes)]) + height_bytes + message

        coinbase_input = TxInput(
            prev_tx_hash=b"\x00" * 32,
            output_index=0xFFFFFFFF,
            script_sig=Script(coinbase_script_data),
        )

        outputs = [
            TxOutput(
                amount=reward,
                script_pubkey=Script.p2pkh_locking(recipient_pubkey_hash),
            )
        ]

        # Add staking reward outputs
        if stake_rewards:
            for pubkey_hash, reward_amount in stake_rewards.items():
                if reward_amount > 0:
                    outputs.append(
                        TxOutput(
                            amount=reward_amount,
                            script_pubkey=Script.p2pkh_locking(pubkey_hash),
                        )
                    )

        super().__init__(
            inputs=[coinbase_input],
            outputs=outputs,
            tx_type=TxType.COINBASE,
        )
        self.block_height = block_height


class StakeTransaction(Transaction):
    """
    A staking transaction that locks BITA as PoS stake.

    The staked amount is sent to a special stake output that can only
    be spent after the lock period via an UnstakeTransaction.
    """

    def __init__(
        self,
        inputs: list[TxInput],
        stake_amount: int,
        staker_pubkey_hash: bytes,
        change_amount: int = 0,
        change_pubkey_hash: Optional[bytes] = None,
    ):
        outputs = [
            TxOutput(
                amount=stake_amount,
                script_pubkey=Script.p2pkh_locking(staker_pubkey_hash),
            )
        ]
        if change_amount > 0 and change_pubkey_hash:
            outputs.append(
                TxOutput(
                    amount=change_amount,
                    script_pubkey=Script.p2pkh_locking(change_pubkey_hash),
                )
            )

        # Store staker info in extra_data
        extra = staker_pubkey_hash + stake_amount.to_bytes(8, "big")

        super().__init__(
            inputs=inputs,
            outputs=outputs,
            tx_type=TxType.STAKE,
            extra_data=extra,
        )
        self.stake_amount = stake_amount
        self.staker_pubkey_hash = staker_pubkey_hash
