#!/usr/bin/env python3
"""
Superforecaster 提示词模块 — 借鉴 Polymarket 官方 agents 框架
- 两阶段 LLM 链：预测 → 交易决策
- 结构化概率估计
- 集成到 PolyStrat 的 LLM 投票系统

来源: https://github.com/Polymarket/agents 的 prompts.py + executor.py
"""

# === 阶段1: Superforecaster 预测提示词 ===
SUPERFORECASTER_SYSTEM = """You are a Superforecaster tasked with correctly predicting the likelihood of events.
Use the following systematic process to develop an accurate prediction:

1. Breaking Down the Question:
   - Decompose the question into smaller, more manageable parts.
   - Identify the key components that need to be addressed to answer the question.

2. Gathering Information:
   - Seek out diverse sources of information.
   - Look for both quantitative data and qualitative insights.
   - Stay updated on relevant news and expert analyses.

3. Consider Base Rates:
   - Use statistical baselines or historical averages as a starting point.
   - Compare the current situation to similar past events to establish a benchmark probability.

4. Identify and Evaluate Factors:
   - List factors that could influence the outcome.
   - Assess the impact of each factor, considering both positive and negative influences.
   - Use evidence to weigh these factors, avoiding over-reliance on any single piece of information.

5. Think Probabilistically:
   - Express predictions in terms of probabilities rather than certainties.
   - Assign likelihoods to different outcomes and avoid binary thinking.
   - Embrace uncertainty and recognize that all forecasts are probabilistic in nature."""


def superforecaster_prompt(question: str, description: str, outcome: str) -> str:
    """
    生成 Superforecaster 提示词
    
    Args:
        question: 市场问题 (e.g., "Will X happen before Y?")
        description: 市场详细描述
        outcome: 结果选项 (e.g., "Yes" or "No")
    
    Returns:
        str: 完整提示词
    """
    return f"""{SUPERFORECASTER_SYSTEM}

Given these steps produce a statement on the probability of outcome=`{outcome}` occurring for the following:

Question: {question}
Description: {description}

Give your response in the following format:

I believe "{question}" has a likelihood `FLOAT` for outcome of `{outcome}`.

Where FLOAT is a number between 0 and 1 representing your probability estimate."""


# === 阶段2: 交易决策提示词 ===
TRADER_SYSTEM = """You are an AI assistant for analyzing prediction markets.
You will be provided with json output for api data from Polymarket.
Polymarket is an online prediction market that lets users bet on the outcome of future events.

Imagine yourself as the top trader on Polymarket, dominating the world of information markets with your keen insights and strategic acumen. You have an extraordinary ability to analyze and interpret data from diverse sources, turning complex information into profitable trading opportunities.
You excel in predicting the outcomes of global events, from political elections to economic developments, using a combination of data analysis and intuition. Your deep understanding of probability and statistics allows you to assess market sentiment and make informed decisions quickly.
Every day, you approach Polymarket with a disciplined strategy, identifying undervalued opportunities and managing your portfolio with precision. You are adept at evaluating the credibility of information and filtering out noise, ensuring that your trades are based on reliable data.
Your adaptability is your greatest asset, enabling you to thrive in a rapidly changing environment. You leverage cutting-edge technology and tools to gain an edge over other traders, constantly seeking innovative ways to enhance your strategies."""


def trade_decision_prompt(prediction: str, outcomes: list, outcome_prices: list) -> str:
    """
    生成交易决策提示词
    
    Args:
        prediction: Superforecaster 的预测结果
        outcomes: 结果选项列表 (e.g., ["Yes", "No"])
        outcome_prices: 当前价格列表 (e.g., ["0.65", "0.35"])
    
    Returns:
        str: 完整提示词
    """
    return f"""{TRADER_SYSTEM}

You made the following prediction for a market: {prediction}

The current outcomes {outcomes} prices are: {outcome_prices}

Given your prediction, respond with a genius trade in the format:
```
    price: FLOAT,
    size: FLOAT,
    side: BUY or SELL,
```

Your trade should approximate price using the likelihood in your prediction.
- price: your estimated fair price (should align with your probability prediction)
- size: percentage of total funds to allocate (0.01 to 0.25, be conservative)
- side: BUY if you think the outcome is undervalued, SELL if overvalued

Example response:
```
    price: 0.5,
    size: 0.1,
    side: BUY,
```"""


# === 辅助函数 ===

def parse_prediction(text: str) -> dict:
    """
    从 Superforecaster 输出中解析概率预测
    
    Args:
        text: LLM 输出文本
    
    Returns:
        dict: {"probability": float, "outcome": str, "raw": str}
    """
    import re
    
    # 尝试匹配 "likelihood `0.7`" 或 "likelihood 0.7"
    match = re.search(r'likelihood\s*`?(\d+\.?\d*)`?\s+for\s+outcome\s+of\s+`?(\w+)`?', text)
    if match:
        prob = float(match.group(1))
        prob = max(0.0, min(1.0, prob))
        return {"probability": prob, "outcome": match.group(2), "raw": text}
    
    # 降级: 找文本中的任何概率数字
    # 先找百分比格式 (如 "22%")
    pct_match = re.search(r'(\d+\.?\d*)\s*%', text)
    if pct_match:
        prob = float(pct_match.group(1)) / 100.0
        prob = max(0.0, min(1.0, prob))
        return {"probability": prob, "outcome": "unknown", "raw": text}
    
    # 再找小数格式 (如 "0.22")
    probs = re.findall(r'(\d+\.?\d*)', text)
    for p in probs:
        val = float(p)
        if 0 < val < 1:
            return {"probability": val, "outcome": "unknown", "raw": text}
    
    return {"probability": 0.5, "outcome": "unknown", "raw": text}


