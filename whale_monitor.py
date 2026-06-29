#!/usr/bin/env python3
"""
链上监控模块
- 巨鲸钱包监控
- 异常交易预警
- 大额转账追踪
"""
import os
import json
import requests
from datetime import datetime, timezone
from pathlib import Path
from polystrat_logger import log, log_error
from retry_helper import retry_request

# 缓存目录
from config_center import ONCHAIN_CACHE_DIR as CACHE_DIR
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# API 配置
ETHERSCAN_API = "https://api.etherscan.io/api"
SOLSCAN_API = "https://public-api.solscan.io"

# 巨鲸钱包列表（示例）
WHALE_WALLETS = {
    "ethereum": [
        "0x28C6c06298d514Db089934071355E5743bf21d60",  # Binance Hot Wallet
        "0x21a31Ee1afC51d94C2eFcCAa2092aD1028285549",  # Binance Cold Wallet
        "0x56Eddb7aa87536c09CCc2793473599fD21A8b17F",  # Coinbase
    ],
    "solana": [
        "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",  # Raydium
        "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM",  # Marinade
    ]
}

def get_eth_balance(address):
    """
    获取以太坊地址余额
    
    Args:
        address: 钱包地址
    
    Returns:
        dict: 余额信息
    """
    try:
        # 使用公开 API（无需 key）
        resp = requests.get(
            f"https://api.ethplorer.io/getAddressInfo/{address}",
            params={"apiKey": "freekey"},
            timeout=10
        )
        
        if resp.status_code == 200:
            data = resp.json()
            return {
                "address": address,
                "eth_balance": data.get("ETH", {}).get("balance", 0),
                "tokens": data.get("tokens", []),
                "success": True
            }
        else:
            return {"address": address, "success": False, "error": resp.status_code}
            
    except Exception as e:
        log_error("onchain", e, f"获取ETH余额失败: {address[:10]}")
        return {"address": address, "success": False, "error": str(e)}

def get_sol_balance(address):
    """
    获取 Solana 地址余额
    
    Args:
        address: 钱包地址
    
    Returns:
        dict: 余额信息
    """
    try:
        resp = requests.get(
            f"https://public-api.solscan.io/account/{address}",
            timeout=10
        )
        
        if resp.status_code == 200:
            data = resp.json()
            return {
                "address": address,
                "sol_balance": data.get("lamports", 0) / 1e9,  # 转换为 SOL
                "success": True
            }
        else:
            return {"address": address, "success": False, "error": resp.status_code}
            
    except Exception as e:
        log_error("onchain", e, f"获取SOL余额失败: {address[:10]}")
        return {"address": address, "success": False, "error": str(e)}

def get_recent_transactions(address, chain="ethereum", limit=10):
    """
    获取最近交易
    
    Args:
        address: 钱包地址
        chain: 链名称
        limit: 返回数量
    
    Returns:
        list: 交易列表
    """
    try:
        if chain == "ethereum":
            # 使用 Etherscan 公开 API
            resp = requests.get(
                ETHERSCAN_API,
                params={
                    "module": "account",
                    "action": "txlist",
                    "address": address,
                    "startblock": 0,
                    "endblock": 99999999,
                    "page": 1,
                    "offset": limit,
                    "sort": "desc"
                },
                timeout=10
            )
            
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "1":
                    txs = data.get("result", [])
                    return [{
                        "hash": tx.get("hash", ""),
                        "from": tx.get("from", ""),
                        "to": tx.get("to", ""),
                        "value": int(tx.get("value", 0)) / 1e18,  # 转换为 ETH
                        "timestamp": datetime.fromtimestamp(int(tx.get("timeStamp", 0)), tz=timezone.utc).isoformat(),
                        "chain": "ethereum"
                    } for tx in txs]
        
        return []
        
    except Exception as e:
        log_error("onchain", e, f"获取交易记录失败: {address[:10]}")
        return []

def monitor_whale_movements(threshold_eth=100):
    """
    监控巨鲸大额转账
    
    Args:
        threshold_eth: 阈值（ETH）
    
    Returns:
        list: 大额转账列表
    """
    movements = []
    
    for address in WHALE_WALLETS.get("ethereum", []):
        txs = get_recent_transactions(address, "ethereum", 5)
        
        for tx in txs:
            if tx.get("value", 0) >= threshold_eth:
                movements.append({
                    "type": "whale_transfer",
                    "chain": "ethereum",
                    "from": tx["from"][:10] + "...",
                    "to": tx["to"][:10] + "...",
                    "amount": tx["value"],
                    "unit": "ETH",
                    "hash": tx["hash"][:10] + "...",
                    "timestamp": tx["timestamp"]
                })
    
    return movements

def format_whale_report(movements):
    """
    格式化巨鲸报告
    
    Args:
        movements: 转账列表
    
    Returns:
        str: 报告内容
    """
    if not movements:
        return "未发现大额转账"
    
    lines = []
    lines.append("🐋 巨鲸监控报告")
    lines.append("=" * 50)
    lines.append(f"发现 {len(movements)} 笔大额转账")
    lines.append("")
    
    for m in movements[:10]:
        lines.append(f"  - {m['amount']:.2f} {m['unit']}")
        lines.append(f"    从: {m['from']}")
        lines.append(f"    到: {m['to']}")
        lines.append(f"    链: {m['chain']}")
        lines.append(f"    时间: {m['timestamp']}")
        lines.append("")
    
    return "\n".join(lines)

def get_whale_balances():
    """
    获取巨鲸钱包余额
    
    Returns:
        dict: 余额统计
    """
    balances = {
        "ethereum": [],
        "solana": []
    }
    
    # 以太坊巨鲸
    for address in WHALE_WALLETS.get("ethereum", [])[:3]:
        balance = get_eth_balance(address)
        if balance.get("success"):
            balances["ethereum"].append({
                "address": address[:10] + "...",
                "balance": balance.get("eth_balance", 0)
            })
    
    # Solana 巨鲸
    for address in WHALE_WALLETS.get("solana", [])[:3]:
        balance = get_sol_balance(address)
        if balance.get("success"):
            balances["solana"].append({
                "address": address[:10] + "...",
                "balance": balance.get("sol_balance", 0)
            })
    
    return balances

if __name__ == "__main__":
    print("=" * 50)
    print("链上监控测试")
    print("=" * 50)
    
    # 测试1: 监控巨鲸转账
    print("\n1. 监控巨鲸转账:")
    movements = monitor_whale_movements(threshold_eth=10)
    print(format_whale_report(movements))
    
    # 测试2: 获取巨鲸余额
    print("\n2. 获取巨鲸余额:")
    balances = get_whale_balances()
    
    print("  以太坊:")
    for b in balances["ethereum"]:
        print(f"    {b['address']}: {b['balance']:.2f} ETH")
    
    print("  Solana:")
    for b in balances["solana"]:
        print(f"    {b['address']}: {b['balance']:.2f} SOL")
    
    print("\n✅ 链上监控测试完成")
