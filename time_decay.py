#!/usr/bin/env python3
"""
时间衰减信号模块 — PolyStrat v4.1
================================
利用预测市场的时间衰减特性生成交易信号。

核心逻辑:
- 临近到期的事件，如果未发生，No的价值自然增长
- 市场情绪往往慢于时钟 → 时间是No的朋友
- 结合事件类型：对于"是否会发生X"类市场，时间衰减更强
- 对于"X是否会达到Y价位"类市场，Crypto价格可能随时波动，衰减较弱

行业验证:
- Binance四Bot实验: 天气Bot(时间衰减类)第二名
- Polymarket链上数据: 临近到期的No share有正期望
- 学术论文: 预测市场时间衰减率约0.5-2%/天

作者: PolyStrat Team
日期: 2026-07-08
"""

from datetime import datetime, timezone, timedelta

# ============ 配置 ============

TIME_DECAY_CONFIG = {
    "enabled": True,
    # 时间衰减参数
    "daily_decay_rate": 0.015,     # 基础衰减率 1.5%/天
    "acceleration_factor": 1.5,    # 最后3天加速
    # 入场阈值（天数）
    "max_days_to_expiry": 7,       # 7天以内才考虑时间衰减
    "sweet_spot_days": (1, 3),     # 甜蜜点：1-3天到期
    # 类别衰减强度
    "category_decay_strength": {
        "Sports": 1.2,        # 体育：比赛前不确定性高，衰减快
        "Politics": 1.1,      # 政治：事件驱动，衰减中等
        "Economics": 1.0,     # 经济：数据发布有固定时间
        "Crypto": 0.5,        # 加密：价格随时波动，衰减弱
        "Weather": 1.3,       # 天气：越近越确定，衰减最强
        "Science": 0.8,       # 科学：不确定
        "Other": 0.9,
    },
    # Yes价阈值：只在Yes价较高时时间衰减有效
    # Yes价已经很低(如10%)→时间衰减意义不大
    "min_yes_price_for_decay": 0.40,
    "optimal_yes_price_range": (0.50, 0.85),  # 最优Yes价区间
}


