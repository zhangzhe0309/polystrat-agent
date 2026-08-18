#!/usr/bin/env python3
"""
CLOB Bid/Ask 价格校验模块 — PolyStrat v4.1
==========================================
解决 Gamma API (bid) vs CLOB API (ask) 价格不一致问题。

核心问题:
- Gamma API 返回的是 mid/last 价格（偏向bid）
- CLOB API 返回的是真实订单簿（bid/ask分离）
- 用Gamma价格计算edge，用CLOB执行，spread吃掉利润
- LayerX团队因此实盘亏37.81%

解决方案:
- 下单前用CLOB API重新查询真实bid/ask
- 计算真实spread，如果spread>阈值则跳过
- 用ask价格重新计算edge（保守估计）

作者: PolyStrat Team
日期: 2026-07-08
"""

import json
import requests
from datetime import datetime, timezone

# ============ 配置 ============

CLOB_API = "https://clob.polymarket.com"

SPREAD_CONFIG = {
    "enabled": True,
    "max_spread_pct": 0.05,       # 最大允许spread 5%
    "edge_recalc": True,          # 用ask价重新计算edge
    "min_liquidity_usd": 100,     # 订单簿最低流动性
    "timeout": 10,                # CLOB API超时
    "cache_seconds": 30,          # 缓存30秒（避免重复查询）
}


# ============ 缓存 ============

_price_cache = {}


def get_clob_orderbook(token_id, side="buy"):
    """
    从CLOB API获取真实订单簿
    
    Args:
        token_id: 市场的token ID
        side: "buy"=查ask(你要付的价格), "sell"=查bid(你能卖的价格)
    
    Returns:
        dict: {
            "best_ask": float,     # 最优ask价（买入时支付）
            "best_bid": float,     # 最优bid价（卖出时收到）
            "spread": float,       # spread (ask-bid)
            "spread_pct": float,   # spread百分比
            "mid_price": float,    # 中间价
            "depth_usd": float,    # 订单簿深度(USD)
            "success": bool,
            "error": str,
        }
    """
    config = SPREAD_CONFIG
    if not config["enabled"]:
        return _default_orderbook("价格校验未启用")
    
    # 检查缓存
    cache_key = f"{token_id}_{side}"
    now = datetime.now(timezone.utc).timestamp()
    if cache_key in _price_cache:
        cached = _price_cache[cache_key]
        if now - cached["timestamp"] < config["cache_seconds"]:
            cached_result = {k: v for k, v in cached.items() if k != "timestamp"}
            cached_result["cached"] = True
            return cached_result
    
    try:
        resp = requests.get(
            f"{CLOB_API}/book",
            params={"token_id": token_id},
            timeout=config["timeout"],
        )
        resp.raise_for_status()
        data = resp.json()
        
        # 解析订单簿
        asks = data.get("asks", [])
        bids = data.get("bids", [])
        
        best_ask = 0.0
        best_bid = 0.0
        depth_usd = 0.0
        
        if asks:
            # asks按价格升序，第一个是最优ask
            try:
                sorted_asks = sorted(asks, key=lambda x: float(x.get("price", 1)))
                best_ask = float(sorted_asks[0].get("price", 0))
                # 计算深度
                for a in sorted_asks[:5]:
                    depth_usd += float(a.get("size", 0)) * float(a.get("price", 0))
            except (ValueError, IndexError):
                best_ask = 0.0
        
        if bids:
            # bids按价格降序，第一个是最优bid
            try:
                sorted_bids = sorted(bids, key=lambda x: float(x.get("price", 0)), reverse=True)
                best_bid = float(sorted_bids[0].get("price", 0))
            except (ValueError, IndexError):
                best_bid = 0.0
        
        spread = best_ask - best_bid if best_ask > 0 and best_bid > 0 else 0
        spread_pct = spread / best_bid if best_bid > 0 else 0
        mid_price = (best_ask + best_bid) / 2 if best_ask > 0 and best_bid > 0 else 0
        
        result = {
            "best_ask": best_ask,
            "best_bid": best_bid,
            "spread": spread,
            "spread_pct": spread_pct,
            "mid_price": mid_price,
            "depth_usd": depth_usd,
            "raw_bids": bids,
            "raw_asks": asks,
            "success": True,
            "error": "",
            "cached": False,
        }
        
        # 更新缓存
        _price_cache[cache_key] = {**result, "timestamp": now}
        
        return result
        
    except requests.Timeout:
        return _default_orderbook("CLOB API超时")
    except requests.HTTPError as e:
        return _default_orderbook(f"CLOB API HTTP {e.response.status_code}")
    except Exception as e:
        return _default_orderbook(f"CLOB查询失败: {type(e).__name__}")


