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


def set_trade_log_path(path):
    """允许外部覆盖交易记录文件路径（DRY_RUN/LIVE 切换）"""
    global TRADE_LOG
    TRADE_LOG = Path(path)


def load_trade_history():
    """加载交易历史（使用安全文件操作）"""
    return atomic_read_json(TRADE_LOG, default=[])


def calculate_signal_accuracy(trades, signal_type="llm", min_samples=3):
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
        min_samples: 最少样本要求（低于此返回 None）

    Returns:
        tuple: (准确率或 None, 样本数)
    """
    if not trades:
        return (None, 0)

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
            continue

        # 获取信号预测（direction感知）
        if signal_type == "llm":
            llm_prob = trade.get("llm_prob", 0.5)
            mp = trade.get("market_price", 0.5)
            if direction == "Yes":
                predicted = "win" if llm_prob > mp else "lose"
            elif direction == "No":
                predicted = "win" if llm_prob < mp else "lose"
            else:
                continue
        elif signal_type == "sentiment":
            sentiment = trade.get("sentiment_score", 0)
            if direction == "Yes":
                predicted = "win" if sentiment > 0 else "lose"
            elif direction == "No":
                predicted = "win" if sentiment < 0 else "lose"
            else:
                continue
        elif signal_type == "onchain":
            onchain = trade.get("onchain_signal", {})
            rec = onchain.get("recommendation", "hold")
            if rec in ["buy", "strong_buy"]:
                predicted = "win" if direction == "Yes" else "lose"
            elif rec in ["sell", "strong_sell"]:
                predicted = "win" if direction == "No" else "lose"
            else:
                continue
        elif signal_type == "ml":
            ml_prob = trade.get("ml_prob", 0.5)
            mp = trade.get("market_price", 0.5)
            if direction == "Yes":
                predicted = "win" if ml_prob > mp else "lose"
            elif direction == "No":
                predicted = "win" if ml_prob < mp else "lose"
            else:
                continue
        else:
            continue

        if predicted == actual:
            correct += 1
        total += 1

    if total < min_samples:
        return (None, total)
    return (correct / total, total)


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

    # 计算各信号准确率（返回 (accuracy_or_None, samples)）
    llm_acc, llm_n = calculate_signal_accuracy(recent_trades, "llm")
    sent_acc, sent_n = calculate_signal_accuracy(recent_trades, "sentiment")
    onch_acc, onch_n = calculate_signal_accuracy(recent_trades, "onchain")
    ml_acc, ml_n = calculate_signal_accuracy(recent_trades, "ml")

    # 只使用有足够数据的信号计算权重，无数据信号给最小基准权重
    signal_accs = {
        "llm": llm_acc,
        "sentiment": sent_acc,
        "onchain": onch_acc,
        "ml": ml_acc,
    }
    valid_weights = {}
    for name, acc in signal_accs.items():
        if acc is not None:
            valid_weights[name] = acc
        else:
            valid_weights[name] = None

    # 有数据的信号按准确率分配，无数据的给基准 0.1
    BASE_WEIGHT = 0.1
    raw_weights = {}
    total_valid_accuracy = 0
    for name, acc in valid_weights.items():
        if acc is not None:
            raw_weights[name] = acc
            total_valid_accuracy += acc
        else:
            raw_weights[name] = None  # 稍后分配基准

    if total_valid_accuracy > 0:
        for name in raw_weights:
            if raw_weights[name] is not None:
                raw_weights[name] /= total_valid_accuracy
            else:
                raw_weights[name] = BASE_WEIGHT
    else:
        # 全部无数据 → 均匀分配
        for name in raw_weights:
            raw_weights[name] = 0.25

    llm_weight = raw_weights["llm"]
    sentiment_weight = raw_weights["sentiment"]
    onchain_weight = raw_weights["onchain"]
    ml_weight = raw_weights["ml"]

    # 归一化
    total_raw = llm_weight + sentiment_weight + onchain_weight + ml_weight
    llm_weight /= total_raw
    sentiment_weight /= total_raw
    onchain_weight /= total_raw
    ml_weight /= total_raw

    # 限幅后再次归一化
    llm_weight = max(MIN_WEIGHT, min(MAX_WEIGHT, llm_weight))
    sentiment_weight = max(MIN_WEIGHT, min(MAX_WEIGHT, sentiment_weight))
    onchain_weight = max(MIN_WEIGHT, min(MAX_WEIGHT, onchain_weight))
    ml_weight = max(MIN_WEIGHT, min(MAX_WEIGHT, ml_weight))
    total_clamped = llm_weight + sentiment_weight + onchain_weight + ml_weight
    llm_weight /= total_clamped
    sentiment_weight /= total_clamped
    onchain_weight /= total_clamped
    ml_weight /= total_clamped

    # 根据整体胜率调整优势阈值
    overall_win_rate = calculate_overall_win_rate(recent_trades)
    if overall_win_rate > 0.6:
        edge_threshold = 0.03
    elif overall_win_rate < 0.4:
        edge_threshold = 0.06
    else:
        edge_threshold = 0.04

    # 自适应情感映射斜率（无数据时用默认 0.35）
    sentiment_accuracy = sent_acc if sent_acc is not None else 0.5
    if sentiment_accuracy > 0.6:
        sentiment_mapping_slope = 0.45
    elif sentiment_accuracy < 0.4:
        sentiment_mapping_slope = 0.25
    else:
        sentiment_mapping_slope = 0.35

    # 自适应链上信号乘数
    onchain_accuracy = onch_acc if onch_acc is not None else 0.5
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
        "llm_accuracy": round(llm_acc, 3) if llm_acc is not None else None,
        "sentiment_accuracy": round(sent_acc, 3) if sent_acc is not None else None,
        "onchain_accuracy": round(onch_acc, 3) if onch_acc is not None else None,
        "ml_accuracy": round(ml_acc, 3) if ml_acc is not None else None,
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
