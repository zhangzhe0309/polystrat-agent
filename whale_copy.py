#!/usr/bin/env python3
"""
鲸鱼跟单模块
- 集成 KongTradeBot 的跟单逻辑
- Multiplier 加权跟单
- 3级钱包筛选（KongScore）
- Take-Profit 触发
"""
import os
import json
import requests
from datetime import datetime, timezone
from pathlib import Path
from polystrat_logger import log, log_error

# 配置
DATA_API = "https://data-api.polymarket.com"

# 鲸鱼钱包配置
WHALE_WALLETS = {
    # Tier 1: 顶级鲸鱼（高胜率，大资金）
    "tier1": [
        {"address": "0x2005d16a...", "name": "RN1", "multiplier": 0.10, "min_score": 80},
    ],
    # Tier 2: 中等鲸鱼
    "tier2": [
        # 可以添加更多
    ],
    # Tier 3: 小型鲸鱼
    "tier3": [
        # 可以添加更多
    ]
}

# 跟单配置
COPY_CONFIG = {
    "multiplier": 0.05,           # 跟单比例（鲸鱼下注的5%）
    "max_position_usd": 100,      # 单笔最大仓位
    "min_whale_size_usd": 100,    # 最小鲸鱼下注金额
    "take_profit_pct": 0.20,      # 止盈 20%
    "stop_loss_pct": -0.10,       # 止损 -10%
    "max_daily_copies": 10,       # 每日最大跟单数
    "min_win_rate": 0.45,         # 最低胜率（低于此停止跟单）
}

def get_whale_activity(wallet_address, limit=20):
    """
    获取鲸鱼活动
    
    Args:
        wallet_address: 钱包地址
        limit: 返回数量
    
    Returns:
        list: 活动列表
    """
    try:
        resp = requests.get(
            f"{DATA_API}/activity",
            params={"user": wallet_address, "limit": limit},
            timeout=15
        )
        
        if resp.status_code == 200:
            return resp.json()
        return []
    except Exception as e:
        log_error("whale_copy", e, f"获取鲸鱼活动失败: {wallet_address[:10]}")
        return []

def calculate_kongscore(wallet_address):
    """
    计算 KongScore（钱包可信度评分）
    
    评分标准：
    - 胜率 (40%)
    - 盈亏比 (30%)
    - 交易频率 (20%)
    - 资金规模 (10%)
    
    Returns:
        dict: 评分详情
    """
    activity = get_whale_activity(wallet_address, 100)
    
    if not activity:
        return {"score": 0, "tier": "unknown"}
    
    # 计算胜率
    wins = sum(1 for a in activity if a.get("pnl", 0) > 0)
    total = len(activity)
    win_rate = wins / total if total > 0 else 0
    
    # 计算盈亏比
    avg_win = sum(a.get("pnl", 0) for a in activity if a.get("pnl", 0) > 0) / max(wins, 1)
    avg_loss = abs(sum(a.get("pnl", 0) for a in activity if a.get("pnl", 0) < 0)) / max(total - wins, 1)
    profit_ratio = avg_win / avg_loss if avg_loss > 0 else 1
    
    # 计算交易频率（每天）
    if total >= 2:
        first = datetime.fromisoformat(activity[-1].get("timestamp", "").replace("Z", "+00:00"))
        last = datetime.fromisoformat(activity[0].get("timestamp", "").replace("Z", "+00:00"))
        days = max((last - first).days, 1)
        frequency = total / days
    else:
        frequency = 0
    
    # 计算资金规模
    total_volume = sum(abs(a.get("size", 0)) for a in activity)
    
    # 综合评分
    score = (
        win_rate * 40 +
        min(profit_ratio / 2, 1) * 30 +
        min(frequency / 5, 1) * 20 +
        min(total_volume / 10000, 1) * 10
    )
    
    # 确定层级
    if score >= 80:
        tier = "tier1"
    elif score >= 60:
        tier = "tier2"
    else:
        tier = "tier3"
    
    return {
        "score": score,
        "tier": tier,
        "win_rate": win_rate,
        "profit_ratio": profit_ratio,
        "frequency": frequency,
        "total_volume": total_volume,
    }

