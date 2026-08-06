#!/usr/bin/env python3
"""
链上数据监控模块
- 监控 Polymarket 市场数据
- 分析交易量变化
- 提供市场情绪信号
"""

import requests
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

# Polymarket API
from config_center import GAMMA_API

# 历史快照目录
from config_center import VOLUME_CACHE_DIR


def get_market_volume(market_slug):
    """
    获取市场交易量

    Args:
        market_slug: 市场 slug

    Returns:
        dict: 交易量数据
    """
    try:
        url = f"{GAMMA_API}/markets"
        params = {"slug": market_slug, "limit": 1}
        resp = requests.get(url, params=params, timeout=10)

        if resp.status_code == 200:
            markets = resp.json()
            if not markets:
                return {"volume": 0, "liquidity": 0, "volume_liquidity_ratio": 0}
            market = markets[0]

            volume = float(market.get("volume", 0))
            liquidity = float(market.get("liquidityNum", 0))

            return {
                "volume": volume,
                "liquidity": liquidity,
                "volume_liquidity_ratio": volume / liquidity if liquidity > 0 else 0,
            }
        else:
            return {"volume": 0, "liquidity": 0, "volume_liquidity_ratio": 0}

    except Exception as e:
        print(f"⚠️ 获取市场交易量失败: {e}")
        return {"volume": 0, "liquidity": 0, "volume_liquidity_ratio": 0}


def get_trending_markets(limit=10):
    """
    获取热门市场

    Args:
        limit: 最大结果数

    Returns:
        list: 热门市场列表
    """
    try:
        url = f"{GAMMA_API}/markets"
        params = {
            "closed": "false",
            "limit": limit * 2,
            "active": "true",
            "order": "volume_24hr",
            "ascending": "false",
        }

        resp = requests.get(url, params=params, timeout=10)

        if resp.status_code == 200:
            markets = resp.json()

            trending = []
            for market in markets:
                volume = float(market.get("volume", 0))
                liquidity = float(market.get("liquidityNum", 0))

                # 过滤有交易量的市场
                if volume > 10000:
                    try:
                        prices_str = market.get("outcomePrices", "[0.5]")
                        if isinstance(prices_str, str):
                            prices = json.loads(prices_str)
                        else:
                            prices = prices_str
                        yes_price = float(prices[0]) if prices else 0.5
                    except (json.JSONDecodeError, ValueError, TypeError) as e:
                        print(f"⚠️ 热门市场价格解析失败: {e}")
                        yes_price = 0.5

                    trending.append(
                        {
                            "title": market.get("question", ""),
                            "slug": market.get("slug", ""),
                            "volume": volume,
                            "liquidity": liquidity,
                            "yes_price": yes_price,
                        }
                    )

            return trending[:limit]
        else:
            print(f"⚠️ 获取热门市场失败: {resp.status_code}")
            return []

    except Exception as e:
        print(f"⚠️ 获取热门市场失败: {e}")
        return []


def _load_volume_snapshot(market_slug):
    """从本地缓存加载历史交易量快照"""
    cache_file = VOLUME_CACHE_DIR / f"{market_slug}.json"
    if cache_file.exists():
        try:
            return json.loads(cache_file.read_text())
        except (json.JSONDecodeError, OSError) as e:
            print(f"⚠️ 交易量快照加载失败: {e}")
            return None
    return None


