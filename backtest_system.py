#!/usr/bin/env python3
"""
回测系统模块
- 历史数据回测
- 策略验证
- 性能分析
"""
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from polystrat_logger import log, log_error

# 交易记录文件
TRADE_LOG = Path("/root/.hermes/profiles/life/home/.hermes/polymarket_bot/logs/polystrat_trades.json")

def load_trade_history():
    """加载交易历史"""
    try:
        if TRADE_LOG.exists():
            return json.loads(TRADE_LOG.read_text())
        return []
    except Exception as e:
        log_error("backtest", e, "加载交易历史失败")
        return []

def calculate_metrics(trades):
    """
    计算策略性能指标
    
    Args:
        trades: 交易列表
    
    Returns:
        dict: 性能指标
    """
    if not trades:
        return {
            "total_trades": 0,
            "win_rate": 0,
            "total_pnl": 0,
            "avg_pnl": 0,
            "max_drawdown": 0,
            "sharpe_ratio": 0,
            "profit_factor": 0
        }
    
    # 分离已结算和未结算
    settled = [t for t in trades if t.get("result") in ("win", "lose")]
    wins = [t for t in settled if t.get("result") == "win"]
    losses = [t for t in settled if t.get("result") == "lose"]
    
    # 计算基本指标
    total_trades = len(trades)
    settled_trades = len(settled)
    win_count = len(wins)
    loss_count = len(losses)
    
    # 胜率
    win_rate = win_count / settled_trades if settled_trades > 0 else 0
    
    # 盈亏计算
    win_pnl = sum(t.get("pnl", 0) for t in wins)
    loss_pnl = sum(t.get("pnl", 0) for t in losses)
    total_pnl = win_pnl + loss_pnl
    
    # 平均盈亏
    avg_win = win_pnl / win_count if win_count > 0 else 0
    avg_loss = loss_pnl / loss_count if loss_count > 0 else 0
    avg_pnl = total_pnl / settled_trades if settled_trades > 0 else 0
    
    # 盈亏比
    profit_factor = abs(win_pnl / loss_pnl) if loss_pnl != 0 else float('inf')
    
    # 最大回撤（简化计算）
    cumulative_pnl = 0
    max_pnl = 0
    max_drawdown = 0
    
    for t in settled:
        pnl = t.get("pnl", 0)
        cumulative_pnl += pnl
        max_pnl = max(max_pnl, cumulative_pnl)
        drawdown = max_pnl - cumulative_pnl
        max_drawdown = max(max_drawdown, drawdown)
    
    # 夏普比率（简化，假设无风险利率为0）
    if settled_trades > 1:
        pnl_list = [t.get("pnl", 0) for t in settled]
        avg_return = sum(pnl_list) / len(pnl_list)
        std_return = (sum((p - avg_return) ** 2 for p in pnl_list) / len(pnl_list)) ** 0.5
        sharpe_ratio = avg_return / std_return if std_return > 0 else 0
    else:
        sharpe_ratio = 0
    
    return {
        "total_trades": total_trades,
        "settled_trades": settled_trades,
        "win_count": win_count,
        "loss_count": loss_count,
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "avg_pnl": avg_pnl,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "max_drawdown": max_drawdown,
        "sharpe_ratio": sharpe_ratio,
        "profit_factor": profit_factor
    }

def analyze_by_category(trades):
    """
    按类别分析性能
    
    Args:
        trades: 交易列表
    
    Returns:
        dict: 各类别性能
    """
    categories = {}
    
    for trade in trades:
        category = trade.get("category", "Unknown")
        if category not in categories:
            categories[category] = []
        categories[category].append(trade)
    
    results = {}
    for category, cat_trades in categories.items():
        metrics = calculate_metrics(cat_trades)
        results[category] = metrics
    
    return results

def analyze_by_time(trades):
    """
    按时间段分析性能
    
    Args:
        trades: 交易列表
    
    Returns:
        dict: 各时间段性能
    """
    # 按天分组
    daily = {}
    
    for trade in trades:
        timestamp = trade.get("timestamp", "")
        if timestamp:
            try:
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                date_str = dt.strftime("%Y-%m-%d")
                if date_str not in daily:
                    daily[date_str] = []
                daily[date_str].append(trade)
            except:
                pass
    
    results = {}
    for date, day_trades in sorted(daily.items()):
        metrics = calculate_metrics(day_trades)
        results[date] = metrics
    
    return results

def generate_backtest_report(trades=None):
    """
    生成回测报告
    
    Args:
        trades: 交易列表（可选，默认加载历史）
    
    Returns:
        str: 报告内容
    """
    if trades is None:
        trades = load_trade_history()
    
    if not trades:
        return "无交易数据"
    
    # 计算总体指标
    metrics = calculate_metrics(trades)
    
    # 按类别分析
    category_analysis = analyze_by_category(trades)
    
    # 生成报告
    lines = []
    lines.append("📊 PolyStrat 回测报告")
    lines.append("=" * 50)
    lines.append(f"报告时间: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("")
    
    lines.append("📈 总体指标:")
    lines.append(f"  总交易数: {metrics['total_trades']}")
    lines.append(f"  已结算: {metrics['settled_trades']}")
    lines.append(f"  胜率: {metrics['win_rate']:.1%}")
    lines.append(f"  总盈亏: {metrics['total_pnl']:+.2f}")
    lines.append(f"  平均盈亏: {metrics['avg_pnl']:+.2f}")
    lines.append(f"  盈亏比: {metrics['profit_factor']:.2f}")
    lines.append(f"  最大回撤: {metrics['max_drawdown']:.2f}")
    lines.append(f"  夏普比率: {metrics['sharpe_ratio']:.2f}")
    lines.append("")
    
    lines.append("📊 按类别分析:")
    for category, cat_metrics in sorted(category_analysis.items()):
        if cat_metrics['settled_trades'] > 0:
            lines.append(f"  {category}:")
            lines.append(f"    交易数: {cat_metrics['settled_trades']}")
            lines.append(f"    胜率: {cat_metrics['win_rate']:.1%}")
            lines.append(f"    盈亏: {cat_metrics['total_pnl']:+.2f}")
    
    return "\n".join(lines)

if __name__ == "__main__":
    print("=" * 50)
    print("回测系统测试")
    print("=" * 50)
    
    # 加载交易历史
    trades = load_trade_history()
    print(f"\n交易记录: {len(trades)} 笔")
    
    # 生成报告
    report = generate_backtest_report(trades)
    print(f"\n{report}")
    
    print("\n✅ 回测系统测试完成")
