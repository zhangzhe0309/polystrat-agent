#!/usr/bin/env python3
"""
Yes Bias 逆向策略模块 — PolyStrat v4.1
=====================================
基于 Polymarket 市场结构性偏差(Yes Bias)的逆向策略。

核心逻辑:
- 预测市场系统性高估正面结果概率(Yes Bias)
- 当市场共识>80%时，反向押No
- 当市场共识<20%时，考虑押Yes（低概率事件低估效应较弱）
- 结合时间衰减：越临近到期，逆向策略越有效
- 结合类别过滤：Sports/Politics类别Yes Bias最强

行业验证:
- Binance四Bot实验: 逆向策略$500→$1,740(冠军)
- Polymarket链上数据: 84%交易者亏损，多数因追Yes
- 学术论文: 预测市场普遍高估正面结果概率10-15%

作者: PolyStrat Team
日期: 2026-07-08
"""

import json
import requests
from datetime import datetime, timezone, timedelta

# ============ 配置 ============

# Yes Bias 参数
YES_BIAS_CONFIG = {
    "enabled": True,
    # 逆向入场阈值
    "strong_yes_threshold": 0.80,   # Yes价>80¢触发强逆向
    "moderate_yes_threshold": 0.70, # Yes价>70¢触发中等逆向
    "strong_no_threshold": 0.20,    # Yes价<20¢考虑低概率事件
    # 逆向信号强度
    "strong_signal": 0.15,          # 强逆向：将概率向No偏移15%
    "moderate_signal": 0.08,        # 中等逆向：偏移8%
    "weak_signal": 0.03,            # 弱逆向：偏移3%
    # 类别权重（Yes Bias在不同类别强度不同）
    "category_bias_strength": {
        "Sports": 1.3,        # 体育赛事Yes Bias最强
        "Politics": 1.2,      # 政治事件次之
        "Crypto": 1.0,        # 加密市场相对理性
        "Economics": 1.0,     # 经济事件
        "Science": 0.8,       # 科学事件较理性
        "Weather": 0.5,       # 天气最理性（有数据锚定）
        "Other": 0.9,
    },
    # 时间衰减加成（越临近到期，逆向越有效）
    "time_decay_bonus": {
        "1_day": 1.5,         # 1天内到期，逆向加成50%
        "3_days": 1.2,        # 3天内到期，加成20%
        "7_days": 1.0,        # 7天内无加成
        "30_days": 0.8,       # 30天以上衰减20%
    },
    # 流动性要求（逆向策略需要足够的退出流动性）
    "min_liquidity": 5000,
    # 排除条件
    "exclude_resolved": True,       # 已解决的市场不参与
    "exclude_crypto_15min": True,   # 排除15分钟Crypto市场（噪音太大）
}


