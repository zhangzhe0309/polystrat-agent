#!/usr/bin/env python3
"""
跨平台套利增强模块
- 集成 Arbiter 的跨平台套利逻辑
- Fractional Kelly 仓位管理
- Monte Carlo 爆仓概率计算
- World Cup 2026 流动性挖矿
"""
import os
import json
import requests
import numpy as np
from datetime import datetime, timezone
from pathlib import Path
from polystrat_logger import log, log_error

# 平台配置
PLATFORMS = {
    "polymarket": {
        "api": "https://gamma-api.polymarket.com",
        "fee": 0.02,  # 2% taker fee
        "enabled": True
    },
    "kalshi": {
        "api": "https://external-api.kalshi.com/trade-api/v2",
        "fee": 0.07,  # 7% (Crypto 最高)
        "enabled": True
    },
    "manifold": {
        "api": "https://api.manifold.markets/v0",
        "fee": 0.00,  # 免费
        "enabled": True
    }
}

# Maker Rebates (2026-06 更新)
MAKER_REBATES = {
    "Tech": 0.25,           # 25% 返佣
    "Mentions": 0.25,       # 25% 返佣
    "Geopolitics": 0.00,    # 无返佣
    "Sports": 0.03,         # 最低 taker fee
    "Crypto": 0.07,         # 最高 taker fee
}

# World Cup 2026 奖励池
WORLD_CUP_REWARDS = {
    "group_stage": {"pre_game": 2139, "live": 3971, "total": 6110},
    "group_stage_focus": {"pre_game": 3754, "live": 6971, "total": 10725},
    "final": {"pre_game": 18200, "live": 33800, "total": 52000},
}

def fetch_polymarket_markets(limit=50):
    """获取 Polymarket 市场"""
    try:
        resp = requests.get(
            f"{PLATFORMS['polymarket']['api']}/markets",
            params={"limit": limit, "active": True, "closed": False},
            timeout=15
        )
        if resp.status_code == 200:
            markets = resp.json()
            return [{
                "platform": "polymarket",
                "title": m.get("question", ""),
                "yes_price": float(json.loads(m.get("outcomePrices", "[0.5]"))[0]),
                "volume": float(m.get("volume", 0)),
                "liquidity": float(m.get("liquidityNum", 0)),
                "condition_id": m.get("conditionId", ""),
            } for m in markets]
        return []
    except Exception as e:
        log_error("arbitrage", e, "Polymarket 获取失败")
        return []

def fetch_kalshi_markets(limit=50):
    """获取 Kalshi 市场"""
    try:
        resp = requests.get(
            f"{PLATFORMS['kalshi']['api']}/markets",
            params={"limit": limit, "status": "open"},
            timeout=15
        )
        if resp.status_code == 200:
            data = resp.json()
            markets = data.get("markets", [])
            return [{
                "platform": "kalshi",
                "title": m.get("title", ""),
                "yes_price": m.get("yes_bid", 50) / 100,
                "volume": m.get("volume", 0),
                "liquidity": m.get("open_interest", 0),
                "ticker": m.get("ticker", ""),
            } for m in markets]
        return []
    except Exception as e:
        log_error("arbitrage", e, "Kalshi 获取失败")
        return []

def fetch_manifold_markets(limit=50):
    """获取 Manifold 市场"""
    try:
        resp = requests.get(
            f"{PLATFORMS['manifold']['api']}/search-markets",
            params={"term": "", "limit": limit},
            timeout=15
        )
        if resp.status_code == 200:
            markets = resp.json()
            return [{
                "platform": "manifold",
                "title": m.get("question", ""),
                "yes_price": m.get("probability", 0.5),
                "volume": m.get("volume", 0),
                "liquidity": m.get("liquidity", 0),
                "id": m.get("id", ""),
            } for m in markets]
        return []
    except Exception as e:
        log_error("arbitrage", e, "Manifold 获取失败")
        return []

def calculate_similarity(title1, title2):
    """计算标题相似度（Jaccard）"""
    import re
    
    t1 = set(re.findall(r'\w+', title1.lower()))
    t2 = set(re.findall(r'\w+', title2.lower()))
    
    if not t1 or not t2:
        return 0.0
    
    intersection = t1.intersection(t2)
    union = t1.union(t2)
    
    return len(intersection) / len(union)

def find_cross_platform_opportunities(min_similarity=0.5, min_spread=0.05):
    """
    查找跨平台套利机会
    
    Args:
        min_similarity: 最小相似度
        min_spread: 最小价差
    
    Returns:
        list: 套利机会列表
    """
    # 获取所有平台市场
    polymarket = fetch_polymarket_markets()
    kalshi = fetch_kalshi_markets()
    manifold = fetch_manifold_markets()
    
    all_markets = polymarket + kalshi + manifold
    
    opportunities = []
    
    # 跨平台比较
    for i, m1 in enumerate(all_markets):
        for j, m2 in enumerate(all_markets):
            if i >= j:
                continue
            if m1["platform"] == m2["platform"]:
                continue
            
            # 计算相似度
            sim = calculate_similarity(m1["title"], m2["title"])
            if sim < min_similarity:
                continue
            
            # 计算价差
            spread = abs(m1["yes_price"] - m2["yes_price"])
            if spread < min_spread:
                continue
            
            # 计算扣除费用后的利润
            fee1 = PLATFORMS[m1["platform"]]["fee"]
            fee2 = PLATFORMS[m2["platform"]]["fee"]
            gross_profit = spread - (fee1 + fee2)
            
            # 滑点保护（预留 2% 滑点）
            slippage = 0.02
            net_profit = gross_profit - slippage
            
            # 单腿风险保护（价差必须大于滑点的2倍）
            min_spread_for_arb = slippage * 2 + fee1 + fee2

            if net_profit > 0 and spread > min_spread_for_arb:
                opportunities.append({
                    "market1": m1,
                    "market2": m2,
                    "similarity": sim,
                    "spread": spread,
                    "net_profit": net_profit,
                    "buy_platform": m1["platform"] if m1["yes_price"] < m2["yes_price"] else m2["platform"],
                    "sell_platform": m2["platform"] if m1["yes_price"] < m2["yes_price"] else m1["platform"],
                })
    
    # 按净利润排序
    opportunities.sort(key=lambda x: x["net_profit"], reverse=True)
    
    return opportunities

