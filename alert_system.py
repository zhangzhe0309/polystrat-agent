#!/usr/bin/env python3
"""
告警系统模块
- 异常检测
- 阈值告警
- 通知推送
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from polystrat_logger import log, log_error

# 告警日志文件
from config_center import ALERT_LOG
ALERT_LOG.parent.mkdir(parents=True, exist_ok=True)

# 告警配置
ALERT_THRESHOLDS = {
    "max_loss_per_trade": -10.0,  # 单笔最大亏损
    "max_daily_loss": -50.0,      # 每日最大亏损
    "max_drawdown": -100.0,       # 最大回撤
    "min_win_rate": 0.3,          # 最低胜率
    "max_disagreement": 30,       # 最大投票分歧
    "min_confidence": 0.4,        # 最低置信度
}

def check_trade_alerts(trade):
    """
    检查交易告警
    
    Args:
        trade: 交易数据
    
    Returns:
        list: 告警列表
    """
    alerts = []
    
    # 检查亏损
    pnl = trade.get("pnl", 0)
    if pnl < ALERT_THRESHOLDS["max_loss_per_trade"]:
        alerts.append({
            "type": "large_loss",
            "level": "warning",
            "message": f"单笔亏损过大: {pnl:.2f}",
            "threshold": ALERT_THRESHOLDS["max_loss_per_trade"],
            "value": pnl
        })
    
    # 检查投票分歧
    vote_details = trade.get("vote_details", {})
    disagreement = vote_details.get("disagreement", 0)
    if disagreement > ALERT_THRESHOLDS["max_disagreement"]:
        alerts.append({
            "type": "high_disagreement",
            "level": "warning",
            "message": f"投票分歧过大: {disagreement:.1f}%",
            "threshold": ALERT_THRESHOLDS["max_disagreement"],
            "value": disagreement
        })
    
    # 检查置信度
    confidence = vote_details.get("confidence", 1)
    if confidence < ALERT_THRESHOLDS["min_confidence"]:
        alerts.append({
            "type": "low_confidence",
            "level": "warning",
            "message": f"置信度过低: {confidence:.2f}",
            "threshold": ALERT_THRESHOLDS["min_confidence"],
            "value": confidence
        })
    
    return alerts

def check_daily_alerts(trades):
    """
    检查每日告警
    
    Args:
        trades: 今日交易列表
    
    Returns:
        list: 告警列表
    """
    alerts = []
    
    # 计算今日盈亏
    daily_pnl = sum(t.get("pnl", 0) for t in trades)
    if daily_pnl < ALERT_THRESHOLDS["max_daily_loss"]:
        alerts.append({
            "type": "daily_loss",
            "level": "critical",
            "message": f"今日亏损过大: {daily_pnl:.2f}",
            "threshold": ALERT_THRESHOLDS["max_daily_loss"],
            "value": daily_pnl
        })
    
    # 计算胜率
    settled = [t for t in trades if t.get("result") in ("win", "lose")]
    if len(settled) >= 5:
        wins = len([t for t in settled if t.get("result") == "win"])
        win_rate = wins / len(settled)
        if win_rate < ALERT_THRESHOLDS["min_win_rate"]:
            alerts.append({
                "type": "low_win_rate",
                "level": "warning",
                "message": f"胜率过低: {win_rate:.1%}",
                "threshold": ALERT_THRESHOLDS["min_win_rate"],
                "value": win_rate
            })
    
    return alerts

def save_alert(alert):
    """
    保存告警记录
    
    Args:
        alert: 告警数据
    """
    try:
        alerts = []
        if ALERT_LOG.exists():
            alerts = json.loads(ALERT_LOG.read_text())
        
        alert["timestamp"] = datetime.now(timezone.utc).isoformat()
        alerts.append(alert)
        
        # 只保留最近100条
        if len(alerts) > 100:
            alerts = alerts[-100:]
        
        ALERT_LOG.write_text(json.dumps(alerts, indent=2, ensure_ascii=False))
    except Exception as e:
        log_error("alert", e, "保存告警失败")

def process_alerts(alerts):
    """
    处理告警（记录日志+保存）
    
    Args:
        alerts: 告警列表
    """
    for alert in alerts:
        level = alert.get("level", "info")
        message = alert.get("message", "")
        
        # 记录日志
        if level == "critical":
            log.error(f"🚨 告警: {message}")
        elif level == "warning":
            log.warning(f"⚠️ 告警: {message}")
        else:
            log.info(f"ℹ️ 告警: {message}")
        
        # 保存告警
        save_alert(alert)

def get_recent_alerts(limit=10):
    """
    获取最近告警
    
    Args:
        limit: 返回数量
    
    Returns:
        list: 告警列表
    """
    try:
        if ALERT_LOG.exists():
            alerts = json.loads(ALERT_LOG.read_text())
            return alerts[-limit:]
        return []
    except Exception as e:
        log_error("alert", e, "获取告警失败")
        return []

def format_alert_report(alerts=None):
    """
    格式化告警报告
    
    Args:
        alerts: 告警列表（可选）
    
    Returns:
        str: 报告内容
    """
    if alerts is None:
        alerts = get_recent_alerts(20)
    
    if not alerts:
        return "无告警记录"
    
    lines = []
    lines.append("🚨 告警报告")
    lines.append("=" * 50)
    lines.append(f"最近 {len(alerts)} 条告警")
    lines.append("")
    
    for alert in alerts:
        level = alert.get("level", "info")
        emoji = "🚨" if level == "critical" else "⚠️" if level == "warning" else "ℹ️"
        
        lines.append(f"{emoji} [{alert.get('timestamp', '')[:16]}]")
        lines.append(f"  类型: {alert.get('type', '')}")
        lines.append(f"  消息: {alert.get('message', '')}")
        lines.append("")
    
    return "\n".join(lines)

if __name__ == "__main__":
    print("=" * 50)
    print("告警系统测试")
    print("=" * 50)
    
    # 测试交易告警
    print("\n1. 交易告警测试:")
    test_trade = {
        "pnl": -15,
        "vote_details": {
            "disagreement": 35,
            "confidence": 0.3
        }
    }
    alerts = check_trade_alerts(test_trade)
    print(f"   发现 {len(alerts)} 个告警")
    for a in alerts:
        print(f"   - {a['type']}: {a['message']}")
    
    # 处理告警
    process_alerts(alerts)
    
    # 获取最近告警
    print("\n2. 最近告警:")
    recent = get_recent_alerts(5)
    print(f"   {len(recent)} 条告警记录")
    
    # 打印报告
    print(f"\n{format_alert_report()}")
    
    print("\n✅ 告警系统测试完成")