def validate_price_before_trade(market, intended_direction, intended_price, token_id):
    """
    下单前价格校验
    
    Args:
        market: 市场信息 dict
        intended_direction: "Yes" or "No"
        intended_price: 打算下单的价格
        token_id: 对应的token ID
    
    Returns:
        dict: {
            "valid": bool,             # 是否可以下单
            "real_price": float,       # 真实需要支付的价格(ask)
            "spread_pct": float,       # 真实spread
            "edge_after_spread": float, # 扣除spread后的edge
            "original_price": float,   # Gamma API价格
            "price_slippage": float,   # 价格偏差
            "reason": str,             # 原因说明
        }
    """
    config = SPREAD_CONFIG
    if not config["enabled"]:
        return {
            "valid": True,
            "real_price": intended_price,
            "spread_pct": 0,
            "edge_after_spread": 0,
            "original_price": intended_price,
            "price_slippage": 0,
            "reason": "价格校验未启用",
        }
    
    if not token_id:
        return {
            "valid": False,
            "real_price": intended_price,
            "spread_pct": 0,
            "edge_after_spread": 0,
            "original_price": intended_price,
            "price_slippage": 0,
            "reason": "缺少token_id",
        }
    
    # 查询CLOB真实订单簿
    orderbook = get_clob_orderbook(token_id)
    
    if not orderbook["success"]:
        # CLOB查询失败，保守放行（不阻塞交易）
        return {
            "valid": True,
            "real_price": intended_price,
            "spread_pct": 0,
            "edge_after_spread": 0,
            "original_price": intended_price,
            "price_slippage": 0,
            "reason": f"CLOB查询失败({orderbook['error']})，保守放行",
        }
    
    # 🔧 买入 Yes/No token 的成本都是该 token 的 best_ask
    # direction=No 时下单是 BUY no_token，成本 = no_token.best_ask（原误用 best_bid）
    if intended_direction in ("Yes", "No"):
        real_price = orderbook["best_ask"] if orderbook["best_ask"] > 0 else intended_price
    else:
        real_price = orderbook["best_bid"] if orderbook["best_bid"] > 0 else intended_price
    
    spread_pct = orderbook["spread_pct"]
    price_slippage = real_price - intended_price
    
    # 检查spread
    if spread_pct > config["max_spread_pct"]:
        return {
            "valid": False,
            "real_price": real_price,
            "spread_pct": spread_pct,
            "edge_after_spread": 0,
            "original_price": intended_price,
            "price_slippage": price_slippage,
            "reason": f"Spread {spread_pct:.1%}>{config['max_spread_pct']:.0%}，利润被吃掉",
        }
    
    # 检查深度
    if orderbook["depth_usd"] < config["min_liquidity_usd"]:
        return {
            "valid": False,
            "real_price": real_price,
            "spread_pct": spread_pct,
            "edge_after_spread": 0,
            "original_price": intended_price,
            "price_slippage": price_slippage,
            "reason": f"订单簿深度不足 ${orderbook['depth_usd']:.0f}<${config['min_liquidity_usd']}",
        }
    
    return {
        "valid": True,
        "real_price": real_price,
        "spread_pct": spread_pct,
        "edge_after_spread": max(0, (1 - real_price) - (1 - intended_price)),
        "original_price": intended_price,
        "price_slippage": price_slippage,
        "reason": f"价格校验通过 spread={spread_pct:.1%} slippage={price_slippage:+.2f}¢",
    }