def parse_trade_decision(text: str) -> dict:
    """
    从交易决策输出中解析交易参数
    
    Args:
        text: LLM 输出文本
    
    Returns:
        dict: {"price": float, "size": float, "side": str}
    """
    import re
    
    result = {"price": 0.5, "size": 0.0, "side": "NONE"}
    
    # 解析 price
    price_match = re.search(r'price[:\s]+(\d+\.?\d*)', text, re.IGNORECASE)
    if price_match:
        result["price"] = float(price_match.group(1))
    
    # 解析 size
    size_match = re.search(r'size[:\s]+(\d+\.?\d*)', text, re.IGNORECASE)
    if size_match:
        result["size"] = float(size_match.group(1))
    
    # 解析 side
    side_match = re.search(r'side[:\s]+(BUY|SELL)', text, re.IGNORECASE)
    if side_match:
        result["side"] = side_match.group(1).upper()
    
    return result


# === 市场数据预处理 (来自官方 utils.py) ===

def parse_camel_case(key: str) -> str:
    """驼峰转空格分隔"""
    output = ""
    for char in key:
        if char.isupper():
            output += " " + char.lower()
        else:
            output += char
    return output


def preprocess_market_description(market: dict) -> str:
    """
    增强市场描述，将布尔值和数值字段嵌入描述文本
    用于提升向量搜索/LLM理解效果
    
    来自: agents/utils/utils.py preprocess_market_object
    
    Args:
        market: 市场数据 dict
    
    Returns:
        str: 增强后的描述文本
    """
    description = market.get("description", "") or ""
    
    for k, v in market.items():
        if k == "description":
            continue
        if isinstance(v, bool):
            description += f' This market is{" not" if not v else ""} {parse_camel_case(k)}.'
        if k in ["volume", "liquidity", "volume24hr", "liquidityClob"]:
            if v:
                description += f" This market has a current {k} of {v}."
    
    return description


# === 集成示例 ===

def analyze_market_with_superforecaster(market: dict, llm_call_fn) -> dict:
    """
    完整的两阶段分析流程（可集成到 PolyStrat 的 LLM 投票系统）
    
    Args:
        market: 市场数据 dict (需含 question, description, outcomes, outcomePrices)
        llm_call_fn: LLM 调用函数 fn(prompt) -> str
    
    Returns:
        dict: 完整分析结果
    """
    question = market.get("question", "")
    description = market.get("description", "")
    outcomes = market.get("outcomes", "Yes,No")
    outcome_prices = market.get("outcomePrices", "[0.5, 0.5]")
    
    # 阶段1: Superforecaster 预测
    outcome = outcomes[0] if isinstance(outcomes, list) else "Yes"
    pred_prompt = superforecaster_prompt(question, description, outcome)
    pred_text = llm_call_fn(pred_prompt)
    prediction = parse_prediction(pred_text)
    
    # 阶段2: 交易决策
    trade_prompt = trade_decision_prompt(
        prediction=pred_text,
        outcomes=outcomes if isinstance(outcomes, list) else str(outcomes),
        outcome_prices=outcome_prices if isinstance(outcome_prices, list) else str(outcome_prices)
    )
    trade_text = llm_call_fn(trade_prompt)
    trade = parse_trade_decision(trade_text)
    
    return {
        "prediction": prediction,
        "trade": trade,
        "market_question": question,
        "edge": prediction["probability"] - (float(outcome_prices[0]) if isinstance(outcome_prices, list) and outcome_prices else 0.5),
    }


if __name__ == "__main__":
    # 测试
    print("=== Superforecaster 提示词测试 ===\n")
    
    test_market = {
        "question": "Will Bitcoin reach $100k by end of 2026?",
        "description": "This market resolves to Yes if Bitcoin (BTC) reaches or exceeds $100,000 USD on any major exchange before December 31, 2026 11:59 PM ET.",
        "outcomes": ["Yes", "No"],
        "outcomePrices": ["0.65", "0.35"],
        "volume": 1500000,
        "active": True,
    }
    
    print("1. Superforecaster Prompt:")
    print(superforecaster_prompt(
        test_market["question"], 
        test_market["description"], 
        "Yes"
    )[:500])
    print("...\n")
    
    print("2. Trade Decision Prompt:")
    print(trade_decision_prompt(
        'I believe "Will Bitcoin reach $100k..." has a likelihood `0.72` for outcome of `Yes`.',
        test_market["outcomes"],
        test_market["outcomePrices"]
    )[:500])
    print("...\n")
    
    print("3. Parse Prediction Test:")
    test_output = 'I believe "Will Bitcoin reach $100k by end of 2026?" has a likelihood `0.72` for outcome of `Yes`.'
    print(f"   Input: {test_output}")
    print(f"   Result: {parse_prediction(test_output)}\n")
    
    print("4. Parse Trade Decision Test:")
    test_trade = "    price: 0.72,\n    size: 0.15,\n    side: BUY,\n"
    print(f"   Input: {test_trade}")
    print(f"   Result: {parse_trade_decision(test_trade)}\n")
    
    print("5. Market Description Preprocessing:")
    print(f"   Original: {test_market.get('description', '')[:80]}...")
    print(f"   Enhanced: {preprocess_market_description(test_market)[:120]}...")
