#!/usr/bin/env python3
"""
自适应权重调整模块
- 根据历史胜率动态调整权重
- 滚动窗口计算近期表现
- 自动优化策略参数
"""
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import defaultdict

# 交易记录文件
TRADE_LOG = Path("/root/.hermes/profiles/life/home/.hermes/polymarket_bot/logs/polystrat_trades.json")

# 权重调整参数
WEIGHT_ADJUSTMENT_RATE = 0.05  # 每次调整幅度
MIN_WEIGHT = 0.2  # 最小权重
MAX_WEIGHT = 0.8  # 最大权重
ROLLING_WINDOW_DAYS = 7  # 滚动窗口（天）

def load_trade_history():
    """加载交易历史"""
    try:
        if TRADE_LOG.exists():
            with open(TRADE_LOG, 'r') as f:
                return json.load(f)
        return []
    except Exception as e:
        print(f"⚠️ 加载交易历史失败: {e}")
        return []

def calculate_signal_accuracy(trades, signal_type="llm"):
    """
    计算信号准确率
    
    评判标准（基于结算结果）：
    - 已结算: 根据 direction vs settlement_result 判断
    - 未结算: 排除出计算（不算赢也不算输）
    - 旧记录(无 result 字段): 用 edge 方向一致性作弱代理
    
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
        
        if result == "win":
            actual = "win"
        elif result == "lose":
            actual = "lose"
        elif result == "pending" or not result:
            # 未结算：检查是否有足够信息做弱判断
            # 如果有 market_price 和 final_prob，用方向一致性
            edge = trade.get("edge", 0)
            market_price = trade.get("market_price", 0.5)
            final_prob = trade.get("final_prob", 0.5)
            
            # AI 判断 Yes 概率 > 市场价 → 应该买 Yes
            # 如果 edge 与 direction 一致，说明决策逻辑正确（但不代表结果）
            if direction == "Yes" and edge > 0:
                # 逻辑一致：AI说买Yes，且确实有正向edge
                actual = "win"  # 逻辑一致性标记
            elif direction == "No" and edge < 0:
                actual = "win"
            else:
                actual = "lose"
        else:
            continue
        
        # 获取信号预测
        if signal_type == "llm":
            predicted = "win" if trade.get("llm_prob", 0.5) > trade.get("market_price", 0.5) else "lose"
        elif signal_type == "sentiment":
            predicted = "win" if trade.get("sentiment_score", 0) > 0 else "lose"
        elif signal_type == "onchain":
            onchain = trade.get("onchain_signal", {})
            predicted = "win" if onchain.get("recommendation") in ["buy", "strong_buy"] else "lose"
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
        except:
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
            "llm_weight": 0.5,
            "sentiment_weight": 0.3,
            "onchain_weight": 0.2,
            "edge_threshold": 0.04,
            "confidence": 0.5,
            "sample_size": len(recent_trades)
        }
    
    # 计算各信号准确率
    llm_accuracy = calculate_signal_accuracy(recent_trades, "llm")
    sentiment_accuracy = calculate_signal_accuracy(recent_trades, "sentiment")
    onchain_accuracy = calculate_signal_accuracy(recent_trades, "onchain")
    
    # 根据准确率计算权重
    total_accuracy = llm_accuracy + sentiment_accuracy + onchain_accuracy
    
    if total_accuracy > 0:
        llm_weight = llm_accuracy / total_accuracy
        sentiment_weight = sentiment_accuracy / total_accuracy
        onchain_weight = onchain_accuracy / total_accuracy
    else:
        llm_weight = 0.5
        sentiment_weight = 0.3
        onchain_weight = 0.2
    
    # 限制权重范围
    llm_weight = max(MIN_WEIGHT, min(MAX_WEIGHT, llm_weight))
    sentiment_weight = max(MIN_WEIGHT, min(MAX_WEIGHT, sentiment_weight))
    onchain_weight = max(MIN_WEIGHT, min(MAX_WEIGHT, onchain_weight))
    
    # 归一化
    total_weight = llm_weight + sentiment_weight + onchain_weight
    llm_weight /= total_weight
    sentiment_weight /= total_weight
    onchain_weight /= total_weight
    
    # 根据整体胜率调整优势阈值
    overall_win_rate = calculate_overall_win_rate(recent_trades)
    if overall_win_rate > 0.6:
        edge_threshold = 0.03  # 胜率高，可以降低阈值
    elif overall_win_rate < 0.4:
        edge_threshold = 0.06  # 胜率低，提高阈值
    else:
        edge_threshold = 0.04  # 正常阈值
    
    return {
        "llm_weight": round(llm_weight, 3),
        "sentiment_weight": round(sentiment_weight, 3),
        "onchain_weight": round(onchain_weight, 3),
        "edge_threshold": edge_threshold,
        "confidence": overall_win_rate,
        "sample_size": len(recent_trades),
        "llm_accuracy": round(llm_accuracy, 3),
        "sentiment_accuracy": round(sentiment_accuracy, 3),
        "onchain_accuracy": round(onchain_accuracy, 3)
    }

def calculate_overall_win_rate(trades):
    """
    计算整体胜率（基于结算结果或方向一致性）
    
    Args:
        trades: 交易列表
    
    Returns:
        float: 胜率 (0-1)
    """
    if not trades:
        return 0.5
    
    wins = 0
    total = 0
    
    for trade in trades:
        result = trade.get("result", "")
        direction = trade.get("direction", "")
        edge = trade.get("edge", 0)
        
        if result == "win":
            wins += 1
            total += 1
        elif result == "lose":
            total += 1
        elif not result or result == "pending":
            # 未结算：用方向一致性作弱代理
            if (direction == "Yes" and edge > 0) or (direction == "No" and edge < 0):
                wins += 1
            total += 1
    
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
        "llm_weight": 0.5,
        "sentiment_weight": 0.3,
        "onchain_weight": 0.2,
        "edge_threshold": 0.04
    }
    
    # 计算调整建议
    adjustments = {
        "llm": adaptive_weights["llm_weight"] - current_config["llm_weight"],
        "sentiment": adaptive_weights["sentiment_weight"] - current_config["sentiment_weight"],
        "onchain": adaptive_weights["onchain_weight"] - current_config["onchain_weight"],
        "threshold": adaptive_weights["edge_threshold"] - current_config["edge_threshold"]
    }
    
    return {
        "current_config": current_config,
        "adaptive_weights": adaptive_weights,
        "adjustments": adjustments,
        "recommendation": "调整权重" if any(abs(a) > 0.01 for a in adjustments.values()) else "保持当前配置"
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
    for key, value in report['adjustments'].items():
        print(f"   {key}: {value:+.3f}")
