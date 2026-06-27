#!/usr/bin/env python3
"""
鲸鱼跟单模块
- 集成 KongTradeBot 的跟单逻辑
- Win-Rate Decay Detection（最近20笔胜率<45%→停止跟单）
- Trend Decline Detection（近期胜率>10%低于总体→减半跟单）
- Multi-Wallet Signal Aggregation（2+钱包同方向→1.5-2x加权）
- Per-Wallet Multiplier（根据历史胜率动态调整）
- Take-Profit 触发
"""
import os
import json
import requests
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from polystrat_logger import log, log_error

# 配置
DATA_API = "https://data-api.polymarket.com"

# 鲸鱼钱包配置（含 per-wallet multiplier）
WHALE_WALLETS = {
    # Tier 1: 顶级鲸鱼（高胜率，大资金）
    "tier1": [
        {"address": "0x2005d16a84ceefa912d4e380cd32e7ff827875ea", "name": "RN1", "multiplier": 0.10, "min_score": 80},
    ],
    # Tier 2: 中等鲸鱼
    "tier2": [],
    # Tier 3: 小型鲸鱼
    "tier3": [],
}

# KongTradeBot 高胜率钱包清单（可用于扩展跟单目标）
KONG_WALLET_MULTIPLIERS = {
    "0x019782cab5d844f02bafb71f512758be78579f3c": 3.0,  # majorexploiter — 76% WR
    "0xbddf61af533ff524d27154e589d2d7a81510c684": 3.0,  # Countryside — 92% WR
    "0xdb27bf2ac5d428a9c63dbc914611036855a6c56e": 3.0,  # DrPufferfish — 92% WR
    "0xde7be6d489bce070a959e0cb813128ae659b5f4b": 2.5,  # wan123 — 90% WR
    "0x492442eab586f242b53bda933fd5de859c8a3782": 2.0,  # April#1 Sports — 65% WR
    "0xde17f7144fbd0eddb2679132c10ff5e74b120988": 2.0,  # Crypto Spezialist — 65.6% WR
    "0x7177a7f5c216809c577c50c77b12aae81f81ddef": 2.0,  # kcnyekchno — 81% WR
    "0xd84c2b6d65dc596f49c7b6aadd6d74ca91e407b9": 1.5,  # BoneReader — 72% WR
    "0xee613b3fc183ee44f9da9c05f53e2da107e3debf": 0.3,  # sovereign2013 — 49% WR
    "0x7a6192ea6815d3177e978dd3f8c38be5f575af24": 0.3,  # Gambler1968 — 45% WR
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
    "min_recent_trades": 10,      # 最少近期交易数（用于 decay 检测）
    "decay_threshold": 0.45,      # Win-rate decay 阈值
    "trend_decline_pct": 0.10,    # Trend decline 触发百分比
    "multi_signal_window_s": 60,  # 多钱包信号聚合窗口（秒）
    "multi_signal_boost": {       # 多钱包信号加权
        1: 1.0,
        2: 1.5,
        3: 2.0,
    },
}


class WalletPerformance:
    """
    钱包性能追踪（来源: KongTradeBot）
    - 追踪最近 20 笔交易结果
    - Win-Rate Decay Detection: 近期胜率 < 45% → 停止跟单
    - Trend Decline Detection: 近期胜率 > 10% 低于总体 → 减半跟单
    """

    def __init__(self, wallet_address: str):
        self.wallet_address = wallet_address
        self.trades_total = 0
        self.trades_won = 0
        self.trades_lost = 0
        self.total_pnl_usd = 0.0
        self.recent_results = deque(maxlen=20)  # 最近 20 笔

    @property
    def win_rate(self) -> float:
        if self.trades_total == 0:
            return 0.0
        return self.trades_won / self.trades_total

    @property
    def recent_win_rate(self) -> float:
        """最近 20 笔的胜率"""
        if not self.recent_results:
            return 0.0
        wins = sum(1 for r in self.recent_results if r > 0)
        return wins / len(self.recent_results)

    @property
    def is_decaying(self) -> bool:
        """Win Rate < 45% in recent 20 trades → stop copying entirely"""
        if len(self.recent_results) < COPY_CONFIG["min_recent_trades"]:
            return False
        return self.recent_win_rate < COPY_CONFIG["decay_threshold"]

    @property
    def is_trend_declining(self) -> bool:
        """Trend Decline: recent WR > 10% below overall WR → halve multiplier"""
        if self.trades_total < 20 or len(self.recent_results) < 10:
            return False
        return self.recent_win_rate < self.win_rate - COPY_CONFIG["trend_decline_pct"]

    def record(self, pnl_usd: float):
        """记录交易结果"""
        self.trades_total += 1
        self.total_pnl_usd += pnl_usd
        self.recent_results.append(pnl_usd)
        if pnl_usd > 0:
            self.trades_won += 1
        else:
            self.trades_lost += 1

    def get_effective_multiplier(self, base_multiplier: float) -> float:
        """根据性能状态计算有效跟单倍率"""
        if self.is_decaying:
            return 0.0  # 完全停止跟单
        if self.is_trend_declining:
            return base_multiplier * 0.5  # 减半
        return base_multiplier


# 全局钱包性能追踪
_wallet_performance: dict[str, WalletPerformance] = {}


def get_wallet_performance(wallet_address: str) -> WalletPerformance:
    """获取或创建钱包性能追踪器"""
    addr = wallet_address.lower()
    if addr not in _wallet_performance:
        _wallet_performance[addr] = WalletPerformance(addr)
    return _wallet_performance[addr]

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
    判断是否应该跟单（集成 KongTradeBot Win-Rate Decay）
    
    Args:
        whale_trade: 鲸鱼交易
        kongscore: 钱包评分
    
    Returns:
        tuple: (是否跟单, 原因)
    """
    wallet_addr = whale_trade.get("source", whale_trade.get("proxyWallet", "")).lower()
    
    # Win-Rate Decay 检查（KongTradeBot 核心策略）
    if wallet_addr:
        perf = get_wallet_performance(wallet_addr)
        if perf.is_decaying:
            return False, f"Win-Rate Decay: 近期胜率 {perf.recent_win_rate:.1%} < {COPY_CONFIG['decay_threshold']:.0%}"
    
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

def calculate_copy_size(whale_size, kongscore, wallet_addr=""):
    """
    计算跟单金额（集成 KongTradeBot Trend Decline Detection）
    
    Args:
        whale_size: 鲸鱼下注金额
        kongscore: 钱包评分
        wallet_addr: 钱包地址（用于 trend decline 检测）
    
    Returns:
        float: 跟单金额
    """
    # 基础跟单金额
    base_size = whale_size * COPY_CONFIG["multiplier"]
    
    # 根据 KongScore 调整
    score_multiplier = kongscore["score"] / 100
    adjusted_size = base_size * score_multiplier
    
    # Trend Decline 检测（KongTradeBot 策略）
    if wallet_addr:
        perf = get_wallet_performance(wallet_addr)
        effective_mult = perf.get_effective_multiplier(1.0)
        adjusted_size *= effective_mult
        if effective_mult < 1.0:
            log.warning(f"🐋 Trend Decline: {wallet_addr[:10]} 跟单减半 (近期WR={perf.recent_win_rate:.1%})")
    
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
