# BitAkita - Next-Generation Cryptocurrency

Bitcoin の問題点を解決する草コイン **BitAkita (BITA)** の完全実装です。
Bitcoin プロトコルの基礎実装の上に、8 つの革新を加えています。

## Bitcoin からの改善点

| 課題 | Bitcoin | BitAkita |
|------|---------|----------|
| 電力消費 | PoW のみ | PoW/PoS ハイブリッド |
| スケーラビリティ | 10分/1MB固定 | 60秒/動的ブロックサイズ(0.5-8MB) |
| 手数料の予測不能 | 先着順オークション | EIP-1559 自動調整 + 50%バーン |
| プライバシー | 疑似匿名 | ステルスアドレス (ECDH) |
| ファイナリティ | 確率的(~60分) | PoS チェックポイント確定 |
| ガバナンス | オフチェーン | オンチェーン投票 |
| UTXO 肥大化 | 制御なし | UTXO レンタル料 |
| 経済モデル | 21M BTC / satoshi | 21M BITA / inu |

## 必要環境

- Python 3.10+
- 依存ライブラリ: `ecdsa`

```bash
pip install -r requirements.txt
```

## プロジェクト構成

```
.
├── bitcoin/                  # Bitcoin プロトコル基礎実装
│   ├── crypto/               #   SHA-256, RIPEMD-160, ECDSA (secp256k1)
│   ├── core/                 #   Transaction, Block, Blockchain, Merkle Tree
│   ├── script/               #   Script VM (P2PKH)
│   ├── mining/               #   PoW マイナー
│   ├── wallet/               #   ウォレット (鍵管理)
│   ├── network/              #   ノード (in-process)
│   └── utils/                #   Base58Check エンコーディング
│
├── bitakita/                 # BitAkita 独自実装
│   ├── crypto/stealth.py     #   ステルスアドレス (ECDH)
│   ├── consensus/            #   PoS, チェックポイント, ハイブリッド合意
│   ├── fee/eip1559.py        #   EIP-1559 手数料メカニズム
│   ├── governance/voting.py  #   オンチェーンガバナンス
│   ├── core/                 #   拡張 Transaction/Block/Blockchain
│   ├── wallet/               #   拡張ウォレット (ステルス/ステーキング対応)
│   ├── mining/               #   手数料バーン統合マイナー
│   ├── network/              #   TCP P2P ノード + ワイヤプロトコル
│   ├── storage/              #   ブロック/ウォレットのディスク永続化
│   ├── params.py             #   全ネットワークパラメータ
│   ├── cli.py                #   テストバージョンデモ
│   └── demo.py               #   全8機能デモ
│
├── bitakitad.py              # デーモン (本番用サーバーノード)
├── bitakita-cli.py           # CLI クライアント (デーモン操作用)
├── tests/test_bitakita.py    # ユニットテスト (36件)
└── requirements.txt
```

---

# テストバージョンのデモ

テストバージョンはネットワーク接続やディスク保存を使わず、全てメモリ内で完結します。
BitAkita の基本機能を手軽に試すのに最適です。

## 基本デモ (ウォレット・マイニング・送金)

```bash
python bitakita/cli.py
```

実行すると以下の流れを自動実行します:

1. **ウォレット作成** - 自分と友人の鍵ペアを生成
2. **ジェネシスブロック採掘** - チェーンを起動して最初のブロックを採掘
3. **ブロック採掘** - 5 ブロック採掘して BITA を獲得
4. **残高確認** - UTXO ベースの残高・使用可能額を表示
5. **送金** - 友人に 25 BITA、さらに 10 BITA を送金
6. **まとめ** - チェーン状態の最終確認

### 出力例

```
=== Step 1: ウォレット作成 ===

  アドレス:   APwkzW2gddQrryreYppJM4xvxqCujRd4dk
  秘密鍵:     a3b7c9d1e5f20814... (秘密！)
  公開鍵:     02f8a1b3c5d7e9f0...

  友人のアドレス: AQ3xJKmvN8pRbYzW...

=== Step 2: ブロックチェーン起動 + ジェネシスブロック採掘 ===

  ジェネシスブロック採掘完了!
  ブロックハッシュ: c887fd864d3ac4e9ac3fc2cd8507cb22...
  報酬:             50.00000000 BITA
  残高:             50.00000000 BITA

=== Step 3: ブロック採掘で BITA を稼ぐ ===

  ブロック 1 採掘 → 残高: 100.00000000 BITA
  ブロック 2 採掘 → 残高: 150.00000000 BITA
  ...

=== Step 5: 友人に 25 BITA 送金 ===

  トランザクション作成: 7a3f2b1c...
  メモリプール: Added to mempool
  ブロック採掘: Block added at height 7

  自分の残高:   274.99997000 BITA
  友人の残高:   25.00000000 BITA
```

