"""
BitAkita Wallet with stealth address support.

Extends Bitcoin wallet with:
- Stealth address generation and scanning
- Stake management (stake/unstake)
- Fee estimation using EIP-1559 base fee
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from bitcoin.crypto.keys import PrivateKey, PublicKey
from bitcoin.crypto.hash import hash160
from bitcoin.script.script import Script, OpCode
from bitakita.utils import base58check_encode, base58check_decode
from bitakita.crypto.stealth import StealthAddress, StealthKeyPair
from bitakita.core.transaction import (
    Transaction, TxInput, TxOutput, TxType, StakeTransaction,
)
from bitakita.core.blockchain import Blockchain, UTXO
from bitakita import params


@dataclass
class KeyPair:
    private_key: PrivateKey
    public_key: PublicKey
    pubkey_hash: bytes
    address: str


class Wallet:
    """BitAkita wallet with stealth address and staking support."""

    def __init__(self, network: str = "mainnet"):
        self.network = network
        self.version = params.MAINNET_P2PKH if network == "mainnet" else params.TESTNET_P2PKH
        self.keys: list[KeyPair] = []
        self._address_map: dict[str, KeyPair] = {}
        self._pubkey_hash_map: dict[bytes, KeyPair] = {}

        # Stealth address support
        self.stealth_keypair: Optional[StealthKeyPair] = None
        self.stealth_address: Optional[StealthAddress] = None

        # One-time keys recovered from stealth payments
        self._stealth_keys: dict[bytes, PrivateKey] = {}  # pubkey_hash -> privkey

    # --- Key Management ---

    def generate_key(self) -> KeyPair:
        private_key = PrivateKey.generate()
        return self.import_key(private_key)

    def import_key(self, private_key: PrivateKey) -> KeyPair:
        public_key = private_key.public_key
        pubkey_hash = public_key.hash160()
        address = base58check_encode(self.version, pubkey_hash)
        kp = KeyPair(
            private_key=private_key,
            public_key=public_key,
            pubkey_hash=pubkey_hash,
            address=address,
        )
        self.keys.append(kp)
        self._address_map[address] = kp
        self._pubkey_hash_map[pubkey_hash] = kp
        return kp

    def get_address(self) -> str:
        if not self.keys:
            self.generate_key()
        return self.keys[-1].address

    def get_pubkey_hash(self) -> bytes:
        if not self.keys:
            self.generate_key()
        return self.keys[-1].pubkey_hash

    # --- Stealth Addresses ---

    def generate_stealth_address(self) -> StealthAddress:
        """Generate a stealth meta-address for receiving private payments."""
        self.stealth_keypair = StealthKeyPair.generate()
        self.stealth_address = StealthAddress.from_keypair(self.stealth_keypair)
        return self.stealth_address

    def get_stealth_address_string(self) -> Optional[str]:
        """Get the encoded stealth address string."""
        if self.stealth_address is None:
            return None
        return self.stealth_address.encode()

    def scan_stealth_transaction(
        self,
        ephemeral_pubkey_bytes: bytes,
        output_pubkey_hashes: list[bytes],
    ) -> list[int]:
        """
        Scan a transaction for stealth payments to this wallet.

        Returns indices of outputs belonging to this wallet.
        """
        if self.stealth_keypair is None:
            return []

        matches = StealthAddress.scan_for_payments(
            self.stealth_keypair,
            ephemeral_pubkey_bytes,
            output_pubkey_hashes,
        )

        # Recover private keys for matched outputs
        if matches:
            one_time_priv, one_time_hash = StealthAddress.recover_one_time_privkey(
                self.stealth_keypair, ephemeral_pubkey_bytes
            )
            self._stealth_keys[one_time_hash] = one_time_priv
            # Also register as a regular key for spending
            self.import_key(one_time_priv)

        return matches

    # --- Balance ---

    def get_balance(self, blockchain: Blockchain) -> int:
        total = 0
        for kp in self.keys:
            total += blockchain.get_balance(kp.pubkey_hash)
        return total

    def get_spendable_balance(self, blockchain: Blockchain) -> int:
        """Balance excluding staked UTXOs."""
        total = 0
        for kp in self.keys:
            utxos = blockchain.get_spendable_utxos_for(kp.pubkey_hash)
            total += sum(u.output.amount for u in utxos)
        return total

    def get_utxos(self, blockchain: Blockchain) -> list[UTXO]:
        utxos = []
        for kp in self.keys:
            utxos.extend(blockchain.get_spendable_utxos_for(kp.pubkey_hash))
        return utxos

    # --- Transaction Creation ---

    def create_transaction(
        self,
        blockchain: Blockchain,
        recipient_address: str,
        amount: int,
        priority_fee_per_byte: int = 0,
    ) -> Transaction:
        """
        Create and sign a transaction with EIP-1559 fee calculation.
        """
        version, recipient_hash = base58check_decode(recipient_address)

        # Estimate fee: ~180 bytes per input + ~34 per output + ~20 overhead + buffer
        utxos = self.get_utxos(blockchain)
        estimated_inputs = max(1, (amount // (utxos[0].output.amount if utxos else 1)) + 1)
        estimated_size = estimated_inputs * 180 + 2 * 34 + 20
        fee_breakdown = blockchain.fee_manager.calculate_fee(
            estimated_size, priority_fee_per_byte
        )
        fee = fee_breakdown.total_fee

        selected, selected_total = self._select_utxos(utxos, amount + fee)

        tx = Transaction()
        for utxo in selected:
            tx.inputs.append(
                TxInput(prev_tx_hash=utxo.tx_hash, output_index=utxo.output_index)
            )

        tx.outputs.append(
            TxOutput(amount=amount, script_pubkey=Script.p2pkh_locking(recipient_hash))
        )

        change = selected_total - amount - fee
        if change > params.UTXO_DUST_THRESHOLD:
            tx.outputs.append(
                TxOutput(
                    amount=change,
                    script_pubkey=Script.p2pkh_locking(self.keys[0].pubkey_hash),
                )
            )

        for i, utxo in enumerate(selected):
            self._sign_input(tx, i, utxo)

        return tx

    def create_stealth_transaction(
        self,
        blockchain: Blockchain,
        recipient_stealth: StealthAddress,
        amount: int,
        priority_fee_per_byte: int = 0,
    ) -> Transaction:
        """
        Create a transaction to a stealth address.

        Includes the ephemeral public key in an OP_RETURN output
        so the recipient can detect and spend the payment.
        """
        # Generate one-time address
        one_time_hash, ephemeral_pub_bytes, _ = recipient_stealth.generate_one_time_address()

        estimated_size = 300
        fee_breakdown = blockchain.fee_manager.calculate_fee(
            estimated_size, priority_fee_per_byte
        )
        fee = fee_breakdown.total_fee

        utxos = self.get_utxos(blockchain)
        selected, selected_total = self._select_utxos(utxos, amount + fee)

        tx = Transaction()
        for utxo in selected:
            tx.inputs.append(
                TxInput(prev_tx_hash=utxo.tx_hash, output_index=utxo.output_index)
            )

        # Payment output (to one-time address)
        tx.outputs.append(
            TxOutput(amount=amount, script_pubkey=Script.p2pkh_locking(one_time_hash))
        )

        # OP_RETURN output with ephemeral public key (for recipient scanning)
        op_return_script = Script(
            bytes([OpCode.OP_RETURN, len(ephemeral_pub_bytes)]) + ephemeral_pub_bytes
        )
        tx.outputs.append(TxOutput(amount=0, script_pubkey=op_return_script))

        # Change output
        change = selected_total - amount - fee
        if change > params.UTXO_DUST_THRESHOLD:
            tx.outputs.append(
                TxOutput(
                    amount=change,
                    script_pubkey=Script.p2pkh_locking(self.keys[0].pubkey_hash),
                )
            )

        for i, utxo in enumerate(selected):
            self._sign_input(tx, i, utxo)

        return tx

    # --- Staking ---

    def create_stake_transaction(
        self,
        blockchain: Blockchain,
        stake_amount: int,
    ) -> StakeTransaction:
        """Create a staking transaction to become a PoS validator."""
        if stake_amount < params.MIN_STAKE_AMOUNT:
            raise ValueError(
                f"Minimum stake: {params.MIN_STAKE_AMOUNT} inu "
                f"({params.MIN_STAKE_AMOUNT / 1_0000_0000:.0f} BITA)"
            )

        estimated_fee = blockchain.fee_manager.base_fee * 200
        utxos = self.get_utxos(blockchain)
        selected, selected_total = self._select_utxos(utxos, stake_amount + estimated_fee)

        staker_hash = self.keys[0].pubkey_hash
        change = selected_total - stake_amount - estimated_fee

        inputs = [
            TxInput(prev_tx_hash=u.tx_hash, output_index=u.output_index)
            for u in selected
        ]

        tx = StakeTransaction(
            inputs=inputs,
            stake_amount=stake_amount,
            staker_pubkey_hash=staker_hash,
            change_amount=max(0, change),
            change_pubkey_hash=staker_hash if change > params.UTXO_DUST_THRESHOLD else None,
        )

        for i, utxo in enumerate(selected):
            self._sign_input(tx, i, utxo)

        return tx

    # --- Internal ---

    def _select_utxos(self, utxos: list[UTXO], needed: int) -> tuple[list[UTXO], int]:
        """Select UTXOs to cover the needed amount."""
        utxos.sort(key=lambda u: u.output.amount)
        selected = []
        total = 0
        for utxo in utxos:
            selected.append(utxo)
            total += utxo.output.amount
            if total >= needed:
                break
        if total < needed:
            raise ValueError(
                f"Insufficient funds: have {total} inu, need {needed}"
            )
        return selected, total

    def _sign_input(self, tx: Transaction, input_index: int, utxo: UTXO) -> None:
        script_pubkey = utxo.output.script_pubkey
        pubkey_hash = script_pubkey.data[3:23]

        if pubkey_hash not in self._pubkey_hash_map:
            raise ValueError("No private key found for UTXO")

        kp = self._pubkey_hash_map[pubkey_hash]
        sig_hash = tx.hash_for_signing(input_index, script_pubkey)
        signature = kp.private_key.sign(sig_hash)

        sig_bytes = signature.der_bytes + b"\x01"
        pubkey_bytes = kp.public_key.compressed_bytes()

        tx.inputs[input_index].script_sig = Script.p2pkh_unlocking(
            sig_bytes, pubkey_bytes
        )

    @staticmethod
    def address_to_pubkey_hash(address: str) -> bytes:
        _, pubkey_hash = base58check_decode(address)
        return pubkey_hash

    def __repr__(self) -> str:
        stealth = "yes" if self.stealth_address else "no"
        return f"Wallet(keys={len(self.keys)}, stealth={stealth})"