def calculate_yes_bias_signal(market):
    """
    计算 Yes Bias 逆向信号
    
    Args:
        market: 市场信息 dict，必须包含:
            - yes_price: float (0-1)
            - category: str (可选)
            - end_date: str (可选, ISO格式)
            - liquidity: float (可选)
            - title: str
    
    Returns:
        dict: {
            "signal": float,           # 概率偏移 (-1 to 1, 负=偏向No)
            "strength": str,           # "strong"/"moderate"/"weak"/"none"
            "direction": str,          # "no"/"yes"/"neutral"
            "raw_yes_bias": float,     # 原始Yes Bias偏移量
            "time_bonus": float,       # 时间衰减加成倍率
            "category_multiplier": float, # 类别乘数
            "reason": str,             # 可解释的原因
        }
    """
    config = YES_BIAS_CONFIG
    if not config["enabled"]:
        return _neutral_signal("Yes Bias策略未启用")
    
    yes_price = market.get("yes_price", 0.5)
    category = market.get("category", "Other")
    end_date = market.get("end_date", "")
    liquidity = market.get("liquidity", 0)
    title = market.get("title", "")
    
    # 1. 排除检查
    if liquidity > 0 and liquidity < config["min_liquidity"]:
        return _neutral_signal(f"流动性不足 ${liquidity:,.0f} < ${config['min_liquidity']:,.0f}")
    
    # 排除15分钟Crypto市场
    if config["exclude_crypto_15min"]:
        title_lower = title.lower()
        if any(kw in title_lower for kw in ["15 min", "15-min", "15min", "5 min", "5-min"]):
            return _neutral_signal("短周期Crypto市场排除")
    
    # 2. 判断逆向方向和信号强度
    signal = 0.0
    strength = "none"
    direction = "neutral"
    reason = ""
    
    if yes_price >= config["strong_yes_threshold"]:
        # 强逆向：市场过度乐观 → 偏向No
        signal = -config["strong_signal"]  # 负数=偏向No
        strength = "strong"
        direction = "no"
        reason = f"Yes价{yes_price:.0%}>={config['strong_yes_threshold']:.0%}，强Yes Bias逆向"
    
    elif yes_price >= config["moderate_yes_threshold"]:
        # 中等逆向
        signal = -config["moderate_signal"]
        strength = "moderate"
        direction = "no"
        reason = f"Yes价{yes_price:.0%}>={config['moderate_yes_threshold']:.0%}，中等Yes Bias逆向"
    
    elif yes_price <= config["strong_no_threshold"]:
        # 低概率事件低估效应（较弱）
        signal = config["weak_signal"]
        strength = "weak"
        direction = "yes"
        reason = f"Yes价{yes_price:.0%}<={config['strong_no_threshold']:.0%}，低概率事件可能低估"
    
    else:
        return _neutral_signal(f"Yes价{yes_price:.0%}在正常区间，无显著Yes Bias")
    
    # 3. 类别乘数
    cat_mult = config["category_bias_strength"].get(category, 0.9)
    signal *= cat_mult
    
    # 4. 时间衰减加成
    time_bonus = 1.0
    if end_date:
        try:
            if "T" in end_date:
                end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            else:
                end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            
            now = datetime.now(timezone.utc)
            days_to_expiry = (end_dt - now).total_seconds() / 86400
            
            if days_to_expiry <= 1:
                time_bonus = config["time_decay_bonus"]["1_day"]
            elif days_to_expiry <= 3:
                time_bonus = config["time_decay_bonus"]["3_days"]
            elif days_to_expiry <= 7:
                time_bonus = config["time_decay_bonus"]["7_days"]
            else:
                time_bonus = config["time_decay_bonus"]["30_days"]
            
            signal *= time_bonus
            
            if time_bonus > 1.0:
                reason += f"，临近到期({days_to_expiry:.1f}天)加成×{time_bonus}"
        except Exception:
            pass
    
    # 5. 边界保护
    signal = max(-0.30, min(0.10, signal))  # 逆向No最多偏移30%，逆向Yes最多10%
    
    return {
        "signal": signal,
        "strength": strength,
        "direction": direction,
        "raw_yes_bias": abs(signal) / (cat_mult * time_bonus),  # 原始偏移量
        "time_bonus": time_bonus,
        "category_multiplier": cat_mult,
        "reason": reason,
    }


def get_yes_bias_prob(market, base_prob):
    """
    将Yes Bias信号应用到基础概率上
    
    Args:
        market: 市场信息 dict
        base_prob: 当前融合后的基础概率 (0-1)
    
    Returns:
        float: 调整后的概率
    """
    bias = calculate_yes_bias_signal(market)
    adjusted = base_prob + bias["signal"]
    return max(0.01, min(0.99, adjusted))


def _neutral_signal(reason=""):
    """返回中性信号"""
    return {
        "signal": 0.0,
        "strength": "none",
        "direction": "neutral",
        "raw_yes_bias": 0.0,
        "time_bonus": 1.0,
        "category_multiplier": 1.0,
        "reason": reason,
    }


# ============ 自测 ============
if __name__ == "__main__":
    test_markets = [
        {"title": "Will Argentina win the 2026 FIFA World Cup?", "yes_price": 0.85, "category": "Sports", "liquidity": 50000},
        {"title": "Will Bitcoin reach $200K by 2026?", "yes_price": 0.72, "category": "Crypto", "liquidity": 100000},
        {"title": "Will it rain in London tomorrow?", "yes_price": 0.35, "category": "Weather", "liquidity": 10000},
        {"title": "Will X company go bankrupt?", "yes_price": 0.12, "category": "Economics", "liquidity": 8000},
    ]
    
    print("=== Yes Bias 逆向策略测试 ===\n")
    for m in test_markets:
        result = calculate_yes_bias_signal(m)
        print(f"📊 {m['title'][:50]}")
        print(f"   Yes={m['yes_price']:.0%} | 信号={result['signal']:+.3f} | 方向={result['direction']} | 强度={result['strength']}")
        print(f"   原因: {result['reason']}")
        print()