def validate_sell_depth(token_id, sell_shares, min_acceptable_price=None, max_slippage_pct=0.10):
    """
    卖出/平仓前订单簿深度与滑点校验（防止在流动性真空期盲目砸盘）
    
    Args:
        token_id: 合约 token ID
        sell_shares: 拟卖出的份额数
        min_acceptable_price: 最低可接受卖出价格（可选）
        max_slippage_pct: 允许的最大加权滑点比例（默认 10%）
        
    Returns:
        dict: {
            "valid": bool,
            "best_bid": float,
            "weighted_bid_price": float,
            "available_bid_shares": float,
            "slippage_pct": float,
            "reason": str,
        }
    """
    config = SPREAD_CONFIG
    if not config.get("enabled", True):
        return {
            "valid": True,
            "best_bid": 0.0,
            "weighted_bid_price": 0.0,
            "available_bid_shares": sell_shares,
            "slippage_pct": 0.0,
            "reason": "校验未启用",
        }
        
    if not token_id or sell_shares <= 0:
        return {
            "valid": False,
            "best_bid": 0.0,
            "weighted_bid_price": 0.0,
            "available_bid_shares": 0.0,
            "slippage_pct": 0.0,
            "reason": "无效的 token_id 或 sell_shares",
        }
        
    orderbook = get_clob_orderbook(token_id, side="sell")
    if not orderbook.get("success"):
        return {
            "valid": True,
            "best_bid": 0.0,
            "weighted_bid_price": 0.0,
            "available_bid_shares": sell_shares,
            "slippage_pct": 0.0,
            "reason": f"CLOB 查询失败({orderbook.get('error')})，保守放行",
        }
        
    best_bid = orderbook.get("best_bid", 0.0)
    raw_bids = orderbook.get("raw_bids", [])
    
    if best_bid <= 0 or not raw_bids:
        return {
            "valid": False,
            "best_bid": 0.0,
            "weighted_bid_price": 0.0,
            "available_bid_shares": 0.0,
            "slippage_pct": 1.0,
            "reason": "买盘无挂单(Best Bid=0)，存在流动性真空",
        }
        
    # 计算多档买盘深度与加权均价
    sorted_bids = sorted(raw_bids, key=lambda x: float(x.get("price", 0)), reverse=True)
    accum_shares = 0.0
    accum_value = 0.0
    
    for b in sorted_bids:
        p = float(b.get("price", 0))
        s = float(b.get("size", 0))
        if p <= 0 or s <= 0:
            continue
        needed = sell_shares - accum_shares
        take = min(s, needed)
        accum_shares += take
        accum_value += take * p
        if accum_shares >= sell_shares:
            break
            
    total_depth_shares = sum(float(b.get("size", 0)) for b in sorted_bids if float(b.get("price", 0)) > 0)
    weighted_price = (accum_value / accum_shares) if accum_shares > 0 else 0.0
    slippage_pct = (best_bid - weighted_price) / best_bid if best_bid > 0 else 0.0
    
    # 深度不足判断
    if accum_shares < sell_shares * 0.5:
        return {
            "valid": False,
            "best_bid": best_bid,
            "weighted_bid_price": weighted_price,
            "available_bid_shares": total_depth_shares,
            "slippage_pct": slippage_pct,
            "reason": f"买盘深度不足: 仅可承接 {accum_shares:.1f}/{sell_shares:.1f} 份额",
        }
        
    if slippage_pct > max_slippage_pct:
        return {
            "valid": False,
            "best_bid": best_bid,
            "weighted_bid_price": weighted_price,
            "available_bid_shares": total_depth_shares,
            "slippage_pct": slippage_pct,
            "reason": f"平仓加权滑点过大: {slippage_pct:.1%} > {max_slippage_pct:.1%}",
        }
        
    if min_acceptable_price and weighted_price < min_acceptable_price:
        return {
            "valid": False,
            "best_bid": best_bid,
            "weighted_bid_price": weighted_price,
            "available_bid_shares": total_depth_shares,
            "slippage_pct": slippage_pct,
            "reason": f"加权均价 ${weighted_price:.4f} 低于最低限制 ${min_acceptable_price:.4f}",
        }
        
    return {
        "valid": True,
        "best_bid": best_bid,
        "weighted_bid_price": weighted_price,
        "available_bid_shares": total_depth_shares,
        "slippage_pct": slippage_pct,
        "reason": f"深度充足, 加权均价 ${weighted_price:.4f} (滑点 {slippage_pct:.1%})",
    }


def _default_orderbook(error_msg):
    """返回默认的订单簿数据（查询失败时）"""
    return {
        "best_ask": 0,
        "best_bid": 0,
        "spread": 0,
        "spread_pct": 0,
        "mid_price": 0,
        "depth_usd": 0,
        "success": False,
        "error": error_msg,
        "cached": False,
    }


# ============ 自测 ============
if __name__ == "__main__":
    print("=== CLOB Bid/Ask 价格校验测试 ===\n")
    
    # 用一个真实的token_id测试
    test_token = "21742633143463906290569050155826241533067272736897614950488156847949938836455"
    print(f"📊 查询token: {test_token[:20]}...")
    book = get_clob_orderbook(test_token)
    print(f"   Ask={book.get('best_ask', 'N/A')} Bid={book.get('best_bid', 'N/A')} Spread={book.get('spread_pct', 0):.1%}")
    print(f"   成功={book['success']} {book.get('error', '')}")
    
    # 价格校验测试
    print(f"\n📊 价格校验测试:")
    validation = validate_price_before_trade(
        market={"title": "Test Market"},
        intended_direction="Yes",
        intended_price=0.65,
        token_id=test_token,
    )
    print(f"   Valid={validation['valid']} | Real={validation['real_price']} | Spread={validation['spread_pct']:.1%}")
    print(f"   原因: {validation['reason']}")