def fractional_kelly(prob, odds, bankroll, fraction=0.25):
    """
    Fractional Kelly 仓位管理
    
    Args:
        prob: 胜率
        odds: 赔率
        bankroll: 总资金
        fraction: Kelly 分数 (默认 25%)
    
    Returns:
        float: 建议仓位
    """
    # Kelly 公式: f* = (bp - q) / b
    b = odds - 1  # 净赔率
    q = 1 - prob
    
    if b <= 0:
        return 0
    
    kelly = (b * prob - q) / b
    
    # Fractional Kelly
    position = kelly * fraction * bankroll
    
    return max(0, position)

def monte_carlo_risk(positions, simulations=10000):
    """
    Monte Carlo 爆仓概率计算
    
    Args:
        positions: 持仓列表
        simulations: 模拟次数
    
    Returns:
        dict: 风险指标
    """
    if not positions:
        return {"ruin_probability": 0, "expected_return": 0}
    
    # 提取收益率和概率
    returns = []
    probs = []
    
    for pos in positions:
        returns.append(pos.get("expected_return", 0))
        probs.append(pos.get("win_probability", 0.5))
    
    # Monte Carlo 模拟
    results = []
    for _ in range(simulations):
        total = 0
        for ret, prob in zip(returns, probs):
            if np.random.random() < prob:
                total += ret
            else:
                total -= abs(ret)
        results.append(total)
    
    results = np.array(results)
    
    return {
        "ruin_probability": np.mean(results < -0.5),  # 亏损超过50%
        "expected_return": np.mean(results),
        "std_dev": np.std(results),
        "var_95": np.percentile(results, 5),  # 95% VaR
        "max_drawdown": np.min(results),
    }

def calculate_liquidity_rewards(category, is_maker=True):
    """
    计算流动性挖矿奖励
    
    Args:
        category: 市场类别
        is_maker: 是否是 maker
    
    Returns:
        dict: 奖励信息
    """
    rebate = MAKER_REBATES.get(category, 0)
    
    return {
        "category": category,
        "rebate_rate": rebate,
        "is_maker": is_maker,
        "effective_fee": 0 if is_maker and category == "Geopolitics" else None,
    }

def format_arbitrage_report(opportunities):
    """格式化套利报告"""
    if not opportunities:
        return "未发现套利机会"
    
    lines = []
    lines.append("🔄 跨平台套利报告")
    lines.append("=" * 50)
    lines.append(f"发现 {len(opportunities)} 个套利机会")
    lines.append("")
    
    for i, opp in enumerate(opportunities[:5], 1):
        m1 = opp["market1"]
        m2 = opp["market2"]
        
        lines.append(f"机会 {i}:")
        lines.append(f"  {m1['title'][:40]}...")
        lines.append(f"  {m1['platform']}: {m1['yes_price']:.2f} vs {m2['platform']}: {m2['yes_price']:.2f}")
        lines.append(f"  价差: {opp['spread']:.2%}")
        lines.append(f"  净利润: {opp['net_profit']:.2%}")
        lines.append(f"  买入: {opp['buy_platform']} | 卖出: {opp['sell_platform']}")
        lines.append("")
    
    return "\n".join(lines)

if __name__ == "__main__":
    print("=" * 50)
    print("跨平台套利增强测试")
    print("=" * 50)
    
    # 测试1: 获取各平台市场
    print("\n1. 获取市场:")
    pm = fetch_polymarket_markets(10)
    ks = fetch_kalshi_markets(10)
    mf = fetch_manifold_markets(10)
    print(f"   Polymarket: {len(pm)} 个")
    print(f"   Kalshi: {len(ks)} 个")
    print(f"   Manifold: {len(mf)} 个")
    
    # 测试2: 查找套利机会
    print("\n2. 查找套利机会:")
    opps = find_cross_platform_opportunities(min_similarity=0.3, min_spread=0.03)
    print(f"   发现 {len(opps)} 个机会")
    print(format_arbitrage_report(opps))
    
    # 测试3: Fractional Kelly
    print("\n3. Fractional Kelly:")
    position = fractional_kelly(0.6, 2.0, 1000, 0.25)
    print(f"   胜率=60%, 赔率=2x, 资金=$1000, Kelly=25%")
    print(f"   建议仓位: ${position:.2f}")
    
    # 测试4: 流动性奖励
    print("\n4. 流动性奖励:")
    for cat in ["Sports", "Crypto", "Tech", "Geopolitics"]:
        reward = calculate_liquidity_rewards(cat)
        print(f"   {cat}: 返佣 {reward['rebate_rate']:.0%}")
    
    print("\n✅ 跨平台套利增强测试完成")
