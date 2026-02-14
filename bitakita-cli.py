#!/usr/bin/env python3
"""
bitakita-cli - BitAkita Command Line Interface

デーモン (bitakitad) と通信して操作を行う。

使い方:
    python bitakita-cli.py getinfo             # ノード情報
    python bitakita-cli.py getbalance           # 残高確認
    python bitakita-cli.py getaddress           # 自分のアドレス
    python bitakita-cli.py newaddress           # 新しいアドレス生成
    python bitakita-cli.py send <address> <amount_inu>  # 送金
    python bitakita-cli.py mine [count]         # ブロック採掘
    python bitakita-cli.py startmining          # 自動採掘開始
    python bitakita-cli.py stopmining           # 自動採掘停止
    python bitakita-cli.py getblock [height]    # ブロック情報
    python bitakita-cli.py getmempool           # メモリプール
    python bitakita-cli.py getutxos             # UTXO一覧
    python bitakita-cli.py connect <host> <port> # ピア接続
    python bitakita-cli.py getpeers             # ピア一覧
"""

import json
import socket
import sys


DEFAULT_RPC_HOST = "127.0.0.1"
DEFAULT_RPC_PORT = 18332

# Set by main() when --rpc-port is specified
_rpc_port = DEFAULT_RPC_PORT


def rpc_call(method: str, params: dict = None, host: str = DEFAULT_RPC_HOST, port: int = None) -> dict:
    if port is None:
        port = _rpc_port
    """Send an RPC request to the daemon."""
    request = json.dumps({
        "method": method,
        "params": params or {},
    }) + "\n"

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(30)
        sock.connect((host, port))
        sock.sendall(request.encode())

        # Read response
        data = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
            if b"\n" in data:
                break

        sock.close()
        response = json.loads(data.decode())

        if response.get("error"):
            print(f"Error: {response['error']}")
            sys.exit(1)

        return response.get("result", {})

    except ConnectionRefusedError:
        print(f"Error: デーモンに接続できません ({host}:{port})")
        print(f"  bitakitad を起動してください: python bitakitad.py")
        sys.exit(1)
    except socket.timeout:
        print("Error: RPC タイムアウト")
        sys.exit(1)


def fmt(inu: int) -> str:
    return f"{inu / 1_0000_0000:.8f} BITA"


def cmd_getinfo():
    info = rpc_call("getinfo")
    print("=== BitAkita Node Info ===")
    print(f"  ブロック高:       {info['height']}")
    print(f"  接続ピア数:       {info['peers']}")
    print(f"  メモリプール:     {info['mempool']} tx")
    print(f"  UTXO数:           {info['utxo_count']}")
    print(f"  総発行量:         {fmt(info['total_supply'])}")
    print(f"  バーン済み:       {fmt(info['total_burned'])}")
    print(f"  流通量:           {fmt(info['circulating'])}")
    print(f"  手数料(base):     {info['base_fee']} inu/byte")
    print(f"  マイニング中:     {'はい' if info['mining'] else 'いいえ'}")
    print(f"  バリデーター数:   {info['validators']}")
    print(f"  ファイナライズ高: {info['finalized_height']}")


def cmd_getbalance():
    result = rpc_call("getbalance")
    print("=== 残高 ===")
    print(f"  総残高:       {result['balance_bita']:.8f} BITA ({result['balance']} inu)")
    print(f"  使用可能:     {result['spendable_bita']:.8f} BITA ({result['spendable']} inu)")


def cmd_getaddress():
    result = rpc_call("getaddress")
    print(f"  メインアドレス: {result['address']}")
    if len(result["all_addresses"]) > 1:
        print(f"  全アドレス:")
        for addr in result["all_addresses"]:
            print(f"    {addr}")


def cmd_newaddress():
    result = rpc_call("newaddress")
    print(f"  新しいアドレス: {result['address']}")


def cmd_send(address: str, amount: str):
    amount_inu = int(float(amount) * 1_0000_0000)
    result = rpc_call("send", {"to": address, "amount": amount_inu})
    if result["success"]:
        print(f"  送金成功!")
        print(f"  TXID: {result['txid']}")
        print(f"  {result['message']}")
    else:
        print(f"  送金失敗: {result['message']}")


def cmd_mine(count: int = 1):
    print(f"  {count} ブロック採掘中...")
    result = rpc_call("mine", {"count": count})
    print(f"  採掘完了: {result['mined']} ブロック")
    print(f"  現在のブロック高: {result['height']}")


def cmd_startmining():
    result = rpc_call("startmining")
    print("  自動採掘を開始しました")


def cmd_stopmining():
    result = rpc_call("stopmining")
    print("  自動採掘を停止しました")


