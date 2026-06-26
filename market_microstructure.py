#!/usr/bin/env python3
"""
市场微观结构信号模块
- 订单簿深度分析
- 买卖价差监控
- 成交量动量
- 价格动量
- 流动性变化趋势
"""

import requests
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from polystrat_logger import log, log_error

# Polymarket API
GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"

# 缓存配置
CACHE_DIR = Path("/root/.hermes/profiles/life/data/market_microstructure")
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_TTL_HOURS = 1  # 缓存有效期 1 小时


def get_cache_path(market_slug):
    """获取缓存文件路径"""
    return CACHE_DIR / f"{market_slug}.json"


def load_cached_data(market_slug):
    """加载缓存数据"""
    cache_path = get_cache_path(market_slug)
    if not cache_path.exists():
        return None

    try:
        with open(cache_path, "r") as f:
            data = json.load(f)

        # 检查缓存是否过期
        cached_at = datetime.fromisoformat(data.get("cached_at", "2000-01-01T00:00:00+00:00"))
        if datetime.now(timezone.utc) - cached_at > timedelta(hours=CACHE_TTL_HOURS):
            return None

        return data
    except Exception:
        return None


def save_cached_data(market_slug, data):
    """保存缓存数据"""
    cache_path = get_cache_path(market_slug)
    try:
        data["cached_at"] = datetime.now(timezone.utc).isoformat()
        with open(cache_path, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        log_error("market_microstructure", e, f"保存缓存失败: {market_slug}")


def get_order_book_depth(token_id):
    """
    获取订单簿深度

    Args:
        token_id: 代币 ID

    Returns:
        dict: 订单簿深度数据
    """
    try:
        # 使用 CLOB API 获取订单簿
        resp = requests.get(
            f"{CLOB_API}/book",
            params={"token_id": token_id},
            timeout=10
        )

        if resp.status_code == 200:
            book = resp.json()

            # 分析买单和卖单深度
            bids = book.get("bids", [])
            asks = book.get("asks", [])

            # 计算深度（前5档）
            bid_depth = sum(float(b.get("size", 0)) for b in bids[:5])
            ask_depth = sum(float(a.get("size", 0)) for a in asks[:5])

            # 计算买卖价差
            best_bid = float(bids[0]["price"]) if bids else 0
            best_ask = float(asks[0]["price"]) if asks else 0
            spread = best_ask - best_bid if best_ask > 0 and best_bid > 0 else 0
            spread_pct = spread / best_bid if best_bid > 0 else 0

            return {
                "bid_depth": bid_depth,
                "ask_depth": ask_depth,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "spread": spread,
                "spread_pct": spread_pct,
                "depth_ratio": bid_depth / ask_depth if ask_depth > 0 else 1.0,
            }

        return None
    except Exception as e:
        log_error("market_microstructure", e, f"获取订单簿失败: {token_id[:10]}")
        return None


def get_volume_momentum(condition_id, hours=24):
    """
    获取成交量动量

    Args:
        condition_id: 市场条件 ID
        hours: 时间窗口（小时）

    Returns:
        dict: 成交量动量数据
    """
    try:
        # 使用 Gamma API 获取市场数据
        resp = requests.get(
            f"{GAMMA_API}/markets",
            params={"conditionId": condition_id},
            timeout=10
        )

        if resp.status_code == 200:
            markets = resp.json()
            if markets:
                market = markets[0]

                # 获取当前成交量
                current_volume = float(market.get("volume", 0))
                liquidity = float(market.get("liquidityNum", 0))

                # 计算成交量/流动性比率
                volume_liquidity_ratio = current_volume / liquidity if liquidity > 0 else 0

                return {
                    "current_volume": current_volume,
                    "liquidity": liquidity,
                    "volume_liquidity_ratio": volume_liquidity_ratio,
                }

        return None
    except Exception as e:
        log_error("market_microstructure", e, f"获取成交量失败: {condition_id[:10]}")
        return None


def get_price_momentum(condition_id, hours=24):
    """
    获取价格动量

    Args:
        condition_id: 市场条件 ID
        hours: 时间窗口（小时）

    Returns:
        dict: 价格动量数据
    """
    try:
        # 使用 Gamma API 获取市场数据
        resp = requests.get(
            f"{GAMMA_API}/markets",
            params={"conditionId": condition_id},
            timeout=10
        )

        if resp.status_code == 200:
            markets = resp.json()
            if markets:
                market = markets[0]

                # 获取当前价格
                prices = market.get("outcomePrices", "[0.5]")
                if isinstance(prices, str):
                    price_list = json.loads(prices)
                else:
                    price_list = prices

                current_price = float(price_list[0]) if price_list else 0.5

                # 注意：Polymarket API 不提供历史价格
                # 这里只返回当前价格，价格变化需要通过缓存历史数据计算
                return {
                    "current_price": current_price,
                    "price_change_24h": 0,  # 需要历史数据
                    "price_change_7d": 0,   # 需要历史数据
                }

        return None
    except Exception as e:
        log_error("market_microstructure", e, f"获取价格动量失败: {condition_id[:10]}")
        return None


def calculate_microstructure_signal(condition_id, token_id, market_slug=None):
    """
    计算市场微观结构信号

    Args:
        condition_id: 市场条件 ID
        token_id: 代币 ID
        market_slug: 市场 slug（用于缓存）

    Returns:
        dict: 微观结构信号
    """
    # 检查缓存
    if market_slug:
        cached = load_cached_data(market_slug)
        if cached:
            return cached

    # 获取订单簿深度
    order_book = get_order_book_depth(token_id)

    # 获取成交量动量
    volume_data = get_volume_momentum(condition_id)

    # 获取价格动量
    price_data = get_price_momentum(condition_id)

    # 计算综合信号
    signal = {
        "order_book": order_book,
        "volume": volume_data,
        "price": price_data,
        "recommendation": "hold",
        "confidence": 0.3,
        "factors": [],
    }

    # 分析订单簿
    if order_book:
        spread_pct = order_book.get("spread_pct", 0)
        depth_ratio = order_book.get("depth_ratio", 1.0)

        # 价差分析
        if spread_pct < 0.02:  # 价差 < 2%
            signal["factors"].append("tight_spread")
        elif spread_pct > 0.10:  # 价差 > 10%
            signal["factors"].append("wide_spread")

        # 深度分析
        if depth_ratio > 1.5:  # 买盘深度 > 卖盘 1.5 倍
            signal["factors"].append("buy_pressure")
        elif depth_ratio < 0.67:  # 卖盘深度 > 买盘 1.5 倍
            signal["factors"].append("sell_pressure")

    # 分析成交量
    if volume_data:
        volume_ratio = volume_data.get("volume_liquidity_ratio", 0)

        # 成交量/流动性比率分析
        if volume_ratio > 0.5:  # 高活跃度
            signal["factors"].append("high_activity")
        elif volume_ratio < 0.1:  # 低活跃度
            signal["factors"].append("low_activity")

    # 生成推荐
    buy_signals = sum(1 for f in signal["factors"] if f in ["buy_pressure", "tight_spread", "high_activity"])
    sell_signals = sum(1 for f in signal["factors"] if f in ["sell_pressure", "wide_spread"])

    if buy_signals > sell_signals:
        signal["recommendation"] = "buy"
        signal["confidence"] = min(0.7, 0.3 + buy_signals * 0.1)
    elif sell_signals > buy_signals:
        signal["recommendation"] = "sell"
        signal["confidence"] = min(0.7, 0.3 + sell_signals * 0.1)
    else:
        signal["recommendation"] = "hold"
        signal["confidence"] = 0.3

    # 保存缓存
    if market_slug:
        save_cached_data(market_slug, signal)

    return signal


def format_microstructure_report(signal):
    """格式化微观结构报告"""
    if not signal:
        return "微观结构数据: 无"

    lines = []
    lines.append("📊 市场微观结构")
    lines.append(f"   推荐: {signal['recommendation']} (置信度: {signal['confidence']:.2f})")

    if signal.get("order_book"):
        ob = signal["order_book"]
        lines.append(f"   买卖价差: {ob['spread_pct']:.2%}")
        lines.append(f"   深度比率: {ob['depth_ratio']:.2f} (买/卖)")

    if signal.get("volume"):
        vol = signal["volume"]
        lines.append(f"   成交量: ${vol['current_volume']:,.0f}")
        lines.append(f"   流动性: ${vol['liquidity']:,.0f}")

    if signal.get("factors"):
        lines.append(f"   因子: {', '.join(signal['factors'])}")

    return "\n".join(lines)


if __name__ == "__main__":
    print("=" * 50)
    print("市场微观结构信号模块测试")
    print("=" * 50)

    # 测试用例
    test_condition_id = "0x1234567890abcdef"
    test_token_id = "0xabcdef1234567890"
    test_slug = "test-market"

    print("\n1. 计算微观结构信号:")
    signal = calculate_microstructure_signal(test_condition_id, test_token_id, test_slug)
    print(format_microstructure_report(signal))

    print("\n✅ 市场微观结构信号模块测试完成")
