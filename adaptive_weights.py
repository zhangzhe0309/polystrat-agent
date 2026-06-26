#!/usr/bin/env python3
"""
自适应权重调整模块
- 根据历史胜率动态调整权重
- 滚动窗口计算近期表现
- 自动优化策略参数
"""

import json
from safe_file_ops import atomic_read_json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import defaultdict

# 交易记录文件
TRADE_LOG = Path(
    "/root/.hermes/profiles/life/home/.hermes/polymarket_bot/logs/polystrat_trades.json"
)

# 权重调整参数
WEIGHT_ADJUSTMENT_RATE = 0.05  # 每次调整幅度
MIN_WEIGHT = 0.2  # 最小权重
MAX_WEIGHT = 0.8  # 最大权重
ROLLING_WINDOW_DAYS = 7  # 滚动窗口（天）


def load_trade_history():
    """加载交易历史（使用安全文件操作）"""
    return atomic_read_json(TRADE_LOG, default=[])


def calculate_signal_accuracy(trades, signal_type="llm"):
    """
    计算信号准确率

    评判标准（基于结算结果）：
    - 已结算: 根据 direction vs settlement_result 判断
    - 未结算: 排除出计算（不算赢也不算输）
    - 旧记录(无 result 字段): 排除出计算

    注意：不能用 edge 方向一致性作弱代理，这是数据泄露！

    Args:
        trades: 交易列表
        signal_type: 信号类型 (llm, sentiment, onchain)

    Returns:
        float: 准确率 (0-1)
    """
    if not trades:
        return 0.5  # 默认 50%

    correct = 0
    total = 0

    for trade in trades:
        result = trade.get("result", "")
        direction = trade.get("direction", "")

        # 只使用已结算的交易
        if result == "win":
            actual = "win"
        elif result == "lose":
            actual = "lose"
        else:
            # 未结算或无结果：跳过，不计入统计
            # 注意：不能用 edge 方向一致性，这是数据泄露！
            continue

        # 获取信号预测
        if signal_type == "llm":
            predicted = (
                "win"
                if trade.get("llm_prob", 0.5) > trade.get("market_price", 0.5)
                else "lose"
            )
        elif signal_type == "sentiment":
            predicted = "win" if trade.get("sentiment_score", 0) > 0 else "lose"
        elif signal_type == "onchain":
            onchain = trade.get("onchain_signal", {})
            rec = onchain.get("recommendation", "hold")
            if rec in ["buy", "strong_buy"]:
                predicted = "win"
            elif rec == "sell":
                predicted = "lose"
            else:
                # hold = 中性信号，不计入准确率
                continue
        elif signal_type == "ml":
            predicted = (
                "win"
                if trade.get("ml_prob", 0.5) > trade.get("market_price", 0.5)
                else "lose"
            )
        else:
            continue

        if predicted == actual:
            correct += 1
        total += 1

    return correct / total if total > 0 else 0.5


