#!/usr/bin/env python3
"""
Polymarket 自动化工具集成模块
- 使用官方 py-clob-client-v2 SDK
- 增强市场扫描
- 订单簿分析
- 仓位管理
"""
import os
import requests
from datetime import datetime, timezone
from pathlib import Path
from polystrat_logger import log, log_error

# Polymarket API 配置
GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"
DATA_API = "https://data-api.polymarket.com"

# 交易配置
DEFAULT_CONFIG = {
    "trade_size": 0.5,           # 每笔交易占余额比例
    "markets_limit": 100,        # 最大市场数
    "max_positions": 5,          # 最大持仓数
    "min_volume": 10000,         # 最小交易量
    "max_spread": 0.05,          # 最大价差
    "signature_type": 1,         # 签名类型
}

def get_client():
    """
    获取 Polymarket 客户端
    
    Returns:
        ClobClient: 客户端实例
    """
    try:
        from py_clob_client.client import ClobClient
        
        private_key = os.environ.get("POLYMARKET_PRIVATE_KEY", "")
        funder_address = os.environ.get("POLYMARKET_FUNDER_ADDRESS", "")
        
        if not private_key or not funder_address:
            log.warning("Polymarket 密钥未配置")
            return None
        
        client = ClobClient(
            CLOB_API,
            key=private_key,
            chain_id=137,
            signature_type=DEFAULT_CONFIG["signature_type"],
            funder=funder_address,
        )
        
        # 获取 API 凭证
        creds = client.derive_api_key()
        client.set_api_creds(creds)
        
        return client
        
    except ImportError:
        log.warning("py-clob-client-v2 未安装，使用模拟模式")
        return None
    except Exception as e:
        log_error("polymarket", e, "初始化客户端失败")
        return None

def get_balance(client=None):
    """
    获取账户余额
    
    Args:
        client: Polymarket 客户端
    
    Returns:
        float: 余额 (USDC)
    """
    if client is None:
        return 1000.0  # 模拟余额
    
    try:
        from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
        
        balance = client.get_balance_allowance(
            BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
        )
        return int(balance["balance"]) / 1e6
    except Exception as e:
        log_error("polymarket", e, "获取余额失败")
        return 0.0

def get_price(token_id, client=None):
    """
    获取代币价格
    
    Args:
        token_id: 代币 ID
        client: Polymarket 客户端
    
    Returns:
        dict: 价格信息
    """
    if client is None:
        return {"midpoint": 0.5, "best_ask": 0.51, "best_bid": 0.49, "spread": 0.02}
    
    try:
        return {
            "midpoint": float(client.get_midpoint(token_id)["mid"]),
            "best_ask": float(client.get_price(token_id, side="BUY")["price"]),
            "best_bid": float(client.get_price(token_id, side="SELL")["price"]),
            "spread": float(client.get_spread(token_id)["spread"]),
        }
    except Exception as e:
        log_error("polymarket", e, f"获取价格失败: {token_id[:10]}")
        return None

def get_positions(address=None, client=None):
    """
    获取当前持仓
    
    Args:
        address: 钱包地址
        client: Polymarket 客户端
    
    Returns:
        list: 持仓列表
    """
    try:
        addr = address or os.environ.get("POLYMARKET_FUNDER_ADDRESS", "")
        if not addr:
            return []
        
        resp = requests.get(
            f"{DATA_API}/positions",
            params={"user": addr},
            timeout=15
        )
        
        if resp.status_code == 200:
            return resp.json()
        return []
    except Exception as e:
        log_error("polymarket", e, "获取持仓失败")
        return []

