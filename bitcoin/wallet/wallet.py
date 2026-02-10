"""
Bitcoin Wallet.

A wallet manages private keys, generates addresses, and creates signed transactions.

Address generation (P2PKH):
1. Generate ECDSA private key (secp256k1)
2. Derive public key
3. Hash160(public_key) -> 20-byte pubkey hash
4. Base58Check encode with version byte 0x00 -> Bitcoin address

Transaction creation:
1. Select UTXOs to cover the desired amount + fee
2. Create transaction with inputs and outputs
3. Sign each input with the corresponding private key
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from bitcoin.crypto.keys import PrivateKey, PublicKey
from bitcoin.crypto.hash import hash160
from bitcoin.utils.encoding import base58check_encode, base58check_decode
from bitcoin.core.transaction import Transaction, TxInput, TxOutput
from bitcoin.core.blockchain import Blockchain, UTXO
from bitcoin.script.script import Script


@dataclass
class KeyPair:
    """A private/public key pair with its derived address."""
    private_key: PrivateKey
    public_key: PublicKey
    pubkey_hash: bytes
    address: str


class Wallet:
    """
    A Bitcoin wallet managing keys and creating transactions.
    """

    # Version bytes for addresses
    MAINNET_P2PKH = b"\x00"
    TESTNET_P2PKH = b"\x6f"

    def __init__(self, network: str = "mainnet"):
        self.network = network
        self.version = self.MAINNET_P2PKH if network == "mainnet" else self.TESTNET_P2PKH
        self.keys: list[KeyPair] = []
        self._address_map: dict[str, KeyPair] = {}
        self._pubkey_hash_map: dict[bytes, KeyPair] = {}

    def generate_key(self) -> KeyPair:
        """Generate a new key pair and add it to the wallet."""
        private_key = PrivateKey.generate()
        return self.import_key(private_key)

    def import_key(self, private_key: PrivateKey) -> KeyPair:
        """Import an existing private key into the wallet."""
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
        """Get the current receiving address (generates one if none exist)."""
        if not self.keys:
            self.generate_key()
        return self.keys[-1].address

    def get_pubkey_hash(self) -> bytes:
        """Get the pubkey hash for the current receiving address."""
        if not self.keys:
            self.generate_key()
        return self.keys[-1].pubkey_hash

    def get_all_addresses(self) -> list[str]:
        """Get all addresses managed by this wallet."""
        return [kp.address for kp in self.keys]

    def get_balance(self, blockchain: Blockchain) -> int:
        """Get total balance across all wallet addresses (in satoshis)."""
        total = 0
        for kp in self.keys:
            total += blockchain.get_balance(kp.pubkey_hash)
        return total

    def get_utxos(self, blockchain: Blockchain) -> list[UTXO]:
        """Get all UTXOs for this wallet."""
        utxos = []
        for kp in self.keys:
            utxos.extend(blockchain.get_utxos_for(kp.pubkey_hash))
        return utxos

    def create_transaction(
        self,
        blockchain: Blockchain,
        recipient_address: str,
        amount: int,
        fee: int = 1000,
    ) -> Transaction:
        """
        Create and sign a transaction sending `amount` satoshis to `recipient_address`.

        Args:
            blockchain: The blockchain (for UTXO lookup)
            recipient_address: The recipient's Bitcoin address
            amount: Amount to send in satoshis
            fee: Transaction fee in satoshis

        Returns:
            A signed Transaction ready for broadcast

        Raises:
            ValueError: If insufficient funds or invalid address
        """
        # Decode recipient address
        version, recipient_hash = base58check_decode(recipient_address)

        # Select UTXOs (simple greedy algorithm)
        utxos = self.get_utxos(blockchain)
        selected_utxos: list[UTXO] = []
        selected_total = 0
        needed = amount + fee

        # Sort by amount (ascending) for better coin selection
        utxos.sort(key=lambda u: u.output.amount)
        for utxo in utxos:
            selected_utxos.append(utxo)
            selected_total += utxo.output.amount
            if selected_total >= needed:
                break

        if selected_total < needed:
            raise ValueError(
                f"Insufficient funds: have {selected_total} satoshis, "
                f"need {needed} (amount={amount}, fee={fee})"
            )

        # Create transaction
        tx = Transaction()

        # Add inputs (unsigned for now)
        for utxo in selected_utxos:
            tx.inputs.append(
                TxInput(
                    prev_tx_hash=utxo.tx_hash,
                    output_index=utxo.output_index,
                )
            )

        # Add recipient output
        tx.outputs.append(
            TxOutput(
                amount=amount,
                script_pubkey=Script.p2pkh_locking(recipient_hash),
            )
        )

        # Add change output if needed
        change = selected_total - amount - fee
        if change > 0:
            change_pubkey_hash = self.keys[0].pubkey_hash
            tx.outputs.append(
                TxOutput(
                    amount=change,
                    script_pubkey=Script.p2pkh_locking(change_pubkey_hash),
                )
            )

        # Sign each input
        for i, utxo in enumerate(selected_utxos):
            self._sign_input(tx, i, utxo)

        return tx

    def _sign_input(self, tx: Transaction, input_index: int, utxo: UTXO) -> None:
        """Sign a specific transaction input."""
        # Find the key for this UTXO
        script_pubkey = utxo.output.script_pubkey
        # Extract pubkey hash from P2PKH script: OP_DUP OP_HASH160 0x14 <hash> OP_EQUALVERIFY OP_CHECKSIG
        pubkey_hash = script_pubkey.data[3:23]

        if pubkey_hash not in self._pubkey_hash_map:
            raise ValueError("No private key found for UTXO")

        kp = self._pubkey_hash_map[pubkey_hash]

        # Compute the hash to sign
        sig_hash = tx.hash_for_signing(input_index, script_pubkey)

        # Sign
        signature = kp.private_key.sign(sig_hash)

        # Build scriptSig: <sig> <pubkey>
        # Append SIGHASH_ALL byte (0x01) to signature
        sig_bytes = signature.der_bytes + b"\x01"
        pubkey_bytes = kp.public_key.compressed_bytes()

        tx.inputs[input_index].script_sig = Script.p2pkh_unlocking(
            sig_bytes, pubkey_bytes
        )

    @staticmethod
    def address_to_pubkey_hash(address: str) -> bytes:
        """Extract the pubkey hash from a Bitcoin address."""
        _, pubkey_hash = base58check_decode(address)
        return pubkey_hash

    @staticmethod
    def pubkey_hash_to_address(pubkey_hash: bytes, version: bytes = b"\x00") -> str:
        """Convert a pubkey hash to a Bitcoin address."""
        return base58check_encode(version, pubkey_hash)

    def __repr__(self) -> str:
        return f"Wallet(keys={len(self.keys)}, network={self.network})"
