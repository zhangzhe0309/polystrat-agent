#!/usr/bin/env python3
"""
情感分析模块
- 分析新闻情感倾向
- 输出情感分数 (-1 到 1)
- 支持多种分析方法
"""
import os
import time
import requests
import json
import re
import hashlib
from collections import OrderedDict
from threading import Lock

# 配置
LLM_API_KEY = os.environ.get("NVIDIA_API_KEY_2", "")
LLM_BASE_URL = "https://integrate.api.nvidia.com/v1"
LLM_MODEL = os.environ.get("SENTIMENT_LLM_MODEL", "qwen/qwen3.5-397b-a17b")
LLM_FALLBACK_MODEL = os.environ.get("SENTIMENT_LLM_FALLBACK", "meta/llama-3.3-70b-instruct")
LLM_TEMPERATURE = float(os.environ.get("SENTIMENT_LLM_TEMPERATURE", "0.3"))

# 情感分析结果缓存（LRU + TTL）
class TTLCache:
    """线程安全的 LRU + TTL 缓存"""
    def __init__(self, maxsize=1000, ttl=3600):
        self.maxsize = maxsize
        self.ttl = ttl
        self._cache = OrderedDict()
        self._lock = Lock()
    
    def get(self, key):
        with self._lock:
            if key in self._cache:
                value, timestamp = self._cache[key]
                if time.time() - timestamp < self.ttl:
                    # 移到末尾 (LRU)
                    self._cache.move_to_end(key)
                    return value
                else:
                    # 过期删除
                    del self._cache[key]
            return None
    
    def set(self, key, value):
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            elif len(self._cache) >= self.maxsize:
                self._cache.popitem(last=False)  # 移除最旧
            self._cache[key] = (value, time.time())
    
    def clear(self):
        """清空缓存"""
        with self._lock:
            self._cache.clear()

    def clear_expired(self):
        """清理过期项"""
        with self._lock:
            now = time.time()
            expired = [k for k, (_, ts) in self._cache.items() if now - ts >= self.ttl]
            for k in expired:
                del self._cache[k]

_sentiment_cache = TTLCache(maxsize=1000, ttl=3600)

def _extract_json_from_llm(content):
    """从 LLM 响应中提取 JSON，支持多种格式"""
    # 1. 尝试直接解析
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # 2. 尝试提取 Markdown 代码块中的 JSON
    code_block_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
    if code_block_match:
        try:
            return json.loads(code_block_match.group(1))
        except json.JSONDecodeError:
            pass

    # 3. 按花括号匹配提取嵌套 JSON
    start = content.find('{')
    if start != -1:
        brace_count = 0
        for i in range(start, len(content)):
            if content[i] == '{':
                brace_count += 1
            elif content[i] == '}':
                brace_count -= 1
            if brace_count == 0:
                try:
                    return json.loads(content[start:i + 1])
                except json.JSONDecodeError:
                    break

    return {}


def _truncate_text(text, max_len=500):
    """按句子边界截断文本，避免在句子中间截断"""
    if len(text) <= max_len:
        return text
    truncated = text[:max_len]
    # 在截断点附近找句子边界
    last_period = truncated.rfind('.')
    last_space = truncated.rfind(' ')
    cut_point = max(last_period, last_space) if max(last_period, last_space) > max_len * 0.8 else max_len
    return text[:cut_point]


