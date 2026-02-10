"""
Bitcoin Script - a simple stack-based scripting language.

Bitcoin uses Script to define the conditions under which funds can be spent.
The most common script type is Pay-to-Public-Key-Hash (P2PKH):

ScriptPubKey (locking): OP_DUP OP_HASH160 <pubkey_hash> OP_EQUALVERIFY OP_CHECKSIG
ScriptSig (unlocking):  <signature> <pubkey>

This implementation supports a subset of Bitcoin opcodes sufficient for P2PKH.
"""

from __future__ import annotations

import struct
from enum import IntEnum
from typing import Optional

from bitcoin.crypto.hash import hash160, double_sha256
from bitcoin.crypto.keys import PublicKey, Signature


class OpCode(IntEnum):
    # Constants
    OP_0 = 0x00
    OP_FALSE = 0x00
    OP_PUSHDATA1 = 0x4C
    OP_PUSHDATA2 = 0x4D
    OP_1NEGATE = 0x4F
    OP_1 = 0x51
    OP_TRUE = 0x51
    OP_2 = 0x52
    OP_16 = 0x60

    # Flow control
    OP_NOP = 0x61
    OP_VERIFY = 0x69
    OP_RETURN = 0x6A

    # Stack
    OP_DUP = 0x76
    OP_DROP = 0x75
    OP_SWAP = 0x7C

    # Bitwise logic
    OP_EQUAL = 0x87
    OP_EQUALVERIFY = 0x88

    # Crypto
    OP_RIPEMD160 = 0xA6
    OP_SHA256 = 0xA8
    OP_HASH160 = 0xA9
    OP_HASH256 = 0xAA
    OP_CHECKSIG = 0xAC
    OP_CHECKMULTISIG = 0xAE


class Script:
    """
    A Bitcoin script (sequence of opcodes and data pushes).

    Scripts are serialized as a byte sequence where:
    - Bytes 0x01-0x4B push that many bytes onto the stack
    - Known opcodes perform operations
    """

    def __init__(self, data: bytes = b""):
        self.data = data

    @classmethod
    def p2pkh_locking(cls, pubkey_hash: bytes) -> Script:
        """
        Create a standard P2PKH locking script (scriptPubKey).

        OP_DUP OP_HASH160 <20-byte hash> OP_EQUALVERIFY OP_CHECKSIG
        """
        if len(pubkey_hash) != 20:
            raise ValueError("pubkey_hash must be 20 bytes")
        return cls(
            bytes([OpCode.OP_DUP, OpCode.OP_HASH160, 0x14])
            + pubkey_hash
            + bytes([OpCode.OP_EQUALVERIFY, OpCode.OP_CHECKSIG])
        )

    @classmethod
    def p2pkh_unlocking(cls, signature: bytes, pubkey: bytes) -> Script:
        """
        Create a standard P2PKH unlocking script (scriptSig).

        <sig_length> <signature> <pubkey_length> <pubkey>
        """
        return cls(
            bytes([len(signature)]) + signature
            + bytes([len(pubkey)]) + pubkey
        )

    def serialize(self) -> bytes:
        """Serialize the script with a length prefix (varint)."""
        length = encode_varint(len(self.data))
        return length + self.data

    @classmethod
    def deserialize(cls, data: bytes, offset: int = 0) -> tuple[Script, int]:
        """Deserialize a length-prefixed script. Returns (script, bytes_consumed)."""
        length, varint_size = decode_varint(data, offset)
        start = offset + varint_size
        script_data = data[start : start + length]
        return cls(script_data), varint_size + length

    def __len__(self) -> int:
        return len(self.data)

    def __add__(self, other: Script) -> Script:
        """Concatenate two scripts (used for validation: scriptSig + scriptPubKey)."""
        return Script(self.data + other.data)

    def hex(self) -> str:
        return self.data.hex()

    def __repr__(self) -> str:
        return f"Script({self.data.hex()})"


