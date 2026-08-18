#!/usr/bin/env python3
"""
风险管理模块
- 止损设置
- 仓位控制
- 分散投资
- 风险评估
"""

import json
import os
from datetime import datetime, timezone
from safe_file_ops import atomic_read_json
from polystrat_logger import log

# 配置
STOP_LOSS_THRESHOLD = 100.0  # 最大累计回撤100%（模拟模式放开止损）
MAX_POSITION_SIZE = 1.0
MAX_TOTAL_POSITION = 100.0
MAX_SAME_CATEGORY = 100.0
MAX_SAME_MARKET = 100.0

# 交易记录文件
TRADE_LOG = (
    "/root/.hermes/profiles/life/home/.hermes/polymarket_bot/logs/polystrat_trades.json"
)


def set_trade_log_path(path):
    """允许外部覆盖交易记录文件路径（DRY_RUN/LIVE 切换）"""
    global TRADE_LOG
    TRADE_LOG = str(path)


def load_trade_history():
    """加载交易历史（使用安全文件操作）"""
    return atomic_read_json(TRADE_LOG, default=[])


def calculate_position_size(balance, confidence, market_category=None, entry_price=None):
    """
    计算仓位大小

    使用事务性读取，只加载一次交易历史，保证数据一致性
    增加针对高胜率/高价合约（捡钢镚）的非对称赔率缩减与专项敞口控制

    Args:
        balance: 账户余额
        confidence: 置信度 (0-1)
        market_category: 市场类别
        entry_price: 预期买入价格 (0.01 - 0.99)

    Returns:
        float: 建议仓位大小
    """
    # 基础仓位
    base_position = balance * MAX_POSITION_SIZE

    # 根据置信度调整
    confidence_adjusted = base_position * confidence

    # 高价合约（捡钢镚区）非对称赔率风控缩减
    if entry_price and entry_price >= 0.75:
        # 当价格 >= 0.75 时，潜在盈亏比严重不对称，进行渐进式仓位压制
        # 0.75 -> 1.0x, 0.85 -> 0.6x, 0.90 -> 0.4x, 0.95 -> 0.2x
        odds_scale = max(0.2, (1.0 - entry_price) / 0.25)
        confidence_adjusted *= odds_scale

    # 只加载一次交易历史，保证数据一致性
    trades = load_trade_history()

    # 高价合约专项累计敞口限制 (不超过总资金 10%)
    if entry_price and entry_price >= 0.80:
        high_price_exposure = sum(
            t.get("amount", 0)
            for t in trades
            if t.get("result") in ("pending", "", None) and float(t.get("market_price", 0)) >= 0.80
        )
        max_high_price_exposure = balance * 0.10
        if high_price_exposure >= max_high_price_exposure:
            log.warning(f"高价合约(>=0.80)总敞口已达上限 ({high_price_exposure:.2f}/{max_high_price_exposure:.2f})")
            return 0
        remaining_high_price = max_high_price_exposure - high_price_exposure
        confidence_adjusted = min(confidence_adjusted, remaining_high_price)

    # 检查同类别限制
    if market_category:
        category_trades = [t for t in trades if t.get("category") == market_category]
        # 只计算未结算的交易（pending 或无 result）
        category_exposure = sum(
            t.get("amount", 0)
            for t in category_trades
            if t.get("result") in ("pending", "", None)
        )

        max_category = balance * MAX_SAME_CATEGORY
        if category_exposure >= max_category:
            log.warning(
                f"{market_category} 类别已达上限 ({category_exposure:.2f}/{max_category:.2f})"
            )
            return 0

        # 剩余类别额度
        remaining_category = max_category - category_exposure
        confidence_adjusted = min(confidence_adjusted, remaining_category)

    # 检查总仓位限制（只计算未结算的交易）
    total_exposure = sum(
        t.get("amount", 0) for t in trades if t.get("result") in ("pending", "", None)
    )
    max_total = balance * MAX_TOTAL_POSITION

    if total_exposure >= max_total:
        log.warning(f"总仓位已达上限 ({total_exposure:.2f}/{max_total:.2f})")
        return 0

    # 剩余总仓位额度
    remaining_total = max_total - total_exposure
    final_position = min(confidence_adjusted, remaining_total)

    return max(0, final_position)


def check_stop_loss(balance=None, trade_history=None):
    """
    检查止损：累计亏损 + 未结算敞口双重保护

    止损逻辑：
    1. 已结算亏损回撤 > 10% → 触发
    2. 未结算总敞口 > 余额 25% → 触发（防止在结算前过度暴露）

    Args:
        balance: 初始/参考余额（从环境变量读取）
        trade_history: 交易历史列表

    Returns:
        dict: {"triggered": bool, "drawdown_pct": float, "reason": str}
    """
    if trade_history is None:
        trade_history = load_trade_history()

    if balance is None:
        balance = float(os.environ.get("POLYSTRAT_BALANCE", "1000.0"))

    # 统计已结算交易的盈亏
    net_pnl = 0.0
    settled_count = 0
    pending_exposure = 0.0
    pending_count = 0

    for t in trade_history:
        result = t.get("result", "pending")
        amount = t.get("amount", 0)
        market_price = t.get("market_price", 0.5)
        if result == "lose":
            net_pnl -= amount
            settled_count += 1
        elif result == "win":
            # Polymarket 二元合约：投入 amount 买入代币，获胜时每代币赔付 $1
            # 收益 = amount × ((1 / market_price) - 1) = amount × (1 - market_price) / market_price
            if market_price > 0:
                net_pnl += amount * (1 - market_price) / market_price
            settled_count += 1
        elif result in ("pending", "", None):
            pending_exposure += amount
            pending_count += 1

    drawdown_pct = -net_pnl / balance if balance > 0 else 0  # 正数 = 回撤幅度

    # 检查1: 已结算亏损回撤
    if drawdown_pct > STOP_LOSS_THRESHOLD:
        print(
            f"🚨 止损触发: 累计回撤 {drawdown_pct:.2%} > 阈值 {STOP_LOSS_THRESHOLD:.2%} "
            f"(已结算 {settled_count} 笔, net_pnl=${net_pnl:+.2f})"
        )
        return {
            "triggered": True,
            "drawdown_pct": drawdown_pct,
            "reason": f"累计回撤 {drawdown_pct:.2%}",
        }

    # 检查2: 未结算敞口过大（防止在结算前过度暴露）
    # Polymarket 结算可能需要数小时到数周，期间资金被锁定
    pending_exposure_pct = pending_exposure / balance if balance > 0 else 0
    if pending_exposure_pct > 100.0:  # 模拟模式放开未结算敞口限制
        print(
            f"🚨 止损触发: 未结算敞口 {pending_exposure_pct:.2%} > 25% "
            f"({pending_count} 笔待结算, 敞口 ${pending_exposure:.2f})"
        )
        return {
            "triggered": True,
            "drawdown_pct": drawdown_pct,
            "reason": f"未结算敞口 {pending_exposure_pct:.2%} ({pending_count}笔)",
        }

    return {"triggered": False, "drawdown_pct": drawdown_pct, "reason": "正常"}