def _save_volume_snapshot(market_slug, volume, liquidity):
    """保存当前交易量快照到本地缓存"""
    VOLUME_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = VOLUME_CACHE_DIR / f"{market_slug}.json"
    try:
        cache_file.write_text(
            json.dumps(
                {
                    "volume": volume,
                    "liquidity": liquidity,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
        )
    except OSError as e:
        print(f"⚠️ 交易量快照保存失败: {e}")


def analyze_volume_change(market_slug, hours=24):
    """
    分析交易量变化（基于 Gamma API + 本地快照缓存）

    Gamma API 返回的是累计交易量，两次快照之差 = 区间交易量。

    工作方式：
    - 读取上次运行保存的 volume 快照
    - 检查快照时效性是否在 hours 窗口内
    - 对比当前 volume 计算变化率
    - 保存当前 volume 供下次对比
    - 首次运行无快照时：用 volume/liquidity 比率作代理

    Args:
        market_slug: 市场 slug
        hours: 时间范围（小时），仅用于校验快照时效性

    Returns:
        dict: 交易量变化分析
    """
    volume_data = get_market_volume(market_slug)
    current_volume = volume_data.get("volume", 0)
    current_liquidity = volume_data.get("liquidity", 0)

    previous = _load_volume_snapshot(market_slug)
    change = 0.0
    trend = "stable"
    confidence = 0.1

    if previous and previous.get("volume", 0) > 0:
        old_volume = previous["volume"]
        old_ts = previous.get("timestamp", "")
        # 校验快照时效性
        snap_hours_ago = None
        if old_ts:
            try:
                snap_time = datetime.fromisoformat(old_ts.replace("Z", "+00:00"))
                snap_hours_ago = (
                    datetime.now(timezone.utc) - snap_time
                ).total_seconds() / 3600
            except (ValueError, TypeError) as e:
                print(f"⚠️ 快照时间戳解析失败: {e}")
        # 快照太新（< 0.5h）或太旧（> 2×hours）都降低置信度
        time_ok = True
        if snap_hours_ago is not None:
            if snap_hours_ago < 0.5:
                confidence = 0.15
                time_ok = False
            elif snap_hours_ago > hours * 2:
                confidence = 0.2
                time_ok = False

        if old_volume > 0:
            change = (current_volume - old_volume) / old_volume
        else:
            change = 0

        trend = (
            "increasing"
            if change > 0.05
            else "decreasing"
            if change < -0.05
            else "stable"
        )
        if time_ok:
            confidence = min(0.8, 0.4 + abs(change))
    else:
        # 无历史快照：无法计算变化，返回 0 和低置信度
        pass

    _save_volume_snapshot(market_slug, current_volume, current_liquidity)

    return {
        "volume_change": round(change, 4),
        "trend": trend,
        "confidence": round(confidence, 2),
    }


def get_market_momentum(market_title):
    """
    获取市场动量（优化版：更多因子，更准确的信号）

    优化点：
    1. 提升市场匹配度（70% 单词匹配）
    2. 增加更多动量因子（价格变化、流动性变化、交易量趋势）
    3. 增加 sell/strong_sell 信号
    4. 提升置信度计算

    Args:
        market_title: 市场标题

    Returns:
        dict: 市场动量数据
    """
    try:
        # 搜索市场
        url = f"{GAMMA_API}/markets"
        params = {"limit": 30, "active": "true"}

        resp = requests.get(url, params=params, timeout=10)

        if resp.status_code == 200:
            markets = resp.json()

            # 找到匹配的市场（使用单词边界，防子字符串误匹配）
            target_market = None
            title_lower = market_title.lower()
            title_words = set(re.findall(r"\w+", title_lower))

            # 优先精确匹配，然后模糊匹配
            best_match_ratio = 0
            for market in markets:
                question = market.get("question", "").lower()
                q_words = set(re.findall(r"\w+", question))
                # 计算匹配度
                if title_words and q_words:
                    overlap = title_words & q_words
                    ratio = len(overlap) / max(len(title_words), len(q_words))
                    # 至少匹配 70% 的单词（提升匹配度）
                    if ratio >= 0.7 and ratio > best_match_ratio:
                        best_match_ratio = ratio
                        target_market = market

            if target_market:
                slug = target_market.get("slug", "")
                volume_data = get_market_volume(slug)
                volume_change = analyze_volume_change(slug)

                # 获取价格数据
                prices = target_market.get("outcomePrices", "[0.5]")
                if isinstance(prices, str):
                    price_list = json.loads(prices)
                else:
                    price_list = prices
                yes_price = float(price_list[0]) if price_list else 0.5

                # 计算动量分数（多因子）
                momentum_score = 0
                factors = []

                # 因子1：成交量/流动性比率（权重 0.25）
                vol_liq_ratio = volume_data["volume_liquidity_ratio"]
                if vol_liq_ratio > 0.5:
                    momentum_score += 0.25
                    factors.append("high_vol_liq_ratio")
                elif vol_liq_ratio > 0.2:
                    momentum_score += 0.15
                    factors.append("medium_vol_liq_ratio")

                # 因子2：成交量变化（权重 0.25）
                vol_change = volume_change["volume_change"]
                if vol_change > 0.2:
                    momentum_score += 0.25
                    factors.append("strong_volume_increase")
                elif vol_change > 0.1:
                    momentum_score += 0.15
                    factors.append("volume_increase")
                elif vol_change < -0.2:
                    momentum_score -= 0.15
                    factors.append("volume_decrease")

                # 因子3：绝对成交量（权重 0.2）
                volume = volume_data["volume"]
                if volume > 100000:
                    momentum_score += 0.2
                    factors.append("high_volume")
                elif volume > 50000:
                    momentum_score += 0.1
                    factors.append("medium_volume")

                # 因子4：流动性（权重 0.15）
                liquidity = volume_data["liquidity"]
                if liquidity > 50000:
                    momentum_score += 0.15
                    factors.append("high_liquidity")
                elif liquidity > 20000:
                    momentum_score += 0.1
                    factors.append("medium_liquidity")

                # 因子5：价格极端性（权重 0.15）
                # 极端价格（<20% 或 >80%）可能意味着市场已经定价
                if yes_price < 0.2 or yes_price > 0.8:
                    momentum_score -= 0.1
                    factors.append("extreme_price")

                # 限制分数范围
                momentum_score = max(0, min(1, momentum_score))

                # 生成推荐（增加 sell 信号）
                if momentum_score > 0.7:
                    recommendation = "strong_buy"
                elif momentum_score > 0.5:
                    recommendation = "buy"
                elif momentum_score < 0.2:
                    recommendation = "sell"
                elif momentum_score < 0.3:
                    recommendation = "weak_sell"
                else:
                    recommendation = "hold"

                return {
                    "market_found": True,
                    "volume": volume,
                    "liquidity": liquidity,
                    "volume_change": vol_change,
                    "volume_liquidity_ratio": vol_liq_ratio,
                    "yes_price": yes_price,
                    "momentum_score": round(momentum_score, 2),
                    "recommendation": recommendation,
                    "factors": factors,
                    "match_ratio": best_match_ratio,
                }

        return {
            "market_found": False,
            "volume": 0,
            "liquidity": 0,
            "volume_change": 0,
            "volume_liquidity_ratio": 0,
            "yes_price": 0.5,
            "momentum_score": 0,
            "recommendation": "hold",
            "factors": [],
            "match_ratio": 0,
        }

    except Exception as e:
        print(f"⚠️ 市场动量分析失败: {e}")
        return {
            "market_found": False,
            "volume": 0,
            "liquidity": 0,
            "volume_change": 0,
            "volume_liquidity_ratio": 0,
            "yes_price": 0.5,
            "momentum_score": 0,
            "recommendation": "hold",
            "factors": [],
            "match_ratio": 0,
        }


def get_onchain_signal(market_title):
    """
    获取链上信号（优化版：更准确的置信度计算）

    优化点：
    1. 提升置信度计算（多因子）
    2. 增加信号详情（因素、匹配度）
    3. 增加 sell/strong_sell 信号支持

    Args:
        market_title: 市场标题

    Returns:
        dict: 链上信号
    """
    # 1. 获取热门市场
    trending = get_trending_markets(limit=5)

    # 2. 分析市场动量
    momentum = get_market_momentum(market_title)

    # 3. 综合信号（多因子置信度计算）
    market_found = momentum.get("market_found", False)
    momentum_score = momentum.get("momentum_score", 0)
    match_ratio = momentum.get("match_ratio", 0)
    factors = momentum.get("factors", [])

    if market_found:
        # 置信度计算（多因子）
        # 基础置信度：基于市场匹配度
        base_confidence = 0.3 + 0.3 * match_ratio  # 匹配度越高，基础置信度越高

        # 动量置信度：基于动量分数
        momentum_confidence = 0.2 * momentum_score

        # 因子置信度：基于因素数量
        factor_confidence = min(0.2, len(factors) * 0.05)  # 每个因素 +0.05，最高 0.2

        # 总置信度
        confidence = base_confidence + momentum_confidence + factor_confidence
        confidence = min(0.95, max(0.3, confidence))  # 限制在 0.3-0.95 之间
    else:
        confidence = 0.3

    signal = {
        "trending_markets": len(trending),
        "market_volume": momentum.get("volume", 0),
        "volume_change": momentum.get("volume_change", 0),
        "volume_liquidity_ratio": momentum.get("volume_liquidity_ratio", 0),
        "yes_price": momentum.get("yes_price", 0.5),
        "momentum_score": momentum_score,
        "recommendation": momentum.get("recommendation", "hold"),
        "confidence": round(confidence, 2),
        "factors": factors,
        "match_ratio": match_ratio,
        "market_found": market_found,
    }

    return signal


if __name__ == "__main__":
    # 测试链上数据监控
    print("🔗 链上数据监控模块测试")
    print("=" * 50)

    # 测试热门市场
    print("\n1. 热门市场:")
    trending = get_trending_markets(limit=5)
    print(f"   找到 {len(trending)} 个热门市场")
    for market in trending[:3]:
        print(f"   - {market['title'][:40]}... | 交易量: ${market['volume']:,.0f}")

    # 测试市场动量
    print("\n2. 市场动量分析:")
    momentum = get_market_momentum("Trump president")
    print(f"   市场找到: {momentum['market_found']}")
    print(f"   交易量: ${momentum['volume']:,.0f}")
    print(f"   动量分数: {momentum['momentum_score']:.2f}")
    print(f"   建议: {momentum['recommendation']}")

    # 测试链上信号
    print("\n3. 链上信号:")
    signal = get_onchain_signal("Trump president")
    print(f"   热门市场: {signal['trending_markets']} 个")
    print(f"   市场交易量: ${signal['market_volume']:,.0f}")
    print(f"   动量分数: {signal['momentum_score']:.2f}")
    print(f"   建议: {signal['recommendation']}")
    print(f"   置信度: {signal['confidence']:.2f}")
