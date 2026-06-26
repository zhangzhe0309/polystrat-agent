#!/usr/bin/env python3
"""
情感分析模块
- 分析新闻情感倾向
- 输出情感分数 (-1 到 1)
- 支持多种分析方法
"""
import os
import requests
import json
import re

# 配置
LLM_API_KEY = os.environ.get("NVIDIA_API_KEY_2", "")
LLM_BASE_URL = "https://integrate.api.nvidia.com/v1"
LLM_MODEL = "qwen/qwen3.5-397b-a17b"

def analyze_sentiment_with_llm(text, market_context=""):
    """
    使用 LLM 分析文本情感（优化版：更详细的提示词、更好的解析）

    优化点：
    1. 更详细的提示词（包含预测市场专用指导）
    2. 更好的 JSON 解析（处理多种格式）
    3. 添加关键词提取（便于调试）
    4. 优化置信度计算
    """
    if not LLM_API_KEY:
        return {"score": 0, "label": "neutral", "confidence": 0, "explanation": "API未配置"}

    prompt = f"""你是一个专业的情感分析师，专门分析预测市场相关新闻。

请分析以下文本的情感倾向，特别关注对预测市场的影响。

文本: {text[:500]}

市场背景: {market_context if market_context else "无"}

分析指导：
1. 关注预测市场相关术语（如：odds, probability, likelihood, chance, prediction）
2. 关注市场情绪词（如：bullish, bearish, optimistic, pessimistic）
3. 关注事件结果词（如：win, lose, success, failure, victory, defeat）
4. 关注程度词（如：very, extremely, slightly, somewhat）
5. 关注否定词（如：not, no, never, unlikely）

请分析：
1. 情感倾向（positive/negative/neutral）
2. 情感强度（-1到1的分数，-1为极度负面，1为极度正面）
3. 置信度（0到1，基于文本明确性）
4. 关键情感词（提取2-3个关键情感词）
5. 简要解释

请用JSON格式输出：
{{"score": 0.5, "label": "positive", "confidence": 0.8, "keywords": ["bullish", "surge"], "explanation": "文本表达了对市场上涨的乐观情绪"}}"""

    try:
        resp = requests.post(
            f"{LLM_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {LLM_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": LLM_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 300,
                "temperature": 0.1
            },
            timeout=30
        )

        if resp.status_code == 200:
            content = resp.json()["choices"][0]["message"]["content"].strip()

            # 尝试解析JSON（支持多种格式）
            try:
                # 尝试直接解析
                result = json.loads(content)
            except json.JSONDecodeError:
                # 尝试提取 JSON 部分
                json_match = re.search(r'\{[^}]+\}', content, re.DOTALL)
                if json_match:
                    try:
                        result = json.loads(json_match.group())
                    except json.JSONDecodeError:
                        result = {}
                else:
                    result = {}

            if result:
                score = float(result.get("score", 0))
                score = max(-1, min(1, score))

                label = result.get("label", "neutral")
                if label not in ["positive", "negative", "neutral"]:
                    label = "neutral"

                confidence = float(result.get("confidence", 0.5))
                confidence = max(0, min(1, confidence))

                keywords = result.get("keywords", [])
                if isinstance(keywords, list):
                    keywords = keywords[:3]  # 最多3个关键词
                else:
                    keywords = []

                return {
                    "score": round(score, 3),
                    "label": label,
                    "confidence": round(confidence, 3),
                    "keywords": keywords,
                    "explanation": result.get("explanation", "")[:200]
                }

            # JSON 解析失败，使用关键词判断
            content_lower = content.lower()
            positive_indicators = ["positive", "bullish", "optimistic", "upbeat", "favorable"]
            negative_indicators = ["negative", "bearish", "pessimistic", "downbeat", "unfavorable"]

            positive_count = sum(1 for word in positive_indicators if word in content_lower)
            negative_count = sum(1 for word in negative_indicators if word in content_lower)

            if positive_count > negative_count:
                return {"score": 0.5, "label": "positive", "confidence": 0.6, "keywords": [], "explanation": content[:150]}
            elif negative_count > positive_count:
                return {"score": -0.5, "label": "negative", "confidence": 0.6, "keywords": [], "explanation": content[:150]}
            else:
                return {"score": 0, "label": "neutral", "confidence": 0.5, "keywords": [], "explanation": content[:150]}

        else:
            return {"score": 0, "label": "neutral", "confidence": 0, "keywords": [], "explanation": f"API错误: {resp.status_code}"}

    except Exception as e:
        return {"score": 0, "label": "neutral", "confidence": 0, "keywords": [], "explanation": str(e)[:100]}

