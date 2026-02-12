#!/usr/bin/env python3
"""
BitAkita CLI - ウォレット作成、マイニング、残高確認、送金の実例。

使い方:
    python bitakita/cli.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bitakita.core.blockchain import Blockchain
from bitakita.wallet.wallet import Wallet
from bitakita.mining.miner import Miner
from bitakita import params


def fmt(inu: int) -> str:
    """inu を BITA 表記に変換"""
    return f"{inu / 1_0000_0000:.8f} BITA"


def main():
    # ================================================================
    # Step 1: ウォレットを作る
    # ================================================================
    print("=== Step 1: ウォレット作成 ===\n")

    my_wallet = Wallet()
    my_wallet.generate_key()

    print(f"  アドレス:   {my_wallet.get_address()}")
    print(f"  秘密鍵:     {my_wallet.keys[0].private_key.hex()[:16]}... (秘密！)")
    print(f"  公開鍵:     {my_wallet.keys[0].public_key.hex()}")

    # もう1つ送金先ウォレットも作る
    friend_wallet = Wallet()
    friend_wallet.generate_key()
    print(f"\n  友人のアドレス: {friend_wallet.get_address()}")

    # ================================================================
    # Step 2: ブロックチェーンを起動してジェネシスブロックを採掘
    # ================================================================
    print("\n=== Step 2: ブロックチェーン起動 + ジェネシスブロック採掘 ===\n")

    blockchain = Blockchain()
    miner = Miner(blockchain, my_wallet.get_pubkey_hash())

    genesis = miner.mine_genesis_block(
        message=b"BitAkita hajimemashita!"  # 好きなメッセージを入れられる
    )
    blockchain.add_genesis_block(genesis)

    print(f"  ジェネシスブロック採掘完了!")
    print(f"  ブロックハッシュ: {genesis.hash_hex()[:32]}...")
    print(f"  報酬:             {fmt(params.INITIAL_REWARD)}")
    print(f"  残高:             {fmt(my_wallet.get_balance(blockchain))}")

    # ================================================================
    # Step 3: さらにブロックを掘って BITA を貯める
    # ================================================================
    print("\n=== Step 3: ブロック採掘で BITA を稼ぐ ===\n")

    for i in range(5):
        block = miner.mine_block(
            message=f"Block {i+1} mined!".encode()
        )
        if block:
            success, msg = blockchain.add_block(block)
            if success:
                balance = my_wallet.get_balance(blockchain)
                print(f"  ブロック {blockchain.height} 採掘 → 残高: {fmt(balance)}")

    # ================================================================
    # Step 4: 残高を確認する
    # ================================================================
    print("\n=== Step 4: 残高確認 ===\n")

    balance = my_wallet.get_balance(blockchain)
    spendable = my_wallet.get_spendable_balance(blockchain)
    utxos = my_wallet.get_utxos(blockchain)

    print(f"  総残高:         {fmt(balance)}")
    print(f"  使用可能残高:   {fmt(spendable)}")
    print(f"  UTXO数:         {len(utxos)} 個")
    print(f"  現在の手数料:   {blockchain.fee_manager.base_fee} inu/byte")

    for i, utxo in enumerate(utxos):
        print(f"    UTXO[{i}]: {fmt(utxo.output.amount)} (ブロック{utxo.block_height}で生成)")

    # ================================================================
    # Step 5: 友人に送金する
    # ================================================================
    print("\n=== Step 5: 友人に 25 BITA 送金 ===\n")

    try:
        tx = my_wallet.create_transaction(
            blockchain,
            friend_wallet.get_address(),
            25_0000_0000,  # 25 BITA
        )
        print(f"  トランザクション作成: {tx.txid_hex()[:32]}...")
        print(f"  入力数: {len(tx.inputs)}, 出力数: {len(tx.outputs)}")

        # メモリプールに追加
        success, msg = blockchain.add_to_mempool(tx)
        print(f"  メモリプール: {msg}")

        # ブロックを掘ってトランザクションを確定
        block = miner.mine_block()
        if block:
            success, msg = blockchain.add_block(block)
            print(f"  ブロック採掘: {msg}")

        print(f"\n  自分の残高:   {fmt(my_wallet.get_balance(blockchain))}")
        print(f"  友人の残高:   {fmt(friend_wallet.get_balance(blockchain))}")

    except ValueError as e:
        print(f"  エラー: {e}")

    # ================================================================
    # Step 6: もう1回送金
    # ================================================================
    print("\n=== Step 6: 友人に追加で 10 BITA 送金 ===\n")

    try:
        tx2 = my_wallet.create_transaction(
            blockchain,
            friend_wallet.get_address(),
            10_0000_0000,  # 10 BITA
        )
        success, msg = blockchain.add_to_mempool(tx2)
        print(f"  メモリプール: {msg}")

        block = miner.mine_block()
        if block:
            blockchain.add_block(block)

        print(f"  自分の残高:   {fmt(my_wallet.get_balance(blockchain))}")
        print(f"  友人の残高:   {fmt(friend_wallet.get_balance(blockchain))}")

    except ValueError as e:
        print(f"  エラー: {e}")

    # ================================================================
    # まとめ
    # ================================================================
    print("\n=== まとめ ===\n")
    print(f"  チェーン高:     {blockchain.height}")
    print(f"  自分の残高:     {fmt(my_wallet.get_balance(blockchain))}")
    print(f"  友人の残高:     {fmt(friend_wallet.get_balance(blockchain))}")
    print(f"  総発行量:       {fmt(blockchain.total_supply)}")
    print(f"  バーン済み:     {fmt(blockchain.total_burned)}")
    print(f"  手数料(現在):   {blockchain.fee_manager.base_fee} inu/byte")
    print(f"  UTXO数:         {len(blockchain.utxo_set)}")


if __name__ == "__main__":
    main()