def get_recent_trades(trades, days=ROLLING_WINDOW_DAYS):
    """
    获取最近N天的交易

    Args:
        trades: 交易列表
        days: 天数

    Returns:
        list: 最近交易
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    recent = []
    for trade in trades:
        try:
            timestamp = trade.get("timestamp", "")
            if timestamp:
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                if dt >= cutoff:
                    recent.append(trade)
        except Exception:
            continue

    return recent


def calculate_adaptive_weights(trades):
    """
    计算自适应权重

    Args:
        trades: 交易列表

    Returns:
        dict: 权重配置
    """
    # 获取最近交易
    recent_trades = get_recent_trades(trades, ROLLING_WINDOW_DAYS)

    if len(recent_trades) < 5:
        # 交易太少，使用默认权重
        return {
            "llm_weight": 0.25,
            "sentiment_weight": 0.15,
            "onchain_weight": 0.30,
            "ml_weight": 0.30,
            "edge_threshold": 0.04,
            "confidence": 0.5,
            "sample_size": len(recent_trades),
        }

    # 计算各信号准确率
    llm_accuracy = calculate_signal_accuracy(recent_trades, "llm")
    sentiment_accuracy = calculate_signal_accuracy(recent_trades, "sentiment")
    onchain_accuracy = calculate_signal_accuracy(recent_trades, "onchain")
    ml_accuracy = calculate_signal_accuracy(recent_trades, "ml")

    # 根据准确率计算权重
    total_accuracy = llm_accuracy + sentiment_accuracy + onchain_accuracy + ml_accuracy

    if total_accuracy > 0:
        llm_weight = llm_accuracy / total_accuracy
        sentiment_weight = sentiment_accuracy / total_accuracy
        onchain_weight = onchain_accuracy / total_accuracy
        ml_weight = ml_accuracy / total_accuracy
    else:
        llm_weight = 0.25
        sentiment_weight = 0.15
        onchain_weight = 0.30
        ml_weight = 0.30

    # 限制权重范围
    llm_weight = max(MIN_WEIGHT, min(MAX_WEIGHT, llm_weight))
    sentiment_weight = max(MIN_WEIGHT, min(MAX_WEIGHT, sentiment_weight))
    onchain_weight = max(MIN_WEIGHT, min(MAX_WEIGHT, onchain_weight))
    ml_weight = max(MIN_WEIGHT, min(MAX_WEIGHT, ml_weight))

    # 归一化
    total_weight = llm_weight + sentiment_weight + onchain_weight + ml_weight
    llm_weight /= total_weight
    sentiment_weight /= total_weight
    onchain_weight /= total_weight
    ml_weight /= total_weight

    # 根据整体胜率调整优势阈值
    overall_win_rate = calculate_overall_win_rate(recent_trades)
    if overall_win_rate > 0.6:
        edge_threshold = 0.03  # 胜率高，可以降低阈值
    elif overall_win_rate < 0.4:
        edge_threshold = 0.06  # 胜率低，提高阈值
    else:
        edge_threshold = 0.04  # 正常阈值

    # 自适应情感映射斜率（基于情感信号历史准确率）
    # 准确率高 → 扩大映射范围（让情感更有影响力）
    # 准确率低 → 缩小映射范围（抑制噪声）
    if sentiment_accuracy > 0.6:
        sentiment_mapping_slope = 0.45
    elif sentiment_accuracy < 0.4:
        sentiment_mapping_slope = 0.25
    else:
        sentiment_mapping_slope = 0.35

    # 自适应链上信号乘数（基于链上信号历史准确率）
    # 准确率高 → 加大链上信号置信度影响力
    # 准确率低 → 降低链上信号置信度影响力
    if onchain_accuracy > 0.6:
        onchain_multiplier = 1.3
    elif onchain_accuracy < 0.4:
        onchain_multiplier = 0.7
    else:
        onchain_multiplier = 1.0

    return {
        "llm_weight": round(llm_weight, 3),
        "sentiment_weight": round(sentiment_weight, 3),
        "onchain_weight": round(onchain_weight, 3),
        "ml_weight": round(ml_weight, 3),
        "edge_threshold": edge_threshold,
        "confidence": overall_win_rate,
        "sample_size": len(recent_trades),
        "llm_accuracy": round(llm_accuracy, 3),
        "sentiment_accuracy": round(sentiment_accuracy, 3),
        "onchain_accuracy": round(onchain_accuracy, 3),
        "ml_accuracy": round(ml_accuracy, 3),
        "sentiment_mapping_slope": sentiment_mapping_slope,
        "onchain_multiplier": onchain_multiplier,
    }


def calculate_overall_win_rate(trades):
    """
    计算整体胜率（仅基于已结算结果）

    注意：不能用 edge 方向一致性作弱代理，这是数据泄露！

    Args:
        trades: 交易列表

    Returns:
        float: 胜率 (0-1)，如果没有已结算交易返回 0.5
    """
    if not trades:
        return 0.5

    wins = 0
    total = 0

    for trade in trades:
        result = trade.get("result", "")

        # 只使用已结算的交易
        if result == "win":
            wins += 1
            total += 1
        elif result == "lose":
            total += 1
        else:
            # 未结算或无结果：跳过
            # 注意：不能用 edge 方向一致性，这是数据泄露！
            continue

    return wins / total if total > 0 else 0.5


def get_weight_adjustment_report():
    """
    获取权重调整报告

    Returns:
        dict: 权重调整报告
    """
    trades = load_trade_history()

    # 计算自适应权重
    adaptive_weights = calculate_adaptive_weights(trades)

    # 获取当前配置
    current_config = {
        "llm_weight": 0.25,
        "sentiment_weight": 0.15,
        "onchain_weight": 0.30,
        "ml_weight": 0.30,
        "edge_threshold": 0.04,
    }

    adjustments = {
        "llm": adaptive_weights["llm_weight"] - current_config["llm_weight"],
        "sentiment": adaptive_weights["sentiment_weight"]
        - current_config["sentiment_weight"],
        "onchain": adaptive_weights["onchain_weight"]
        - current_config["onchain_weight"],
        "ml": adaptive_weights["ml_weight"] - current_config["ml_weight"],
        "threshold": adaptive_weights["edge_threshold"]
        - current_config["edge_threshold"],
    }

    return {
        "current_config": current_config,
        "adaptive_weights": adaptive_weights,
        "adjustments": adjustments,
        "recommendation": "调整权重"
        if any(abs(a) > 0.01 for a in adjustments.values())
        else "保持当前配置",
    }


if __name__ == "__main__":
    # 测试自适应权重调整
    print("⚖️ 自适应权重调整模块测试")
    print("=" * 50)

    # 加载交易历史
    trades = load_trade_history()
    print(f"\n1. 交易历史:")
    print(f"   总交易数: {len(trades)}")

    # 计算自适应权重
    print(f"\n2. 自适应权重计算:")
    weights = calculate_adaptive_weights(trades)
    print(f"   LLM 权重: {weights['llm_weight']:.3f}")
    print(f"   情感权重: {weights['sentiment_weight']:.3f}")
    print(f"   链上权重: {weights['onchain_weight']:.3f}")
    print(f"   优势阈值: {weights['edge_threshold']:.2%}")
    print(f"   置信度: {weights['confidence']:.2%}")
    print(f"   样本大小: {weights['sample_size']}")

    # 获取调整报告
    print(f"\n3. 权重调整报告:")
    report = get_weight_adjustment_report()
    print(f"   当前配置: {report['current_config']}")
    print(f"   建议权重: {report['adaptive_weights']}")
    print(f"   调整建议: {report['recommendation']}")

    # 显示调整幅度
    print(f"\n4. 调整幅度:")
    for key, value in report["adjustments"].items():
        print(f"   {key}: {value:+.3f}")