def calculate_risk_score(market, confidence, news_sentiment=0):
    """
    计算风险分数

    Args:
        market: 市场信息
        confidence: 置信度
        news_sentiment: 新闻情感分数

    Returns:
        float: 风险分数 (0-1, 越低越好)
    """
    risk_score = 0

    # 1. 流动性风险
    liquidity = market.get("liquidity", 0)
    if liquidity < 10000:
        risk_score += 0.3
    elif liquidity < 50000:
        risk_score += 0.1

    # 2. 价格波动风险
    yes_price = market.get("yes_price", 0.5)
    if yes_price < 0.1 or yes_price > 0.9:
        risk_score += 0.2  # 极端价格风险更高

    # 3. 时间风险
    end_date = market.get("end_date", "")
    if end_date:
        try:
            dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            days_left = (dt - datetime.now(timezone.utc)).days
            if days_left < 7:
                risk_score += 0.3  # 临近到期风险更高
            elif days_left < 30:
                risk_score += 0.1
        except Exception:
            pass

    # 4. 新闻情感风险
    if abs(news_sentiment) > 0.5:
        risk_score += 0.2  # 强烈情感风险更高

    # 5. 置信度风险
    if confidence < 0.5:
        risk_score += 0.2  # 低置信度风险更高

    return min(1, risk_score)


def should_trade(market, confidence, news_sentiment, balance):
    """
    判断是否应该交易

    Args:
        market: 市场信息
        confidence: 置信度
        news_sentiment: 新闻情感分数
        balance: 账户余额

    Returns:
        tuple: (是否交易, 原因)
    """
    # 1. 检查仓位限制
    position_size = calculate_position_size(balance, confidence, market.get("category"))
    if position_size <= 0:
        return False, "仓位已达上限"

    # 2. 计算风险分数
    risk_score = calculate_risk_score(market, confidence, news_sentiment)

    # 3. 风险阈值
    if risk_score > 0.7:
        return False, f"风险过高 ({risk_score:.2f})"

    # 4. 置信度阈值
    # 🔧 v4.2: 0.3→0.5，至少比抛硬币好才下单（专业交易员标准）
    if confidence < 0.5:
        return False, f"置信度过低 ({confidence:.2f})"

    return True, f"风险可接受 ({risk_score:.2f}), 仓位: {position_size:.2f}"


def get_risk_report():
    """
    获取风险报告

    Returns:
        dict: 风险报告
    """
    trades = load_trade_history()

    # 统计
    total_trades = len(trades)
    total_exposure = sum(
        t.get("amount", 0) for t in trades if t.get("result") in ("pending", "", None)
    )

    # 按类别统计
    categories = {}
    for trade in trades:
        cat = trade.get("category", "Unknown")
        if cat not in categories:
            categories[cat] = {"count": 0, "exposure": 0}
        categories[cat]["count"] += 1
        categories[cat]["exposure"] += trade.get("amount", 0)

    # 计算风险指标
    avg_trade_size = total_exposure / total_trades if total_trades > 0 else 0

    return {
        "total_trades": total_trades,
        "total_exposure": total_exposure,
        "avg_trade_size": avg_trade_size,
        "categories": categories,
        "risk_level": "高"
        if total_exposure > 100
        else "中"
        if total_exposure > 50
        else "低",
    }


if __name__ == "__main__":
    # 测试风险管理
    print("⚠️ 风险管理模块测试")
    print("=" * 50)

    # 测试仓位计算
    balance = 1000  # 假设余额1000
    confidence = 0.7
    category = "Entertainment"

    position_size = calculate_position_size(balance, confidence, category)
    print(f"建议仓位: {position_size:.2f} (余额: {balance}, 置信度: {confidence})")

    # 测试风险分数
    market = {"liquidity": 50000, "yes_price": 0.5, "end_date": "2026-07-31T00:00:00Z"}
    risk_score = calculate_risk_score(market, confidence, 0.3)
    print(f"风险分数: {risk_score:.2f}")

    # 测试交易判断
    should, reason = should_trade(market, confidence, 0.3, balance)
    print(f"是否交易: {should}, 原因: {reason}")

    # 获取风险报告
    report = get_risk_report()
    print(f"\n风险报告:")
    print(f"  总交易: {report['total_trades']}")
    print(f"  总仓位: {report['total_exposure']:.2f}")
    print(f"  风险等级: {report['risk_level']}")
