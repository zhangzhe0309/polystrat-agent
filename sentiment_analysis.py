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
    使用 LLM 分析文本情感
    """
    if not LLM_API_KEY:
        return {"score": 0, "label": "neutral", "confidence": 0, "explanation": "API未配置"}
    
    prompt = f"""分析以下文本的情感倾向，特别关注对预测市场的影响。

文本: {text[:500]}

市场背景: {market_context if market_context else "无"}

请分析：
1. 情感倾向（正面/负面/中性）
2. 情感强度（-1到1的分数，-1为极度负面，1为极度正面）
3. 置信度（0到1）
4. 简要解释

请用JSON格式输出：
{{"score": 0.5, "label": "positive", "confidence": 0.8, "explanation": "..."}}"""

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
                "max_tokens": 200,
                "temperature": 0.1
            },
            timeout=30
        )
        
        if resp.status_code == 200:
            content = resp.json()["choices"][0]["message"]["content"].strip()
            
            # 尝试解析JSON
            try:
                json_match = re.search(r'\{[^}]+\}', content)
                if json_match:
                    result = json.loads(json_match.group())
                    
                    score = float(result.get("score", 0))
                    score = max(-1, min(1, score))
                    
                    label = result.get("label", "neutral")
                    if label not in ["positive", "negative", "neutral"]:
                        label = "neutral"
                    
                    confidence = float(result.get("confidence", 0.5))
                    confidence = max(0, min(1, confidence))
                    
                    return {
                        "score": score,
                        "label": label,
                        "confidence": confidence,
                        "explanation": result.get("explanation", "")
                    }
            except json.JSONDecodeError:
                pass
            
            # 简单判断
            if "positive" in content.lower():
                return {"score": 0.5, "label": "positive", "confidence": 0.6, "explanation": content[:100]}
            elif "negative" in content.lower():
                return {"score": -0.5, "label": "negative", "confidence": 0.6, "explanation": content[:100]}
            else:
                return {"score": 0, "label": "neutral", "confidence": 0.5, "explanation": content[:100]}
        
        else:
            return {"score": 0, "label": "neutral", "confidence": 0, "explanation": f"API错误: {resp.status_code}"}
            
    except Exception as e:
        return {"score": 0, "label": "neutral", "confidence": 0, "explanation": str(e)}

def analyze_sentiment_simple(text):
    """
    简单的情感分析（基于关键词）
    """
    text_lower = text.lower()
    
    positive_words = [
        "bullish", "positive", "good", "great", "excellent", "amazing",
        "win", "success", "growth", "increase", "rise", "up", "high",
        "strong", "powerful", "victory", "triumph", "breakthrough"
    ]
    
    negative_words = [
        "bearish", "negative", "bad", "terrible", "awful", "horrible",
        "lose", "failure", "decline", "decrease", "fall", "down", "low",
        "weak", "powerless", "defeat", "loss", "crash", "collapse"
    ]
    
    positive_count = sum(1 for word in positive_words if word in text_lower)
    negative_count = sum(1 for word in negative_words if word in text_lower)
    
    total = positive_count + negative_count
    if total == 0:
        return {"score": 0, "label": "neutral", "confidence": 0.5, "explanation": "无明显情感词汇"}
    
    score = (positive_count - negative_count) / total
    label = "positive" if score > 0.1 else "negative" if score < -0.1 else "neutral"
    confidence = min(1, total / 10)
    
    return {
        "score": score,
        "label": label,
        "confidence": confidence,
        "explanation": f"正面词: {positive_count}, 负面词: {negative_count}"
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
