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

# 配置
STOP_LOSS_THRESHOLD = -0.10  # 最大亏损10%
MAX_POSITION_SIZE = 0.05  # 单笔最大5%资金
MAX_TOTAL_POSITION = 0.30  # 总仓位最大30%
MAX_SAME_CATEGORY = 0.20  # 同一类别最大20%
MAX_SAME_MARKET = 0.10  # 同一市场最大10%

# 交易记录文件
TRADE_LOG = "/root/.hermes/profiles/life/home/.hermes/polymarket_bot/logs/polystrat_trades.json"

def load_trade_history():
    """加载交易历史"""
    try:
        if os.path.exists(TRADE_LOG):
            with open(TRADE_LOG, 'r') as f:
                return json.load(f)
        return []
    except Exception as e:
        print(f"⚠️ 加载交易历史失败: {e}")
        return []

def calculate_position_size(balance, confidence, market_category=None):
    """
    计算仓位大小
    
    Args:
        balance: 账户余额
        confidence: 置信度 (0-1)
        market_category: 市场类别
    
    Returns:
        float: 建议仓位大小
    """
    # 基础仓位
    base_position = balance * MAX_POSITION_SIZE
    
    # 根据置信度调整
    confidence_adjusted = base_position * confidence
    
    # 检查同类别限制
    if market_category:
        trades = load_trade_history()
        category_trades = [t for t in trades if t.get("category") == market_category]
        category_exposure = sum(t.get("amount", 0) for t in category_trades)
        
        max_category = balance * MAX_SAME_CATEGORY
        if category_exposure >= max_category:
            print(f"⚠️ {market_category} 类别已达上限 ({category_exposure:.2f}/{max_category:.2f})")
            return 0
        
        # 剩余类别额度
        remaining_category = max_category - category_exposure
        confidence_adjusted = min(confidence_adjusted, remaining_category)
    
    # 检查总仓位限制
    trades = load_trade_history()
    total_exposure = sum(t.get("amount", 0) for t in trades if t.get("status") == "DRY_RUN")
    max_total = balance * MAX_TOTAL_POSITION
    
    if total_exposure >= max_total:
        print(f"⚠️ 总仓位已达上限 ({total_exposure:.2f}/{max_total:.2f})")
        return 0
    
    # 剩余总仓位额度
    remaining_total = max_total - total_exposure
    final_position = min(confidence_adjusted, remaining_total)
    
    return max(0, final_position)

def check_stop_loss(position):
    """
    检查止损
    
    Args:
        position: 仓位信息
    
    Returns:
        bool: 是否触发止损
    """
    pnl = position.get("pnl", 0)
    
    if pnl < STOP_LOSS_THRESHOLD:
        print(f"🚨 止损触发: PnL {pnl:.2%} < 阈值 {STOP_LOSS_THRESHOLD:.2%}")
        return True
    
    return False

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
    if confidence < 0.3:
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
    total_exposure = sum(t.get("amount", 0) for t in trades if t.get("status") == "DRY_RUN")
    
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
        "risk_level": "高" if total_exposure > 100 else "中" if total_exposure > 50 else "低"
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
    market = {
        "liquidity": 50000,
        "yes_price": 0.5,
        "end_date": "2026-07-31T00:00:00Z"
    }
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