def calculate_time_decay_signal(market):
    """
    计算时间衰减信号
    
    Args:
        market: 市场信息 dict，必须包含:
            - yes_price: float
            - end_date: str (ISO格式)
            - category: str (可选)
            - title: str
    
    Returns:
        dict: {
            "signal": float,           # 概率偏移（负=偏向No）
            "days_to_expiry": float,   # 到期天数
            "daily_decay": float,      # 日衰减率
            "category_strength": float, # 类别衰减强度
            "reason": str,
        }
    """
    config = TIME_DECAY_CONFIG
    if not config["enabled"]:
        return _neutral_signal("时间衰减未启用")
    
    yes_price = market.get("yes_price", 0.5)
    category = market.get("category", "Other")
    end_date = market.get("end_date", "")
    title = market.get("title", "")
    
    if not end_date:
        return _neutral_signal("无到期日")
    
    # 1. 计算到期天数
    try:
        if "T" in end_date:
            end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
        else:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        
        now = datetime.now(timezone.utc)
        days_to_expiry = (end_dt - now).total_seconds() / 86400
    except Exception:
        return _neutral_signal("日期解析失败")
    
    # 已过期
    if days_to_expiry <= 0:
        return _neutral_signal("市场已到期")
    
    # 超出时间衰减范围
    if days_to_expiry > config["max_days_to_expiry"]:
        return _neutral_signal(f"距到期{days_to_expiry:.1f}天>{config['max_days_to_expiry']}天")
    
    # 2. Yes价检查
    if yes_price < config["min_yes_price_for_decay"]:
        return _neutral_signal(f"Yes价{yes_price:.0%}<{config['min_yes_price_for_decay']:.0%}，时间衰减意义不大")
    
    # 3. 计算基础衰减信号
    # 越临近到期 → No概率越高 → 信号越偏向No(负数)
    base_decay = config["daily_decay_rate"]
    
    # 时间加速：最后3天衰减加速
    if days_to_expiry <= 3:
        base_decay *= config["acceleration_factor"]
    
    # 计算总衰减：days × daily_rate，但有上限
    total_decay = min(days_to_expiry * base_decay, 0.20)  # 最多偏移20%
    
    # 4. Yes价区间优化
    optimal_min, optimal_max = config["optimal_yes_price_range"]
    if optimal_min <= yes_price <= optimal_max:
        price_bonus = 1.0  # 在最优区间，无调整
    elif yes_price > optimal_max:
        # Yes价很高(>85%)，时间衰减效果更强（过度乐观+时间压力）
        price_bonus = 1.2
    else:
        # Yes价中等偏低，衰减效果较弱
        price_bonus = 0.7
    
    total_decay *= price_bonus
    
    # 5. 类别衰减强度
    cat_strength = config["category_decay_strength"].get(category, 0.9)
    total_decay *= cat_strength
    
    # 6. 特殊处理Crypto市场
    title_lower = title.lower()
    if category == "Crypto" or any(kw in title_lower for kw in ["bitcoin", "btc", "eth", "sol"]):
        # Crypto价格可随时波动，只有"是否达到X价位"类市场时间衰减才弱
        # "谁赢"类市场（如选举）衰减正常
        if any(kw in title_lower for kw in ["reach", "hit", "above", "below", "price", "$"]):
            # 价格目标类 → 时间衰减弱
            total_decay *= 0.5
    
    # 7. 生成信号（负=偏向No）
    signal = -total_decay  # 时间衰减偏向No
    
    # 甜蜜点判断
    sweet_min, sweet_max = config["sweet_spot_days"]
    in_sweet_spot = sweet_min <= days_to_expiry <= sweet_max
    
    reason = f"距到期{days_to_expiry:.1f}天"
    if in_sweet_spot:
        reason += "(甜蜜点!)"
    reason += f"，衰减{total_decay:.1%}，偏向No"
    
    return {
        "signal": signal,
        "days_to_expiry": days_to_expiry,
        "daily_decay": base_decay,
        "category_strength": cat_strength,
        "in_sweet_spot": in_sweet_spot,
        "reason": reason,
    }


def get_time_decay_prob(market, base_prob):
    """
    将时间衰减信号应用到基础概率
    
    Args:
        market: 市场信息 dict
        base_prob: 当前融合概率
    
    Returns:
        float: 调整后概率
    """
    decay = calculate_time_decay_signal(market)
    adjusted = base_prob + decay["signal"]
    return max(0.01, min(0.99, adjusted))


def _neutral_signal(reason=""):
    """返回中性信号"""
    return {
        "signal": 0.0,
        "days_to_expiry": 999,
        "daily_decay": 0,
        "category_strength": 0,
        "in_sweet_spot": False,
        "reason": reason,
    }


# ============ 自测 ============
if __name__ == "__main__":
    print("=== 时间衰减信号测试 ===\n")
    
    now = datetime.now(timezone.utc)
    
    test_markets = [
        {"title": "Will X happen?", "yes_price": 0.75, "category": "Sports",
         "end_date": (now + timedelta(days=2)).isoformat()},
        {"title": "Will Bitcoin reach $200K?", "yes_price": 0.65, "category": "Crypto",
         "end_date": (now + timedelta(days=5)).isoformat()},
        {"title": "Will it rain?", "yes_price": 0.55, "category": "Weather",
         "end_date": (now + timedelta(days=1)).isoformat()},
        {"title": "Will X happen next month?", "yes_price": 0.70, "category": "Politics",
         "end_date": (now + timedelta(days=30)).isoformat()},
    ]
    
    for m in test_markets:
        result = calculate_time_decay_signal(m)
        print(f"📊 {m['title'][:40]} | Yes={m['yes_price']:.0%}")
        print(f"   信号={result['signal']:+.3f} | 到期={result['days_to_expiry']:.1f}天 | {result['reason']}")
        print()