class ScriptInterpreter:
    """
    Execute Bitcoin scripts on a stack machine.

    For transaction validation, the scriptSig (unlocking) is executed first,
    then the scriptPubKey (locking) is executed with the resulting stack.
    The transaction is valid if the top of the stack is truthy after execution.
    """

    def __init__(self):
        self.stack: list[bytes] = []

    def verify(
        self,
        script_sig: Script,
        script_pubkey: Script,
        tx_hash: bytes,
    ) -> bool:
        """
        Verify a transaction input by executing scriptSig then scriptPubKey.

        tx_hash is the double-SHA256 hash of the transaction data being signed.
        Returns True if the script execution succeeds and leaves True on the stack.
        """
        self.stack = []
        self._tx_hash = tx_hash

        try:
            self._execute(script_sig)
            self._execute(script_pubkey)
        except Exception:
            return False

        if not self.stack:
            return False
        return self._is_truthy(self.stack[-1])

    def _execute(self, script: Script) -> None:
        """Execute a script, modifying the stack."""
        data = script.data
        i = 0
        while i < len(data):
            opcode = data[i]
            i += 1

            # Data push (1-75 bytes)
            if 0x01 <= opcode <= 0x4B:
                length = opcode
                self.stack.append(data[i : i + length])
                i += length

            elif opcode == OpCode.OP_0:
                self.stack.append(b"")

            elif opcode == OpCode.OP_1:
                self.stack.append(b"\x01")

            elif opcode == OpCode.OP_DUP:
                if not self.stack:
                    raise RuntimeError("OP_DUP: empty stack")
                self.stack.append(self.stack[-1])

            elif opcode == OpCode.OP_DROP:
                if not self.stack:
                    raise RuntimeError("OP_DROP: empty stack")
                self.stack.pop()

            elif opcode == OpCode.OP_HASH160:
                if not self.stack:
                    raise RuntimeError("OP_HASH160: empty stack")
                value = self.stack.pop()
                self.stack.append(hash160(value))

            elif opcode == OpCode.OP_EQUAL:
                if len(self.stack) < 2:
                    raise RuntimeError("OP_EQUAL: need 2 items")
                a = self.stack.pop()
                b = self.stack.pop()
                self.stack.append(b"\x01" if a == b else b"")

            elif opcode == OpCode.OP_EQUALVERIFY:
                if len(self.stack) < 2:
                    raise RuntimeError("OP_EQUALVERIFY: need 2 items")
                a = self.stack.pop()
                b = self.stack.pop()
                if a != b:
                    raise RuntimeError("OP_EQUALVERIFY: values not equal")

            elif opcode == OpCode.OP_CHECKSIG:
                if len(self.stack) < 2:
                    raise RuntimeError("OP_CHECKSIG: need 2 items")
                pubkey_bytes = self.stack.pop()
                sig_bytes = self.stack.pop()
                try:
                    pubkey = PublicKey.from_bytes(pubkey_bytes)
                    # Strip trailing SIGHASH type byte before DER verification
                    der_bytes = sig_bytes[:-1] if sig_bytes else sig_bytes
                    sig = Signature(der_bytes=der_bytes)
                    valid = pubkey.verify(sig, self._tx_hash)
                except Exception:
                    valid = False
                self.stack.append(b"\x01" if valid else b"")

            elif opcode == OpCode.OP_VERIFY:
                if not self.stack:
                    raise RuntimeError("OP_VERIFY: empty stack")
                if not self._is_truthy(self.stack.pop()):
                    raise RuntimeError("OP_VERIFY: false")

            elif opcode == OpCode.OP_RETURN:
                raise RuntimeError("OP_RETURN: script terminated")

            elif opcode == OpCode.OP_NOP:
                pass

            else:
                raise RuntimeError(f"Unknown opcode: 0x{opcode:02x}")

    @staticmethod
    def _is_truthy(value: bytes) -> bool:
        """Check if a stack value is truthy (non-zero)."""
        for byte in value:
            if byte != 0:
                return True
        return False


def encode_varint(n: int) -> bytes:
    """Encode an integer as a Bitcoin variable-length integer."""
    if n < 0xFD:
        return struct.pack("<B", n)
    elif n <= 0xFFFF:
        return b"\xfd" + struct.pack("<H", n)
    elif n <= 0xFFFFFFFF:
        return b"\xfe" + struct.pack("<I", n)
    else:
        return b"\xff" + struct.pack("<Q", n)


def decode_varint(data: bytes, offset: int = 0) -> tuple[int, int]:
    """Decode a Bitcoin varint. Returns (value, bytes_consumed)."""
    first = data[offset]
    if first < 0xFD:
        return first, 1
    elif first == 0xFD:
        return struct.unpack_from("<H", data, offset + 1)[0], 3
    elif first == 0xFE:
        return struct.unpack_from("<I", data, offset + 1)[0], 5
    else:
        return struct.unpack_from("<Q", data, offset + 1)[0], 9