def place_order(token_id, side, amount, price=None, client=None):
    """
    下单
    
    Args:
        token_id: 代币 ID
        side: 方向 (BUY/SELL)
        amount: 金额
        price: 价格（None=市价单）
        client: Polymarket 客户端
    
    Returns:
        dict: 订单结果
    """
    if client is None:
        return {"status": "DRY_RUN", "message": f"模拟 {side} ${amount:.2f}"}
    
    try:
        from py_clob_client.clob_types import OrderArgs, MarketOrderArgs, OrderType
        
        if price is None:
            # 市价单 (FOK)
            order = MarketOrderArgs(
                token_id=token_id,
                amount=amount,
                side=side,
                order_type=OrderType.FOK
            )
            signed = client.create_market_order(order)
            resp = client.post_order(signed, OrderType.FOK)
        else:
            # 限价单 (GTC)
            order = OrderArgs(
                token_id=token_id,
                price=price,
                size=amount,
                side=side
            )
            signed = client.create_order(order)
            resp = client.post_order(signed, OrderType.GTC)
        
        return {"status": "SUCCESS", "response": resp}
    except Exception as e:
        log_error("polymarket", e, f"下单失败: {token_id[:10]}")
        return {"status": "ERROR", "message": str(e)}

def scan_markets(category=None, min_price=0.03, max_price=0.97, min_volume=10000):
    """
    扫描市场
    
    Args:
        category: 类别过滤
        min_price: 最低价格
        max_price: 最高价格
        min_volume: 最小交易量
    
    Returns:
        list: 市场列表
    """
    try:
        params = {
            "limit": DEFAULT_CONFIG["markets_limit"],
            "active": True,
            "closed": False
        }
        
        if category:
            params["tag"] = category
        
        resp = requests.get(f"{GAMMA_API}/markets", params=params, timeout=15)
        
        if resp.status_code == 200:
            markets = resp.json()
            
            filtered = []
            for m in markets:
                prices = m.get("outcomePrices", "[0.5]")
                try:
                    import json as _json
                    price_list = _json.loads(prices) if isinstance(prices, str) else prices
                    yes_price = float(price_list[0])
                except Exception:
                    continue
                
                volume = float(m.get("volume", 0))
                
                if min_price <= yes_price <= max_price and volume >= min_volume:
                    filtered.append({
                        "id": m.get("conditionId", ""),
                        "title": m.get("question", ""),
                        "yes_price": yes_price,
                        "no_price": 1 - yes_price,
                        "volume": volume,
                        "liquidity": float(m.get("liquidityNum", 0)),
                        "yes_token": m.get("clobTokenIds", ["", ""])[0],
                        "no_token": m.get("clobTokenIds", ["", ""])[1] if len(m.get("clobTokenIds", [])) > 1 else "",
                    })
            
            return filtered
        return []
    except Exception as e:
        log_error("polymarket", e, "扫描市场失败")
        return []

def format_position_report(positions):
    """
    格式化持仓报告
    
    Args:
        positions: 持仓列表
    
    Returns:
        str: 报告内容
    """
    if not positions:
        return "无持仓"
    
    lines = []
    lines.append("📊 Polymarket 持仓报告")
    lines.append("=" * 50)
    lines.append(f"持仓数量: {len(positions)}")
    lines.append("")
    
    for p in positions[:10]:
        title = p.get("title", "")[:40]
        size = p.get("size", 0)
        value = p.get("currentValue", 0)
        pnl = p.get("pnl", 0)
        
        lines.append(f"  - {title}")
        lines.append(f"    数量: {size:.2f}, 价值: ${value:.2f}, 盈亏: {pnl:+.2f}")
    
    return "\n".join(lines)

if __name__ == "__main__":
    print("=" * 50)
    print("Polymarket 集成测试")
    print("=" * 50)
    
    # 测试1: 获取客户端
    print("\n1. 初始化客户端:")
    client = get_client()
    print(f"   客户端: {'实盘' if client else '模拟'}")
    
    # 测试2: 获取余额
    print("\n2. 获取余额:")
    balance = get_balance(client)
    print(f"   余额: ${balance:.2f}")
    
    # 测试3: 扫描市场
    print("\n3. 扫描市场:")
    markets = scan_markets(min_volume=50000)
    print(f"   发现 {len(markets)} 个市场")
    for m in markets[:3]:
        print(f"   - {m['title'][:40]}...")
        print(f"     Yes: {m['yes_price']:.2f}, No: {m['no_price']:.2f}")
    
    # 测试4: 获取持仓
    print("\n4. 获取持仓:")
    positions = get_positions(client=client)
    print(f"   持仓: {len(positions)} 个")
    
    print("\n✅ Polymarket 集成测试完成")