## 全機能デモ (8つの革新を全て実演)

```bash
python bitakita/demo.py
```

このデモでは以下の全機能を順番に実行します:

1. ウォレット作成・ジェネシスブロック採掘
2. **PoW マイニング** + **動的手数料**
3. 通常の送金トランザクション
4. **ステルスアドレス** による匿名送金
5. **PoS バリデーター登録** + **チェックポイントファイナリティ**
6. **オンチェーンガバナンス投票**
7. **EIP-1559 手数料** の詳細表示
8. **UTXO レンタル** の説明
9. P2P ネットワークシミュレーション
10. Bitcoin vs BitAkita 比較表

---

# 本番バージョン (デーモン + CLI)

本番バージョンでは、実際の TCP ネットワーク通信とディスク永続化を行います。
自分のマシンをノードとして起動し、他のノードと接続してネットワークを構築できます。

## アーキテクチャ

```
┌─────────────────┐     TCP P2P     ┌─────────────────┐
│   bitakitad      │◄──────────────►│   bitakitad      │
│   (ノード A)     │    port 18333   │   (ノード B)     │
│                  │                 │                  │
│  Blockchain      │                 │  Blockchain      │
│  Wallet          │                 │  Wallet          │
│  Miner           │                 │  Miner           │
│  BlockStore      │                 │  BlockStore      │
└────────┬─────────┘                 └────────┬─────────┘
         │ JSON-RPC                            │ JSON-RPC
         │ port 18332                          │ port 18332
┌────────┴─────────┐                 ┌────────┴─────────┐
│  bitakita-cli    │                 │  bitakita-cli    │
│  (操作用 CLI)    │                 │  (操作用 CLI)    │
└──────────────────┘                 └──────────────────┘
```

## Step 1: デーモンを起動する

```bash
# 基本起動 (ポートはデフォルト P2P=18333, RPC=18332)
python bitakitad.py

# マイニング付きで起動
python bitakitad.py --mine

# ポートやデータ保存先を指定して起動
python bitakitad.py --port 18333 --rpc-port 18332 --data-dir ./my-node --mine
```

起動すると以下のログが表示されます:

```
17:49:21 [bitakitad] INFO: New wallet created: AP57DzcS7mw4v1y7sjVwFApWhcPWnuJs6m
17:49:21 [bitakitad] INFO: Mining genesis block...
17:49:21 [bitakitad] INFO: Genesis block mined: c887fd864d3ac4e9...
17:49:21 [bitakita.node] INFO: Node node-18333 listening on 0.0.0.0:18333
17:49:21 [bitakitad] INFO: RPC server on 127.0.0.1:18332
17:49:21 [bitakitad] INFO: BitAkita daemon started
  P2P port:  18333
  RPC port:  18332
  Data dir:  ./my-node
  Address:   AP57DzcS7mw4v1y7sjVwFApWhcPWnuJs6m
  Height:    0
17:49:21 [bitakitad] INFO: Mining started
17:49:21 [bitakitad] INFO: Mined block 1 | Balance: 100.00 BITA
17:49:21 [bitakitad] INFO: Mined block 2 | Balance: 150.00 BITA
...
```

### デーモンのオプション

| オプション | デフォルト | 説明 |
|-----------|----------|------|
| `--port` | 18333 | P2P 通信ポート (他ノードとの接続用) |
| `--rpc-port` | 18332 | RPC ポート (CLI からの操作受付用) |
| `--data-dir` | `./bitakita-data` | ブロック・ウォレットの保存先ディレクトリ |
| `--mine` | (なし) | 指定すると起動直後からマイニング開始 |
| `--connect` | (なし) | 起動時に接続するピア (`host:port` 形式) |

## Step 2: CLI でノードを操作する

デーモンが起動した状態で、別のターミナルから CLI コマンドを実行します。

```bash
# ノード情報を確認
python bitakita-cli.py getinfo

# 残高を確認
python bitakita-cli.py getbalance

# 自分のアドレスを表示
python bitakita-cli.py getaddress

# 新しいアドレスを生成
python bitakita-cli.py newaddress

# 手動で 5 ブロック採掘
python bitakita-cli.py mine 5

# 自動マイニング開始 / 停止
python bitakita-cli.py startmining
python bitakita-cli.py stopmining

# 送金 (10 BITA を指定アドレスへ)
python bitakita-cli.py send AQ3xJKmvN8pRbYzW... 10

# ブロック情報を表示 (ジェネシスブロック)
python bitakita-cli.py getblock 0

# メモリプール内のトランザクション一覧
python bitakita-cli.py getmempool

# 自分の UTXO 一覧
python bitakita-cli.py getutxos

# 接続中のピア一覧
python bitakita-cli.py getpeers
```

