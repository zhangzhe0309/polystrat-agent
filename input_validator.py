#!/usr/bin/env python3
"""
输入验证模块
- API 响应验证
- 数据类型检查
- 边界条件验证
"""
from polystrat_logger import log, log_error

def validate_market_data(market):
    """
    验证市场数据
    
    Args:
        market: 市场数据字典
    
    Returns:
        tuple: (是否有效, 错误信息)
    """
    required_fields = ["title", "yes_price", "condition_id"]
    
    for field in required_fields:
        if field not in market:
            return False, f"缺少必需字段: {field}"
    
    # 验证价格范围
    yes_price = market.get("yes_price", 0)
    if not isinstance(yes_price, (int, float)):
        return False, f"yes_price 类型错误: {type(yes_price)}"
    
    if yes_price < 0 or yes_price > 1:
        return False, f"yes_price 超出范围: {yes_price}"
    
    # 验证流动性
    liquidity = market.get("liquidity", 0)
    if not isinstance(liquidity, (int, float)):
        return False, f"liquidity 类型错误: {type(liquidity)}"
    
    if liquidity < 0:
        return False, f"liquidity 不能为负: {liquidity}"
    
    return True, None

def validate_trade_data(trade):
    """
    验证交易数据
    
    Args:
        trade: 交易数据字典
    
    Returns:
        tuple: (是否有效, 错误信息)
    """
    required_fields = ["market", "direction", "amount", "timestamp"]
    
    for field in required_fields:
        if field not in trade:
            return False, f"缺少必需字段: {field}"
    
    # 验证方向
    direction = trade.get("direction")
    if direction not in ["Yes", "No"]:
        return False, f"direction 无效: {direction}"
    
    # 验证金额
    amount = trade.get("amount", 0)
    if not isinstance(amount, (int, float)):
        return False, f"amount 类型错误: {type(amount)}"
    
    if amount <= 0:
        return False, f"amount 必须为正数: {amount}"
    
    # 验证结果（如果存在）
    result = trade.get("result")
    if result and result not in ["win", "lose", "pending", "timeout"]:
        return False, f"result 无效: {result}"
    
    return True, None

def validate_probability(prob, name="probability"):
    """
    验证概率值
    
    Args:
        prob: 概率值
        name: 变量名（用于错误信息）
    
    Returns:
        tuple: (是否有效, 错误信息)
    """
    if not isinstance(prob, (int, float)):
        return False, f"{name} 类型错误: {type(prob)}"
    
    if prob < 0 or prob > 1:
        return False, f"{name} 超出范围 [0,1]: {prob}"
    
    return True, None

def validate_weights(weights):
    """
    验证权重配置
    
    Args:
        weights: 权重字典
    
    Returns:
        tuple: (是否有效, 错误信息)
    """
    if not isinstance(weights, dict):
        return False, "weights 必须是字典"
    
    total = sum(weights.values())
    if abs(total - 1.0) > 0.01:
        return False, f"权重总和应为1.0，实际为{total:.4f}"
    
    for name, weight in weights.items():
        if not isinstance(weight, (int, float)):
            return False, f"权重 {name} 类型错误: {type(weight)}"
        if weight < 0 or weight > 1:
            return False, f"权重 {name} 超出范围 [0,1]: {weight}"
    
    return True, None

def sanitize_input(text, max_length=1000):
    """
    清理输入文本
    
    Args:
        text: 输入文本
        max_length: 最大长度
    
    Returns:
        str: 清理后的文本
    """
    if not isinstance(text, str):
        return ""
    
    # 移除控制字符
    text = ''.join(char for char in text if char.isprintable() or char.isspace())
    
    # 限制长度
    text = text[:max_length]
    
    return text.strip()

if __name__ == "__main__":
    print("=" * 50)
    print("输入验证模块测试")
    print("=" * 50)
    
    # 测试市场数据验证
    print("\n1. 市场数据验证:")
    valid_market = {
        "title": "Test Market",
        "yes_price": 0.65,
        "condition_id": "abc123",
        "liquidity": 10000
    }
    is_valid, error = validate_market_data(valid_market)
    print(f"   有效市场: {is_valid}")
    
    invalid_market = {
        "title": "Test",
        "yes_price": 1.5,  # 超出范围
    }
    is_valid, error = validate_market_data(invalid_market)
    print(f"   无效市场: {is_valid}, 错误: {error}")
    
    # 测试交易数据验证
    print("\n2. 交易数据验证:")
    valid_trade = {
        "market": "Test",
        "direction": "Yes",
        "amount": 2.0,
        "timestamp": "2026-06-25T00:00:00Z"
    }
    is_valid, error = validate_trade_data(valid_trade)
    print(f"   有效交易: {is_valid}")
    
    invalid_trade = {
        "market": "Test",
        "direction": "Maybe",  # 无效方向
        "amount": -1,  # 负数
    }
    is_valid, error = validate_trade_data(invalid_trade)
    print(f"   无效交易: {is_valid}, 错误: {error}")
    
    # 测试概率验证
    print("\n3. 概率验证:")
    print(f"   0.5: {validate_probability(0.5)}")
    print(f"   1.5: {validate_probability(1.5)}")
    
    # 测试权重验证
    print("\n4. 权重验证:")
    valid_weights = {"llm": 0.4, "sentiment": 0.2, "onchain": 0.2, "ml": 0.2}
    print(f"   有效权重: {validate_weights(valid_weights)}")
    
    invalid_weights = {"llm": 0.5, "sentiment": 0.5, "onchain": 0.5}
    print(f"   无效权重: {validate_weights(invalid_weights)}")
    
    print("\n✅ 输入验证模块测试完成")