def cmd_getblock(height: str = None):
    params = {}
    if height is not None:
        params["height"] = int(height)
    result = rpc_call("getblock", params)
    if "error" in result:
        print(f"  {result['error']}")
        return
    print(f"=== Block {result['height']} ===")
    print(f"  ハッシュ:       {result['hash'][:32]}...")
    print(f"  前ブロック:     {result['prev_hash'][:32]}...")
    print(f"  タイムスタンプ: {result['timestamp']}")
    print(f"  ナンス:         {result['nonce']}")
    print(f"  トランザクション: {result['tx_count']}")
    print(f"  サイズ:         {result['size']} bytes")
    print(f"  基本手数料:     {result['base_fee']} inu/byte")


def cmd_getmempool():
    result = rpc_call("getmempool")
    print(f"=== メモリプール ({result['count']} tx) ===")
    for tx in result["transactions"]:
        print(f"  {tx['txid'][:32]}... ({tx['size']}B, {tx['inputs']}in/{tx['outputs']}out)")


def cmd_getutxos():
    result = rpc_call("getutxos")
    print(f"=== UTXO一覧 ({result['count']} 個) ===")
    total = 0
    for u in result["utxos"]:
        print(f"  {u['amount_bita']:.8f} BITA  (block {u['block_height']}, {u['txid'][:16]}...:{u['index']})")
        total += u["amount"]
    print(f"  合計: {fmt(total)}")


def cmd_connect(host: str, port: str):
    result = rpc_call("connect", {"host": host, "port": int(port)})
    if result["connected"]:
        print(f"  {result['peer']} に接続しました")
    else:
        print(f"  接続に失敗しました")


def cmd_getpeers():
    result = rpc_call("getpeers")
    print(f"=== ピア一覧 ({result['count']}) ===")
    for p in result["peers"]:
        direction = "← inbound" if p["inbound"] else "→ outbound"
        print(f"  {p['address']}  {direction}  id={p['node_id']}  height={p['height']}")


def print_help():
    print("BitAkita CLI - 使い方:")
    print()
    print("  python bitakita-cli.py <command> [args...]")
    print()
    print("コマンド:")
    print("  getinfo                    ノード情報を表示")
    print("  getbalance                 残高を確認")
    print("  getaddress                 自分のアドレスを表示")
    print("  newaddress                 新しいアドレスを生成")
    print("  send <address> <amount>    送金 (amount は BITA 単位)")
    print("  mine [count]               手動でブロックを採掘")
    print("  startmining                自動採掘を開始")
    print("  stopmining                 自動採掘を停止")
    print("  getblock [height]          ブロック情報を表示")
    print("  getmempool                 メモリプールの内容")
    print("  getutxos                   自分のUTXO一覧")
    print("  connect <host> <port>      ピアに接続")
    print("  getpeers                   接続中のピア一覧")
    print()
    print("例:")
    print("  python bitakita-cli.py mine 5")
    print("  python bitakita-cli.py send AKzZJVjjKCk57LjGKoxGW4BxCGjxBRfrPG 10")
    print("  python bitakita-cli.py connect 192.168.1.5 18333")


def main():
    if len(sys.argv) < 2:
        print_help()
        return

    # Check for --rpc-port flag
    global _rpc_port
    args = list(sys.argv[1:])
    if "--rpc-port" in args:
        idx = args.index("--rpc-port")
        _rpc_port = int(args[idx + 1])
        args = args[:idx] + args[idx + 2:]

    cmd = args[0]

    if cmd == "getinfo":
        cmd_getinfo()
    elif cmd == "getbalance":
        cmd_getbalance()
    elif cmd == "getaddress":
        cmd_getaddress()
    elif cmd == "newaddress":
        cmd_newaddress()
    elif cmd == "send":
        if len(args) < 3:
            print("使い方: send <address> <amount_bita>")
            return
        cmd_send(args[1], args[2])
    elif cmd == "mine":
        count = int(args[1]) if len(args) > 1 else 1
        cmd_mine(count)
    elif cmd == "startmining":
        cmd_startmining()
    elif cmd == "stopmining":
        cmd_stopmining()
    elif cmd == "getblock":
        height = args[1] if len(args) > 1 else None
        cmd_getblock(height)
    elif cmd == "getmempool":
        cmd_getmempool()
    elif cmd == "getutxos":
        cmd_getutxos()
    elif cmd == "connect":
        if len(args) < 3:
            print("使い方: connect <host> <port>")
            return
        cmd_connect(args[1], args[2])
    elif cmd == "getpeers":
        cmd_getpeers()
    elif cmd in ("help", "--help", "-h"):
        print_help()
    else:
        print(f"Unknown command: {cmd}")
        print_help()


if __name__ == "__main__":
    main()