RPC ポートがデフォルト (18332) と異なる場合は `--rpc-port` を指定します:

```bash
python bitakita-cli.py --rpc-port 19332 getinfo
```

### CLI コマンド一覧

| コマンド | 説明 |
|---------|------|
| `getinfo` | ブロック高、ピア数、供給量、手数料などのノード情報 |
| `getbalance` | ウォレットの残高 (総残高 / 使用可能額) |
| `getaddress` | メインアドレスと全アドレスを表示 |
| `newaddress` | 新しいアドレスを生成してウォレットに追加 |
| `send <address> <amount>` | 指定アドレスへ BITA を送金 (amount は BITA 単位) |
| `mine [count]` | 手動で count ブロック採掘 (デフォルト 1) |
| `startmining` | バックグラウンド自動マイニング開始 |
| `stopmining` | 自動マイニング停止 |
| `getblock [height]` | 指定高さのブロック情報 (省略時は最新) |
| `getmempool` | 未確認トランザクションの一覧 |
| `getutxos` | 自分のウォレットの UTXO 一覧 |
| `connect <host> <port>` | 他ノードに接続 |
| `getpeers` | 接続中のピア一覧 |

## Step 3: 2ノードで P2P ネットワークを構築する

2つのターミナルで別々のノードを起動し、接続します。

**ターミナル 1 (ノード A):**
```bash
python bitakitad.py --port 18333 --rpc-port 18332 --data-dir ./node-a --mine
```

**ターミナル 2 (ノード B - ノード A に接続):**
```bash
python bitakitad.py --port 18334 --rpc-port 18334 --data-dir ./node-b --connect 127.0.0.1:18333
```

**ターミナル 3 (CLI で確認):**
```bash
# ノード A のピア一覧
python bitakita-cli.py --rpc-port 18332 getpeers

# ノード B のピア一覧
python bitakita-cli.py --rpc-port 18334 getpeers

# ノード A の残高
python bitakita-cli.py --rpc-port 18332 getbalance

# ノード B がノード A からブロックを同期したか確認
python bitakita-cli.py --rpc-port 18334 getinfo
```

ノード A がマイニングしたブロックは TCP P2P 通信を通じてノード B に自動的に伝播します。

## データの永続化

デーモンを停止 (Ctrl+C) しても、データはディスクに保存されます。
再起動すると前回の状態から再開されます。

```
./bitakita-data/           # --data-dir で指定したディレクトリ
├── blocks/
│   ├── 000000.json        # ジェネシスブロック
│   ├── 000001.json        # ブロック 1
│   ├── 000002.json        # ブロック 2
│   └── ...
├── chain_state.json       # チェーン状態 (高さ, 難易度, 手数料など)
└── wallets/
    └── wallet_AP57Dzc...json  # ウォレットの秘密鍵
```

---

# テストの実行

```bash
pip install pytest
python -m pytest tests/test_bitakita.py -v
```

全 36 テストが Bitcoin 基盤の暗号処理から BitAkita 独自機能まで網羅しています:

- 暗号処理 (SHA-256, Hash160, ECDSA, Base58Check)
- マークルツリー
- ブロックチェーン (ジェネシス、採掘、二重使用検出)
- ステルスアドレス (生成・走査・鍵復元)
- PoS + チェックポイントファイナリティ
- EIP-1559 手数料メカニズム
- オンチェーンガバナンス
- 動的ブロックサイズ
- P2P ネットワーク同期
- PoW/PoS ハイブリッドコンセンサス

---

# パラメータ一覧

| パラメータ | 値 | 説明 |
|-----------|-----|------|
| ブロック報酬 | 50 BITA | 初期報酬 (210,000 ブロック毎に半減) |
| 最大供給量 | 21,000,000 BITA | Bitcoin と同じ |
| ブロック時間 | 60 秒 | Bitcoin の 1/10 |
| ブロックサイズ | 0.5 - 8 MB (目標 2MB) | 動的調整 |
| 基本手数料 | 自動調整 (最低 100 inu) | EIP-1559 方式 |
| 手数料バーン率 | 50% | デフレ圧力 |
| 最低ステーク | 1,000 BITA | バリデーターになるための最低額 |
| チェックポイント間隔 | 10 ブロック | ファイナリティ確定頻度 |
| UTXO レンタル猶予 | 100,000 ブロック (~70日) | レンタル料発生までの猶予 |
| 最小単位 | 1 inu = 0.00000001 BITA | Bitcoin の satoshi に相当 |
| アドレス接頭辞 | `A` (メインネット) | BitAkita のアドレスは A で始まる |

---

# ライセンス

Educational / Research use.
