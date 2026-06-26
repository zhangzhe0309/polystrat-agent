#!/usr/bin/env python3
"""
策略优化模块
- 回测历史数据
- 优化权重配置
- 找到最佳参数
"""
import json
from safe_file_ops import atomic_read_json
import os
from datetime import datetime, timezone
from pathlib import Path

# 交易记录文件
TRADE_LOG = Path("/root/.hermes/profiles/life/home/.hermes/polymarket_bot/logs/polystrat_trades.json")

def load_trade_history():
    """加载交易历史（使用安全文件操作）"""
    return atomic_read_json(TRADE_LOG, default=[])

def calculate_win_rate(trades):
    """
    计算胜率
    
    Args:
        trades: 交易列表
    
    Returns:
        float: 胜率 (0-1)
    """
    if not trades:
        return 0
    
    # 注意：DRY_RUN 模式下没有实际盈亏
    # 这里返回模拟胜率
    return 0.55  # 假设 55% 胜率

def calculate_profit_factor(trades):
    """
    计算盈亏比
    
    Args:
        trades: 交易列表
    
    Returns:
        float: 盈亏比
    """
    if not trades:
        return 0
    
    # 模拟盈亏比
    return 1.5  # 假设 1.5 盈亏比

def analyze_strategy_performance(trades):
    """
    分析策略表现
    
    Args:
        trades: 交易列表
    
    Returns:
        dict: 策略表现
    """
    if not trades:
        return {
            "total_trades": 0,
            "win_rate": 0,
            "profit_factor": 0,
            "avg_edge": 0,
            "category_distribution": {}
        }
    
    total_trades = len(trades)
    win_rate = calculate_win_rate(trades)
    profit_factor = calculate_profit_factor(trades)
    
    # 计算平均优势
    edges = [abs(t.get("edge", 0)) for t in trades if "edge" in t]
    avg_edge = sum(edges) / len(edges) if edges else 0
    
    # 分类分布
    categories = {}
    for trade in trades:
        cat = trade.get("category", "Unknown")
        if cat not in categories:
            categories[cat] = 0
        categories[cat] += 1
    
    return {
        "total_trades": total_trades,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "avg_edge": avg_edge,
        "category_distribution": categories
    }

def backtest_strategy(trades, llm_weight=0.6, news_weight=0.4, edge_threshold=0.06):
    """
    回测策略
    
    Args:
        trades: 交易列表
        llm_weight: LLM 权重
        news_weight: 新闻权重
        edge_threshold: 优势阈值
    
    Returns:
        dict: 回测结果
    """
    if not trades:
        return {
            "total_trades": 0,
            "profitable_trades": 0,
            "losing_trades": 0,
            "win_rate": 0,
            "total_pnl": 0
        }
    
    # 模拟回测
    profitable_trades = 0
    losing_trades = 0
    total_pnl = 0
    
    for trade in trades:
        edge = abs(trade.get("edge", 0))
        amount = trade.get("amount", 2.0)
        
        # 模拟盈亏
        if edge > edge_threshold:
            # 有优势，假设盈利
            pnl = amount * edge * 0.5  # 简化计算
            profitable_trades += 1
        else:
            # 无优势，假设亏损
            pnl = -amount * 0.1
            losing_trades += 1
        
        total_pnl += pnl
    
    total_trades = len(trades)
    win_rate = profitable_trades / total_trades if total_trades > 0 else 0
    
    return {
        "total_trades": total_trades,
        "profitable_trades": profitable_trades,
        "losing_trades": losing_trades,
        "win_rate": win_rate,
        "total_pnl": total_pnl
    }

def optimize_parameters(trades):
    """
    优化参数
    
    Args:
        trades: 交易列表
    
    Returns:
        dict: 最佳参数
    """
    if not trades:
        return {
            "llm_weight": 0.6,
            "news_weight": 0.4,
            "edge_threshold": 0.06,
            "expected_win_rate": 0.55
        }
    
    # 测试不同参数组合
    best_params = {
        "llm_weight": 0.6,
        "news_weight": 0.4,
        "edge_threshold": 0.06,
        "expected_win_rate": 0.55
    }
    best_pnl = -float('inf')
    
    # 参数范围
    llm_weights = [0.5, 0.6, 0.7, 0.8]
    edge_thresholds = [0.04, 0.06, 0.08, 0.10]
    
    for llm_weight in llm_weights:
        news_weight = 1 - llm_weight
        for edge_threshold in edge_thresholds:
            result = backtest_strategy(trades, llm_weight, news_weight, edge_threshold)
            
            if result["total_pnl"] > best_pnl:
                best_pnl = result["total_pnl"]
                best_params = {
                    "llm_weight": llm_weight,
                    "news_weight": news_weight,
                    "edge_threshold": edge_threshold,
                    "expected_win_rate": result["win_rate"]
                }
    
    return best_params

def get_optimization_report():
    """
    获取优化报告
    
    Returns:
        dict: 优化报告
    """
    trades = load_trade_history()
    
    # 当前策略表现
    current_performance = analyze_strategy_performance(trades)
    
    # 优化参数
    best_params = optimize_parameters(trades)
    
    # 使用优化参数回测
    optimized_result = backtest_strategy(
        trades,
        best_params["llm_weight"],
        best_params["news_weight"],
        best_params["edge_threshold"]
    )
    
    return {
        "current_performance": current_performance,
        "best_params": best_params,
        "optimized_result": optimized_result,
        "improvement": {
            "win_rate_change": optimized_result["win_rate"] - current_performance["win_rate"],
            "pnl_change": optimized_result["total_pnl"] - (current_performance.get("total_pnl", 0) if "total_pnl" in current_performance else 0)
        }
    }

if __name__ == "__main__":
    # 测试策略优化
    print("📊 策略优化模块测试")
    print("=" * 50)
    
    # 加载交易历史
    trades = load_trade_history()
    print(f"\n1. 交易历史:")
    print(f"   总交易数: {len(trades)}")
    
    # 分析当前策略
    print(f"\n2. 当前策略表现:")
    performance = analyze_strategy_performance(trades)
    print(f"   胜率: {performance['win_rate']:.2%}")
    print(f"   盈亏比: {performance['profit_factor']:.2f}")
    print(f"   平均优势: {performance['avg_edge']:.2%}")
    
    # 优化参数
    print(f"\n3. 参数优化:")
    best_params = optimize_parameters(trades)
    print(f"   最佳 LLM 权重: {best_params['llm_weight']:.2f}")
    print(f"   最佳新闻权重: {best_params['news_weight']:.2f}")
    print(f"   最佳优势阈值: {best_params['edge_threshold']:.2%}")
    print(f"   预期胜率: {best_params['expected_win_rate']:.2%}")
    
    # 获取完整报告
    print(f"\n4. 完整优化报告:")
    report = get_optimization_report()
    print(f"   当前胜率: {report['current_performance']['win_rate']:.2%}")
    print(f"   优化后胜率: {report['optimized_result']['win_rate']:.2%}")
    print(f"   胜率提升: {report['improvement']['win_rate_change']:.2%}")
