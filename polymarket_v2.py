#!/usr/bin/env python3
"""
Polymarket CLOB V2 集成模块
- 使用 py-clob-client-v2 SDK
- 支持 pUSD 抵押
- Gasless 交易支持
"""
import os
import requests
from datetime import datetime, timezone
from pathlib import Path
from polystrat_logger import log, log_error

# Polymarket V2 API 配置
GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"  # V2 生产环境
DATA_API = "https://data-api.polymarket.com"

# V2 交易配置
DEFAULT_CONFIG = {
    "trade_size": 0.5,
    "markets_limit": 100,
    "max_positions": 5,
    "min_volume": 10000,
    "max_spread": 0.05,
    "signature_type": 1,  # 1=Magic Link, 0=EOA, 2=Safe
}

def get_v2_client():
    """
    获取 Polymarket V2 客户端
    
    Returns:
        ClobClient: V2 客户端实例
    """
    try:
        from py_clob_client.client import ClobClient
        
        private_key = os.environ.get("POLYMARKET_PRIVATE_KEY", "")
        funder_address = os.environ.get("POLYMARKET_FUNDER_ADDRESS", "")
        
        if not private_key or not funder_address:
            log.warning("Polymarket V2 密钥未配置")
            return None
        
        # V2 客户端初始化（使用 options 对象）
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
        
        log.info("Polymarket V2 客户端初始化成功")
        return client
        
    except ImportError:
        log.warning("py-clob-client-v2 未安装")
        return None
    except Exception as e:
        log_error("polymarket_v2", e, "初始化 V2 客户端失败")
        return None

def get_balance(client=None):
    """获取账户余额（pUSD）"""
    if client is None:
        return 1000.0
    
    try:
        from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
        
        balance = client.get_balance_allowance(
            BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
        )
        return int(balance["balance"]) / 1e6
    except Exception as e:
        log_error("polymarket_v2", e, "获取余额失败")
        return 0.0

def get_market_info(token_id, client=None):
    """获取市场信息（V2 动态费用）"""
    if client is None:
        return {"fee": 0.02}  # 默认 2%
    
    try:
        # V2: 查询市场特定费用
        info = client.get_clob_market_info(token_id)
        return {"fee": info.get("fee", 0.02)}
    except Exception as e:
        log_error("polymarket_v2", e, "获取市场信息失败")
        return {"fee": 0.02}

def place_order_v2(token_id, side, amount, price=None, client=None, builder_code=None):
    """
    V2 下单（支持 builder code）
    
    Args:
        token_id: 代币 ID
        side: 方向 (BUY/SELL)
        amount: 金额
        price: 价格（None=市价单）
        client: V2 客户端
        builder_code: Builder 归因代码（可选）
    """
    if client is None:
        return {"status": "DRY_RUN", "message": f"模拟 {side} ${amount:.2f}"}
    
    try:
        from py_clob_client.clob_types import OrderArgs, MarketOrderArgs, OrderType
        
        # V2: 使用 timestamp 替代 nonce
        order_args = {
            "token_id": token_id,
            "side": side,
        }
        
        if price is None:
            # 市价单 (FOK)
            order_args.update({
                "amount": amount,
                "order_type": OrderType.FOK,
            })
            if builder_code:
                order_args["builder"] = builder_code
            order = MarketOrderArgs(**order_args)
            signed = client.create_market_order(order)
            resp = client.post_order(signed, OrderType.FOK)
        else:
            # 限价单 (GTC)
            order_args.update({
                "price": price,
                "size": amount,
            })
            if builder_code:
                order_args["builder"] = builder_code
            order = OrderArgs(**order_args)
            signed = client.create_order(order)
            resp = client.post_order(signed, OrderType.GTC)
        
        return {"status": "SUCCESS", "response": resp}
    except Exception as e:
        log_error("polymarket_v2", e, f"V2 下单失败: {token_id[:10]}")
        return {"status": "ERROR", "message": str(e)}

def check_pusd_balance(client=None):
    """检查 pUSD 余额"""
    if client is None:
        return {"pusd": 1000.0, "usdc": 500.0}
    
    try:
        from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
        
        # 检查 pUSD 余额
        collateral = client.get_balance_allowance(
            BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
        )
        
        return {
            "pusd": int(collateral["balance"]) / 1e6,
        }
    except Exception as e:
        log_error("polymarket_v2", e, "检查 pUSD 余额失败")
        return {"pusd": 0.0}

def scan_markets_v2(category=None, min_price=0.03, max_price=0.97, min_volume=10000):
    """V2 市场扫描"""
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
                    price_list = eval(prices) if isinstance(prices, str) else prices
                    yes_price = float(price_list[0])
                except:
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
        log_error("polymarket_v2", e, "V2 扫描市场失败")
        return []

if __name__ == "__main__":
    print("=" * 50)
    print("Polymarket V2 集成测试")
    print("=" * 50)
    
    # 测试1: 初始化 V2 客户端
    print("\n1. 初始化 V2 客户端:")
    client = get_v2_client()
    print(f"   客户端: {'实盘' if client else '模拟'}")
    
    # 测试2: 检查 pUSD 余额
    print("\n2. 检查 pUSD 余额:")
    balance = check_pusd_balance(client)
    print(f"   pUSD: ${balance['pusd']:.2f}")
    
    # 测试3: 扫描市场
    print("\n3. V2 市场扫描:")
    markets = scan_markets_v2(min_volume=50000)
    print(f"   发现 {len(markets)} 个市场")
    for m in markets[:3]:
        print(f"   - {m['title'][:40]}...")
        print(f"     Yes: {m['yes_price']:.2f}, Volume: ${m['volume']:,.0f}")
    
    print("\n✅ Polymarket V2 集成测试完成")