def analyze_sentiment_simple(text):
    """
    简单的情感分析（优化版：更多词汇、权重区分、否定词处理）

    优化点：
    1. 扩展关键词列表（从 36 个扩展到 100+ 个）
    2. 添加权重区分（不同词汇有不同权重）
    3. 添加否定词处理（not、no、never 等）
    4. 添加程度词处理（very、extremely 等）
    5. 添加预测市场专用词汇
    """
    text_lower = text.lower()
    words = re.findall(r'\b\w+\b', text_lower)

    # 正面词汇（带权重）
    positive_words = {
        # 强正面（权重 2.0）
        "bullish": 2.0, "surge": 2.0, "soar": 2.0, "skyrocket": 2.0,
        "breakout": 2.0, "boom": 2.0, "rally": 2.0, "triumph": 2.0,
        "landslide": 2.0, "overwhelming": 2.0, "decisive": 2.0,
        # 中等正面（权重 1.5）
        "positive": 1.5, "good": 1.5, "great": 1.5, "excellent": 1.5,
        "amazing": 1.5, "win": 1.5, "success": 1.5, "growth": 1.5,
        "increase": 1.5, "rise": 1.5, "strong": 1.5, "powerful": 1.5,
        "victory": 1.5, "momentum": 1.5, "optimistic": 1.5, "hopeful": 1.5,
        "promising": 1.5, "favorable": 1.5, "advantage": 1.5, "lead": 1.5,
        # 弱正面（权重 1.0）
        "up": 1.0, "high": 1.0, "gain": 1.0, "improve": 1.0,
        "recover": 1.0, "rebound": 1.0, "stable": 1.0, "steady": 1.0,
        "support": 1.0, "backing": 1.0, "endorse": 1.0, "approve": 1.0,
        "confident": 1.0, "certain": 1.0, "likely": 1.0, "probable": 1.0,
    }

    # 负面词汇（带权重）
    negative_words = {
        # 强负面（权重 2.0）
        "bearish": 2.0, "crash": 2.0, "collapse": 2.0, "plunge": 2.0,
        "freefall": 2.0, "disaster": 2.0, "catastrophe": 2.0, "devastating": 2.0,
        "overwhelming": 2.0, "decisive": 2.0, "landslide": 2.0,
        # 中等负面（权重 1.5）
        "negative": 1.5, "bad": 1.5, "terrible": 1.5, "awful": 1.5,
        "horrible": 1.5, "lose": 1.5, "failure": 1.5, "decline": 1.5,
        "decrease": 1.5, "fall": 1.5, "weak": 1.5, "powerless": 1.5,
        "defeat": 1.5, "loss": 1.5, "pessimistic": 1.5, "hopeless": 1.5,
        "unfavorable": 1.5, "disadvantage": 1.5, "trail": 1.5, "behind": 1.5,
        # 弱负面（权重 1.0）
        "down": 1.0, "low": 1.0, "drop": 1.0, "dip": 1.0,
        "slip": 1.0, "slide": 1.0, "retreat": 1.0, "pullback": 1.0,
        "uncertain": 1.0, "unsure": 1.0, "doubt": 1.0, "fear": 1.0,
        "worry": 1.0, "concern": 1.0, "risk": 1.0, "threat": 1.0,
    }

    # 否定词列表
    negation_words = {"not", "no", "never", "neither", "nobody", "nothing",
                      "nowhere", "nor", "cannot", "can't", "won't", "don't",
                      "doesn't", "didn't", "isn't", "aren't", "wasn't", "weren't"}

    # 程度词列表（带乘数）
    degree_words = {
        "very": 1.5, "extremely": 2.0, "incredibly": 2.0, "absolutely": 2.0,
        "completely": 1.5, "totally": 1.5, "utterly": 2.0, "highly": 1.5,
        "strongly": 1.5, "slightly": 0.5, "somewhat": 0.7, "barely": 0.3,
    }

    # 计算情感分数（考虑否定词和程度词）
    positive_score = 0
    negative_score = 0
    positive_count = 0
    negative_count = 0

    for i, word in enumerate(words):
        # 检查前面是否有否定词
        is_negated = False
        if i > 0 and words[i-1] in negation_words:
            is_negated = True
        if i > 1 and words[i-2] in negation_words:
            is_negated = True

        # 检查前面是否有程度词
        degree_multiplier = 1.0
        if i > 0 and words[i-1] in degree_words:
            degree_multiplier = degree_words[words[i-1]]
        if i > 1 and words[i-2] in degree_words:
            degree_multiplier = degree_words[words[i-2]]

        # 计算正面分数
        if word in positive_words:
            weight = positive_words[word] * degree_multiplier
            if is_negated:
                negative_score += weight  # 否定正面词变为负面
                negative_count += 1
            else:
                positive_score += weight
                positive_count += 1

        # 计算负面分数
        if word in negative_words:
            weight = negative_words[word] * degree_multiplier
            if is_negated:
                positive_score += weight  # 否定负面词变为正面
                positive_count += 1
            else:
                negative_score += weight
                negative_count += 1

    # 计算总分
    total_score = positive_score + negative_score
    if total_score == 0:
        return {"score": 0, "label": "neutral", "confidence": 0.5, "explanation": "无明显情感词汇"}

    # 归一化分数到 -1 到 1
    score = (positive_score - negative_score) / total_score
    score = max(-1, min(1, score))

    # 计算置信度（基于词汇数量和权重）
    total_words = positive_count + negative_count
    confidence = min(1, total_words / 5)  # 5个词汇达到最高置信度

    # 生成标签
    if score > 0.1:
        label = "positive"
    elif score < -0.1:
        label = "negative"
    else:
        label = "neutral"

    return {
        "score": round(score, 3),
        "label": label,
        "confidence": round(confidence, 3),
        "explanation": f"正面词: {positive_count} (权重: {positive_score:.1f}), 负面词: {negative_count} (权重: {negative_score:.1f})"
    }

