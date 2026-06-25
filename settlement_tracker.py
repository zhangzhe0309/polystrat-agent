#!/usr/bin/env python3
"""
结算追踪模块 v2
自动检查已交易市场的结算状态，更新交易结果，计算实际盈亏
"""
import json
import os
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path
from polystrat_logger import log, log_error
from safe_file_ops import atomic_read_json, atomic_write_json

# 交易记录文件
TRADE_LOG = Path("/root/.hermes/profiles/life/home/.hermes/polymarket_bot/logs/polystrat_trades.json")
GAMMA_API = "https://gamma-api.polymarket.com"

# 结算超时阈值（天）- 超过此时间未结算的市场标记为超时
SETTLEMENT_TIMEOUT_DAYS = 30

def load_trades():
    """加载交易记录（使用安全文件操作）"""
    return atomic_read_json(TRADE_LOG, default=[])

def save_trades(trades):
    """保存交易记录（使用原子写入）"""
    atomic_write_json(TRADE_LOG, trades)

def check_market_batch(condition_ids):
    """
    批量查询市场结算状态（减少API调用）
    
    Args:
        condition_ids: condition_id 列表
    
    Returns:
        dict: {condition_id: {"settled": bool, "outcome": str}}
    """
    results = {}
    
    if not condition_ids:
        return results
    
    try:
        # Gamma API 支持批量查询
        # 但为了稳定性，我们分批处理
        batch_size = 10
        
        for i in range(0, len(condition_ids), batch_size):
            batch = condition_ids[i:i+batch_size]
            
            for cid in batch:
                try:
                    resp = requests.get(
                        f"{GAMMA_API}/markets",
                        params={"conditionId": cid},
                        timeout=10
                    )
                    
                    if resp.status_code == 200:
                        markets = resp.json()
                        if markets:
                            market = markets[0]
                            resolved = market.get("resolved", False)
                            
                            if resolved:
                                outcome_prices = market.get("outcomePrices", "")
                                if isinstance(outcome_prices, str):
                                    try:
                                        prices = json.loads(outcome_prices)
                                    except Exception:
                                        prices = []
                                else:
                                    prices = outcome_prices
                                
                                if prices and len(prices) >= 2:
                                    yes_price = float(prices[0])
                                    if yes_price >= 0.95:
                                        results[cid] = {"settled": True, "outcome": "Yes"}
                                    elif yes_price <= 0.05:
                                        results[cid] = {"settled": True, "outcome": "No"}
                                    else:
                                        results[cid] = {"settled": False, "outcome": None}
                                else:
                                    results[cid] = {"settled": False, "outcome": None}
                            else:
                                results[cid] = {"settled": False, "outcome": None}
                        else:
                            results[cid] = {"settled": False, "outcome": None}
                    else:
                        results[cid] = {"settled": False, "outcome": None}
                        
                except Exception as e:
                    log_error("settlement", e, f"查询失败: {cid[:12]}")
                    results[cid] = {"settled": False, "outcome": None}
                    
    except Exception as e:
        log_error("settlement", e, "批量查询失败")
    
    return results

def calculate_pnl(trade, result):
    """
    计算单笔交易的盈亏
    
    预测市场盈亏计算:
    - 买入 Yes @ 0.60，结算 Yes -> 盈利 0.40/share
    - 买入 Yes @ 0.60，结算 No -> 亏损 0.60/share
    - 买入 No @ 0.40，结算 No -> 盈利 0.60/share
    - 买入 No @ 0.40，结算 Yes -> 亏损 0.40/share
    
    Returns:
        float: 盈亏金额（正=盈利，负=亏损）
    """
    amount = trade.get("amount", 0)
    direction = trade.get("direction", "")
    market_price = trade.get("market_price", 0.5)
    
    if not amount or not direction or not market_price:
        return 0
    
    # 计算 shares 数量
    shares = amount / market_price if market_price > 0 else 0
    
    if result == "win":
        # 盈利 = shares * (1 - 买入价)
        pnl = shares * (1 - market_price)
    else:
        # 亏损 = -amount
        pnl = -amount
    
    return round(pnl, 4)

