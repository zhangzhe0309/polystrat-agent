#!/usr/bin/env python3
"""
Polymarket 跟单盈亏日报 - no_agent mode (简化版)
- 读取现有的 settlement_log.json
- 汇总今日已结算仓位的盈亏
- 输出日报：总 PnL、胜率、最佳/最差交易
"""

import os
import json
import sys
from datetime import datetime, timezone

# ============ 配置区 ============
SETTLEMENT_LOG = "/root/.hermes/profiles/life/home/.hermes/polymarket_bot/logs/settlement_log.json"
DAILY_REPORT_FILE = "/root/.hermes/profiles/life/home/.hermes/polymarket_bot/logs/daily_pnl_simple.json"

# ============ 主逻辑 ============

def main():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    # 0. 检查上次报告日期
    if os.path.exists(DAILY_REPORT_FILE):
        with open(DAILY_REPORT_FILE) as f:
            last_report = json.load(f)
        if last_report.get("date") == today:
            print(f"[{today}] 今日已报告，跳过")
            sys.exit(0)
    
    # 1. 加载结算日志
    if not os.path.exists(SETTLEMENT_LOG):
        print("ERROR: settlement_log.json 不存在", file=sys.stderr)
        sys.exit(1)
    
    with open(SETTLEMENT_LOG) as f:
        data = json.load(f)
    
    bets = data.get("bets", {})
    if not bets:
        print("[今日无结算数据] 静默")
        sys.exit(0)
    
    # 2. 筛选今日已结算的赌注
    settled_today = []
    for key, bet in bets.items():
        if bet.get("result") not in ("won", "lost"):
            continue
        
        # 检查 checked_at 是否在今天
        checked_at = bet.get("checked_at", "")
        if not checked_at.startswith(today):
            continue
        
        settled_today.append(bet)
    
    if not settled_today:
        print(f"[{today}] 无新结算仓位，静默")
        sys.exit(0)
    
    # 3. 计算统计
    total_pnl = sum(bet.get("profit", 0) for bet in settled_today)
    winning_trades = [b for b in settled_today if b.get("profit", 0) > 0]
    losing_trades = [b for b in settled_today if bet.get("profit", 0) < 0]
    win_rate = len(winning_trades) / len(settled_today) * 100 if settled_today else 0
    
    best_trade = max(settled_today, key=lambda x: x.get("profit", 0)) if settled_today else None
    worst_trade = min(settled_today, key=lambda x: x.get("profit", 0)) if settled_today else None
    
    # 4. 生成消息
    lines = []
    lines.append("📊 Polymarket 跟单日报")
    lines.append(f"日期：{today}")
    lines.append(f"跟单钱包：RN1 (0x2005...75ea)")
    lines.append("")
    lines.append("今日结算概况：")
    lines.append(f"  • 结算笔数：{len(settled_today)}")
    lines.append(f"  • 总 PnL: {total_pnl:+.2f} USDC")
    lines.append(f"  • 胜率：{win_rate:.1f}% ({len(winning_trades)}胜{len(losing_trades)}负)")
    lines.append("")
    
    if best_trade and best_trade.get("profit", 0) > 0:
        lines.append(f"🏆 最佳交易：+{best_trade['profit']:.2f} USDC")
        lines.append(f"   {best_trade['market'][:50]} ({best_trade['outcome']})")
    
    if worst_trade and worst_trade.get("profit", 0) < 0:
        lines.append(f"📉 最差交易：{worst_trade['profit']:.2f} USDC")
        lines.append(f"   {worst_trade['market'][:50]} ({worst_trade['outcome']})")
    
    lines.append("")
    lines.append("明细：")
    for bet in sorted(settled_today, key=lambda x: -x.get("profit", 0))[:10]:
        profit = bet.get("profit", 0)
        pnl_str = f"+{profit:.2f}" if profit > 0 else f"{profit:.2f}"
        emoji = "✅" if profit > 0 else "❌"
        lines.append(f"  {emoji} {pnl_str} USDC | {bet['market'][:40]} ({bet['outcome']})")
    
    if len(settled_today) > 10:
        lines.append(f"  ... 还有 {len(settled_today) - 10} 笔")
    
    # 5. 保存报告
    save_data = {
        "date": today,
        "total_pnl": total_pnl,
        "win_rate": win_rate,
        "trade_count": len(settled_today),
        "trades": [{
            "market": b["market"],
            "outcome": b["outcome"],
            "profit": b.get("profit", 0),
            "result": b["result"],
        } for b in settled_today],
    }
    with open(DAILY_REPORT_FILE, "w") as f:
        json.dump(save_data, f, indent=2, ensure_ascii=False)
    
    # 6. 输出
    print("\n".join(lines))

if __name__ == "__main__":
    main()