def analyze_sentiment_with_llm(text, market_context=""):
    """
    使用 LLM 分析文本情感（优化版：更详细的提示词、更好的解析）

    优化点：
    1. 更详细的提示词（包含预测市场专用指导）
    2. 更好的 JSON 解析（支持嵌套、Markdown 代码块）
    3. 添加关键词提取（便于调试）
    4. 优化置信度计算
    5. 输入验证 + 按句子边界截断
    6. 重试机制（1次重试，处理429/超时）
    """
    # 输入验证
    if not isinstance(text, str) or not text.strip():
        return {"score": 0, "label": "neutral", "confidence": 0, "explanation": "无效输入"}

    if not LLM_API_KEY:
        return {"score": 0, "label": "neutral", "confidence": 0, "explanation": "API未配置"}

    # 内容缓存：相同文本+市场上下文直接返回缓存结果
    cache_key = hashlib.md5(f"{text}||{market_context}".encode('utf-8')).hexdigest()
    cached = _sentiment_cache.get(cache_key)
    if cached is not None:
        return cached

    truncated_text = _truncate_text(text, 500)

    prompt = f"""你是一个专业的情感分析师，专门分析预测市场相关新闻。

请分析以下文本的情感倾向，特别关注对预测市场的影响。

文本: {truncated_text}

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

    models_to_try = [LLM_MODEL]
    if LLM_FALLBACK_MODEL and LLM_FALLBACK_MODEL != LLM_MODEL:
        models_to_try.append(LLM_FALLBACK_MODEL)

    last_error = None
    for model in models_to_try:
        for attempt in range(2):
            try:
                resp = requests.post(
                    f"{LLM_BASE_URL}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {LLM_API_KEY}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 300,
                        "temperature": LLM_TEMPERATURE
                    },
                    timeout=30
                )

                # 429 限流时重试
                if resp.status_code == 429:
                    if attempt < 1:
                        time.sleep(2)
                        continue
                    last_error = "API限流"
                    break  # 跳出重试循环，尝试后备模型

                if resp.status_code == 200:
                    content = resp.json()["choices"][0]["message"]["content"].strip()

                    # 使用增强的 JSON 解析
                    result = _extract_json_from_llm(content)

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
                            keywords = keywords[:3]
                        else:
                            keywords = []

                        _sentiment_cache.set(cache_key, {
                            "score": round(score, 3),
                            "label": label,
                            "confidence": round(confidence, 3),
                            "keywords": keywords,
                            "explanation": result.get("explanation", "")[:200]
                        })
                        return _sentiment_cache.get(cache_key)

                    # JSON 解析失败，使用关键词判断
                    content_lower = content.lower()
                    positive_indicators = ["positive", "bullish", "optimistic", "upbeat", "favorable"]
                    negative_indicators = ["negative", "bearish", "pessimistic", "downbeat", "unfavorable"]

                    pos_count = sum(1 for word in positive_indicators if word in content_lower)
                    neg_count = sum(1 for word in negative_indicators if word in content_lower)

                    if pos_count > neg_count:
                        keyword_result = {"score": 0.5, "label": "positive", "confidence": 0.6, "keywords": [], "explanation": content[:150]}
                        _sentiment_cache.set(cache_key, keyword_result)
                        return keyword_result
                    elif neg_count > pos_count:
                        keyword_result = {"score": -0.5, "label": "negative", "confidence": 0.6, "keywords": [], "explanation": content[:150]}
                        _sentiment_cache.set(cache_key, keyword_result)
                        return keyword_result
                    keyword_result = {"score": 0, "label": "neutral", "confidence": 0.5, "keywords": [], "explanation": content[:150]}
                    _sentiment_cache.set(cache_key, keyword_result)
                    return keyword_result

                # 非 200/429 的其他错误 — 记录错误并尝试后备模型
                last_error = f"API错误: {resp.status_code}"
                break  # 跳出重试循环，尝试后备模型

            except requests.Timeout:
                if attempt < 1:
                    continue
                last_error = "API超时"
                break  # 跳出重试循环，尝试后备模型
            except Exception as e:
                if attempt < 1:
                    continue
                last_error = str(e)[:100]
                break  # 跳出重试循环，尝试后备模型

    # 所有模型均失败
    fallback_result = {"score": 0, "label": "neutral", "confidence": 0, "keywords": [], "explanation": last_error or "所有模型调用失败"}
    _sentiment_cache.set(cache_key, fallback_result)
    return fallback_result

def analyze_sentiment_simple(text):
    """
    简单的情感分析（优化版：更多词汇、权重区分、否定词处理）

    优化点：
    1. 扩展关键词列表（从 36 个扩展到 100+ 个）
    2. 添加权重区分（不同词汇有不同权重）
    3. 添加否定词处理（not、no、never 等）
    4. 添加程度词处理（very、extremely 等）
    5. 添加预测市场专用词汇
    6. 修复词汇冲突：程度副词仅保留在 degree_words 中
    7. 否定词+程度词组合逻辑：否定时弱化而非增强
    8. 基于情感词密度的置信度计算
    """
    # 输入验证
    if not isinstance(text, str) or not text.strip():
        return {"score": 0, "label": "neutral", "confidence": 0.5, "explanation": "无效输入"}

    text_lower = text.lower()
    words = re.findall(r'\b\w+\b', text_lower)

    # 正面词汇（带权重）— 程度副词已移至 degree_words，避免正负冲突
    positive_words = {
        # 强正面（权重 2.0）
        "bullish": 2.0, "surge": 2.0, "soar": 2.0, "skyrocket": 2.0,
        "breakout": 2.0, "boom": 2.0, "rally": 2.0, "triumph": 2.0,
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

    # 负面词汇（带权重）— 程度副词已移至 degree_words，避免正负冲突
    negative_words = {
        # 强负面（权重 2.0）
        "bearish": 2.0, "crash": 2.0, "collapse": 2.0, "plunge": 2.0,
        "freefall": 2.0, "disaster": 2.0, "catastrophe": 2.0, "devastating": 2.0,
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

    # 程度词列表（带乘数）— 含原冲突的程度副词
    degree_words = {
        "very": 1.5, "extremely": 2.0, "incredibly": 2.0, "absolutely": 2.0,
        "completely": 1.5, "totally": 1.5, "utterly": 2.0, "highly": 1.5,
        "strongly": 1.5, "slightly": 0.5, "somewhat": 0.7, "barely": 0.3,
        # 程度副词：从正面/负面列表中移出，作为修饰词
        "overwhelming": 1.8, "decisive": 1.6, "landslide": 1.8,
    }

    # 计算情感分数（考虑否定词和程度词）
    positive_score = 0
    negative_score = 0
    positive_count = 0
    negative_count = 0

    for i, word in enumerate(words):
        # 检查前面是否有否定词（3词窗口）
        is_negated = False
        negation_distance = -1
        for dist in range(1, 4):
            if i >= dist and words[i - dist] in negation_words:
                is_negated = True
                negation_distance = dist
                break

        # 检查前面是否有程度词（3词窗口，但排除否定词本身）
        degree_multiplier = 1.0
        for dist in range(1, 4):
            if i >= dist and words[i - dist] in degree_words:
                degree_multiplier = degree_words[words[i - dist]]
                break

        # 否定词+程度词组合：否定时弱化程度词效果
        # "not very bullish" → 弱正面(0.6x)而非强正面(1.5x)被否定
        if is_negated and degree_multiplier > 1.0:
            degree_multiplier = max(0.3, 1.0 / degree_multiplier)

        # 计算正面分数
        if word in positive_words:
            weight = positive_words[word] * degree_multiplier
            if is_negated:
                negative_score += weight
                negative_count += 1
            else:
                positive_score += weight
                positive_count += 1

        # 计算负面分数
        if word in negative_words:
            weight = negative_words[word] * degree_multiplier
            if is_negated:
                positive_score += weight
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

    # 基于情感词密度的置信度计算（替代简单计数）
    total_text_words = len(words) if words else 1
    sentiment_count = positive_count + negative_count
    sentiment_density = sentiment_count / total_text_words
    # 密度越高越可靠，但至少2个情感词才有较高置信度
    confidence = min(1, sentiment_density * 3)
    if sentiment_count < 2:
        confidence = min(confidence, 0.4)

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
        "keywords": [],
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
        # 降级条件：API不可用(confidence=0)或LLM置信度过低(<0.3)
        if sentiment["confidence"] < 0.3:
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