def determine_trade_result(trade, market_outcome):
    """
    根据市场结算结果判断交易盈亏
    
    Args:
        trade: 交易记录
        market_outcome: 市场结算结果 ("Yes" 或 "No")
    
    Returns:
        str: "win" 或 "lose"
    """
    direction = trade.get("direction", "")
    
    if not direction or not market_outcome:
        return None
    
    # 交易方向与市场结果一致 = 盈利
    if direction == market_outcome:
        return "win"
    else:
        return "lose"

def check_timeout_trades(trades):
    """
    检查超时未结算的交易
    
    超过 SETTLEMENT_TIMEOUT_DAYS 天未结算的市场，标记为 "timeout"
    """
    now = datetime.now(timezone.utc)
    timeout_threshold = now - timedelta(days=SETTLEMENT_TIMEOUT_DAYS)
    
    updated = 0
    for trade in trades:
        if trade.get("result") not in ("pending", "", None):
            continue
        
        end_date = trade.get("end_date", "")
        if not end_date:
            continue
        
        try:
            # 解析结算时间
            if "T" in end_date:
                dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            else:
                dt = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            
            # 如果已超过结算时间 + 超时阈值
            if dt < timeout_threshold:
                trade["result"] = "timeout"
                trade["settlement_time"] = now.isoformat()
                updated += 1
                log.warning(f"超时: {trade.get('market', '')[:40]}")
                
        except Exception:
            continue
    
    if updated > 0:
        log.info(f"标记 {updated} 笔超时交易")
    
    return updated

def update_settled_trades():
    """
    更新已结算的交易记录
    
    Returns:
        dict: 更新统计
    """
    trades = load_trades()
    if not trades:
        return {"total": 0, "checked": 0, "updated": 0}
    
    stats = {
        "total": len(trades),
        "checked": 0,
        "updated": 0,
        "wins": 0,
        "losses": 0,
        "total_pnl": 0,
        "timeout": 0
    }
    
    # 1. 先检查超时交易
    timeout_count = check_timeout_trades(trades)
    stats["timeout"] = timeout_count
    
    # 2. 收集需要查询的 condition_id
    pending_trades = []
    for i, t in enumerate(trades):
        if t.get("result") in ("pending", "", None):
            cid = t.get("condition_id", "")
            if cid:
                pending_trades.append((i, t))
    
    if not pending_trades:
        log.info("没有待结算的交易")
        if timeout_count > 0:
            save_trades(trades)
        return stats
    
    log.info(f"检查 {len(pending_trades)} 笔待结算交易...")
    
    # 3. 批量查询市场状态
    condition_ids = list(set(t.get("condition_id", "") for _, t in pending_trades))
    market_status = check_market_batch(condition_ids)
    stats["checked"] = len(market_status)
    
    # 4. 更新交易结果
    for idx, trade in pending_trades:
        cid = trade.get("condition_id", "")
        
        if cid not in market_status:
            continue
        
        settlement = market_status[cid]
        
        if settlement["settled"] and settlement["outcome"]:
            result = determine_trade_result(trade, settlement["outcome"])
            if result:
                # 计算盈亏
                pnl = calculate_pnl(trade, result)
                
                # 更新记录
                trades[idx]["result"] = result
                trades[idx]["settlement_time"] = datetime.now(timezone.utc).isoformat()
                trades[idx]["market_outcome"] = settlement["outcome"]
                trades[idx]["pnl"] = pnl
                stats["updated"] += 1
                stats["total_pnl"] += pnl
                
                if result == "win":
                    stats["wins"] += 1
                else:
                    stats["losses"] += 1
                
                market = trade.get("market", "")[:40]
                direction = trade.get("direction", "")
                log.info(f"结算: {market} | {direction} vs {settlement['outcome']} = {result} | PnL: {pnl:+.2f}")
    
    # 5. 保存更新
    if stats["updated"] > 0 or stats["timeout"] > 0:
        save_trades(trades)
        log.info(f"更新完成: {stats['wins']}胜 {stats['losses']}负 | 总PnL: {stats['total_pnl']:+.2f}")
    
    return stats