def analyze_news_sentiment(news_list, market_context=""):
    """
    分析新闻列表的整体情感
    """
    if not news_list:
        return {
            "overall_score": 0,
            "overall_label": "neutral",
            "confidence": 0,
            "news_count": 0,
            "details": []
        }
    
    scores = []
    details = []
    
    for news in news_list:
        text = news.get("text", news.get("title", news.get("description", "")))
        if not text:
            continue
        
        sentiment = analyze_sentiment_with_llm(text, market_context)
        if sentiment["confidence"] == 0:
            sentiment = analyze_sentiment_simple(text)
        
        scores.append(sentiment["score"])
        details.append({
            "text": text[:100],
            "score": sentiment["score"],
            "label": sentiment["label"],
            "confidence": sentiment["confidence"]
        })
    
    if not scores:
        return {
            "overall_score": 0,
            "overall_label": "neutral",
            "confidence": 0,
            "news_count": 0,
            "details": []
        }
    
    total_confidence = sum(d["confidence"] for d in details)
    if total_confidence > 0:
        weighted_score = sum(d["score"] * d["confidence"] for d in details) / total_confidence
    else:
        weighted_score = sum(scores) / len(scores)
    
    if weighted_score > 0.1:
        overall_label = "positive"
    elif weighted_score < -0.1:
        overall_label = "negative"
    else:
        overall_label = "neutral"
    
    avg_confidence = sum(d["confidence"] for d in details) / len(details)
    
    return {
        "overall_score": weighted_score,
        "overall_label": overall_label,
        "confidence": avg_confidence,
        "news_count": len(details),
        "details": details
    }

if __name__ == "__main__":
    print("😊 情感分析模块测试")
    print("=" * 50)
    
    test_texts = [
        "Trump is leading in the polls, positive outlook for his presidency.",
        "Market crash expected, negative sentiment widespread.",
        "Weather forecast shows mixed conditions.",
        "Bitcoin surges to new highs, bullish sentiment.",
        "Economic recession fears grow, bearish market."
    ]
    
    for text in test_texts:
        print(f"\n文本: {text[:50]}...")
        simple_result = analyze_sentiment_simple(text)
        print(f"  简单分析: {simple_result['label']} ({simple_result['score']:.2f})")
        llm_result = analyze_sentiment_with_llm(text)
        print(f"  LLM分析: {llm_result['label']} ({llm_result['score']:.2f})")