def should_copy(whale_trade, kongscore):
    """
    判断是否应该跟单
    
    Args:
        whale_trade: 鲸鱼交易
        kongscore: 钱包评分
    
    Returns:
        tuple: (是否跟单, 原因)
    """
    # 检查评分
    if kongscore["score"] < 60:
        return False, f"KongScore 过低: {kongscore['score']:.0f}"
    
    # 检查胜率
    if kongscore["win_rate"] < COPY_CONFIG["min_win_rate"]:
        return False, f"胜率过低: {kongscore['win_rate']:.1%}"
    
    # 检查下注金额
    size = abs(whale_trade.get("size", 0))
    if size < COPY_CONFIG["min_whale_size_usd"]:
        return False, f"下注金额过小: ${size:.2f}"
    
    return True, "符合条件"

def calculate_copy_size(whale_size, kongscore):
    """
    计算跟单金额
    
    Args:
        whale_size: 鲸鱼下注金额
        kongscore: 钱包评分
    
    Returns:
        float: 跟单金额
    """
    # 基础跟单金额
    base_size = whale_size * COPY_CONFIG["multiplier"]
    
    # 根据 KongScore 调整
    score_multiplier = kongscore["score"] / 100
    adjusted_size = base_size * score_multiplier
    
    # 限制最大金额
    final_size = min(adjusted_size, COPY_CONFIG["max_position_usd"])
    
    return round(final_size, 2)

def monitor_whales():
    """
    监控鲸鱼活动
    
    Returns:
        list: 跟单信号
    """
    signals = []
    
    for tier, wallets in WHALE_WALLETS.items():
        for wallet in wallets:
            address = wallet["address"]
            
            # 获取最近活动
            activity = get_whale_activity(address, 5)
            
            if not activity:
                continue
            
            # 计算 KongScore
            kongscore = calculate_kongscore(address)
            
            # 检查最新交易
            for trade in activity[:3]:
                should, reason = should_copy(trade, kongscore)
                
                if should:
                    copy_size = calculate_copy_size(abs(trade.get("size", 0)), kongscore)
                    
                    signals.append({
                        "whale": wallet["name"],
                        "whale_tier": tier,
                        "kongscore": kongscore["score"],
                        "market": trade.get("market", ""),
                        "side": trade.get("side", ""),
                        "whale_size": abs(trade.get("size", 0)),
                        "copy_size": copy_size,
                        "timestamp": trade.get("timestamp", ""),
                    })
    
    return signals

def format_whale_signals(signals):
    """格式化跟单信号"""
    if not signals:
        return "无跟单信号"
    
    lines = []
    lines.append("🐋 鲸鱼跟单信号")
    lines.append("=" * 50)
    lines.append(f"发现 {len(signals)} 个跟单机会")
    lines.append("")
    
    for s in signals[:5]:
        lines.append(f"  鲸鱼: {s['whale']} (KongScore: {s['kongscore']:.0f})")
        lines.append(f"  市场: {s['market'][:40]}...")
        lines.append(f"  方向: {s['side']}")
        lines.append(f"  鲸鱼下注: ${s['whale_size']:.2f}")
        lines.append(f"  跟单金额: ${s['copy_size']:.2f}")
        lines.append("")
    
    return "\n".join(lines)

if __name__ == "__main__":
    print("=" * 50)
    print("鲸鱼跟单模块测试")
    print("=" * 50)
    
    # 测试1: 获取鲸鱼活动
    print("\n1. 获取鲸鱼活动:")
    for tier, wallets in WHALE_WALLETS.items():
        for wallet in wallets[:1]:
            activity = get_whale_activity(wallet["address"], 5)
            print(f"   {wallet['name']}: {len(activity)} 笔交易")
    
    # 测试2: 计算 KongScore
    print("\n2. KongScore 计算:")
    for tier, wallets in WHALE_WALLETS.items():
        for wallet in wallets[:1]:
            score = calculate_kongscore(wallet["address"])
            print(f"   {wallet['name']}: Score={score['score']:.0f}, Tier={score['tier']}")
    
    # 测试3: 监控鲸鱼
    print("\n3. 鲸鱼监控:")
    signals = monitor_whales()
    print(format_whale_signals(signals))
    
    print("\n✅ 鲸鱼跟单模块测试完成")