def get_settlement_summary():
    """获取结算统计摘要"""
    trades = load_trades()
    
    total = len(trades)
    settled = len([t for t in trades if t.get("result") in ("win", "lose")])
    pending = len([t for t in trades if t.get("result") in ("pending", "", None)])
    timeout = len([t for t in trades if t.get("result") == "timeout"])
    wins = len([t for t in trades if t.get("result") == "win"])
    losses = len([t for t in trades if t.get("result") == "lose"])
    
    # 计算总盈亏
    total_pnl = sum(t.get("pnl", 0) for t in trades if t.get("pnl") is not None)
    
    # 计算胜率
    win_rate = wins / settled if settled > 0 else 0
    
    # 计算平均盈利/亏损
    win_pnl = [t.get("pnl", 0) for t in trades if t.get("result") == "win" and t.get("pnl")]
    lose_pnl = [t.get("pnl", 0) for t in trades if t.get("result") == "lose" and t.get("pnl")]
    
    avg_win = sum(win_pnl) / len(win_pnl) if win_pnl else 0
    avg_lose = sum(lose_pnl) / len(lose_pnl) if lose_pnl else 0
    
    return {
        "total": total,
        "settled": settled,
        "pending": pending,
        "timeout": timeout,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "avg_win": avg_win,
        "avg_lose": avg_lose,
        "profit_factor": abs(avg_win / avg_lose) if avg_lose != 0 else 0
    }

def format_settlement_report():
    """格式化结算报告"""
    summary = get_settlement_summary()
    
    lines = []
    lines.append("📊 PolyStrat 结算追踪报告")
    lines.append("=" * 40)
    lines.append(f"总交易: {summary['total']} 笔")
    lines.append(f"已结算: {summary['settled']} 笔")
    lines.append(f"待结算: {summary['pending']} 笔")
    lines.append(f"超时:   {summary['timeout']} 笔")
    lines.append("")
    lines.append(f"胜率:   {summary['win_rate']:.1%}")
    lines.append(f"总盈亏: {summary['total_pnl']:+.2f}")
    lines.append(f"平均盈利: {summary['avg_win']:+.2f}")
    lines.append(f"平均亏损: {summary['avg_lose']:+.2f}")
    lines.append(f"盈亏比: {summary['profit_factor']:.2f}")
    
    return "\n".join(lines)

if __name__ == "__main__":
    print("=" * 50)
    print("结算追踪模块 v2 测试")
    print("=" * 50)
    
    # 获取当前状态
    summary = get_settlement_summary()
    print(f"\n📊 当前状态:")
    print(f"   总交易: {summary['total']}")
    print(f"   已结算: {summary['settled']}")
    print(f"   待结算: {summary['pending']}")
    print(f"   超时: {summary['timeout']}")
    print(f"   胜率: {summary['win_rate']:.1%}")
    print(f"   总盈亏: {summary['total_pnl']:+.2f}")
    
    # 更新结算
    print(f"\n🔄 检查结算状态...")
    stats = update_settled_trades()
    print(f"   检查: {stats['checked']} 个市场")
    print(f"   更新: {stats['updated']} 笔交易")
    print(f"   胜: {stats['wins']}, 负: {stats['losses']}")
    print(f"   盈亏: {stats['total_pnl']:+.2f}")
    print(f"   超时: {stats['timeout']}")
    
    # 打印报告
    print(f"\n{format_settlement_report()}")
    
    print("\n✅ 结算追踪模块测试完成")
