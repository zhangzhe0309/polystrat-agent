# PolyStrat 情感分析模块 — 独立诊断 Prompt

将以下内容完整复制给目标模型即可。

---

## 诊断指令

你是一位高级 Python 代码审查专家，专精于金融预测市场系统。请对以下情感分析模块及其集成代码进行全面诊断。

### 诊断维度（每项给出 CRITICAL / HIGH / MEDIUM / LOW 评级 + 具体行号）

1. **功能完整性**：模块是否覆盖了预测市场情感分析的核心需求？缺少什么功能？
2. **代码正确性**：逻辑 Bug、边界情况、类型安全、竞态条件
3. **集成质量**：sentiment_analysis.py ↔ polystrat_agent.py ↔ adaptive_weights.py 之间的数据流是否正确？有无断裂点？
4. **鲁棒性**：异常处理、降级策略、输入验证是否完善？
5. **性能**：LLM 调用超时、重复计算、内存泄漏风险
6. **安全**：API Key 管理、输入注入、日志泄露
7. **可测试性**：模块是否易于单元测试和 Mock？测试覆盖是否充分？
8. **可维护性**：代码结构、命名、文档、SOLID/DRY/KISS 原则遵循度

### 输出格式

```
## [CRITICAL/HIGH/MEDIUM/LOW] 问题标题
- **文件**: 文件名:行号
- **问题**: 详细描述
- **影响**: 对系统的实际影响
- **建议**: 具体修复方案（含代码片段）
```

最后给出：
- **总体评估**：APPROVE / CONDITIONAL / BLOCK
- **必须修复项**：列出所有 CRITICAL + HIGH 问题
- **改进建议**：MEDIUM + LOW 的优先排序

---

## 文件1: sentiment_analysis.py（核心模块）

```python
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

# 配置
LLM_API_KEY = os.environ.get("NVIDIA_API_KEY_2", "")
LLM_BASE_URL = "https://integrate.api.nvidia.com/v1"
LLM_MODEL = "qwen/qwen3.5-397b-a17b"

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

    for attempt in range(2):
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

            # 429 限流时重试
            if resp.status_code == 429:
                if attempt < 1:
                    time.sleep(2)
                    continue
                return {"score": 0, "label": "neutral", "confidence": 0, "keywords": [], "explanation": "API限流"}

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

                pos_count = sum(1 for word in positive_indicators if word in content_lower)
                neg_count = sum(1 for word in negative_indicators if word in content_lower)

                if pos_count > neg_count:
                    return {"score": 0.5, "label": "positive", "confidence": 0.6, "keywords": [], "explanation": content[:150]}
                elif neg_count > pos_count:
                    return {"score": -0.5, "label": "negative", "confidence": 0.6, "keywords": [], "explanation": content[:150]}
                else:
                    return {"score": 0, "label": "neutral", "confidence": 0.5, "keywords": [], "explanation": content[:150]}

            # 非 200/429 的其他错误
            return {"score": 0, "label": "neutral", "confidence": 0, "keywords": [], "explanation": f"API错误: {resp.status_code}"}

        except requests.Timeout:
            if attempt < 1:
                continue
            return {"score": 0, "label": "neutral", "confidence": 0, "keywords": [], "explanation": "API超时"}
        except Exception as e:
            if attempt < 1:
                continue
            return {"score": 0, "label": "neutral", "confidence": 0, "keywords": [], "explanation": str(e)[:100]}

    return {"score": 0, "label": "neutral", "confidence": 0, "keywords": [], "explanation": "重试失败"}

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
    print("情感分析模块测试")
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
```

---

## 文件2: polystrat_agent.py（集成方，仅情感分析相关片段）

### 导入部分 (第31行)
```python
from sentiment_analysis import analyze_news_sentiment
```

### 权重配置 (第146-152行)
```python
SIGNAL_WEIGHTS = {
    "llm": 0.20,
    "sentiment": 0.15,   # 新闻情感权重
    "onchain": 0.25,
    "ml": 0.25,
    "microstructure": 0.15,
}
```

### 主循环初始化 (第873-877行)
```python
for market in markets:
    title = market["title"]
    yes_price = market["yes_price"]
    category = market.get("category", "Other")
    liquidity = market.get("liquidity", 0)
    condition_id = market.get("condition_id", "")

    # 初始化所有信号的默认值（防止 NameError）
    microstructure_signal = {"recommendation": "hold", "confidence": 0.3}
```

### 情感分析主流程 (第944-967行)
```python
        # 3. 情感分析（LLM优先 + 关键词降级，置信度加权聚合）
        try:
            if news_list:
                # 使用 analyze_news_sentiment：LLM优先，低置信度自动降级为关键词
                # 分析更多新闻（最多5条），保留真实置信度
                analysis_limit = min(len(news_list), 5)
                sentiment_result = analyze_news_sentiment(
                    news_list[:analysis_limit], market_context=title
                )
                sentiment_score = sentiment_result["overall_score"]
                sentiment_confidence = sentiment_result["confidence"]
            else:
                sentiment_score = 0
                sentiment_confidence = 0
        except Exception as e:
            sentiment_score = 0
            sentiment_confidence = 0
            print(f"⚠️ 情感分析失败: {e}")
```

### 情感信号→概率映射 (第1076-1082行)
```python
        # 信号2: 情感概率（将 sentiment_score 转换为概率）
        # 使用自适应映射斜率（基于情感信号历史准确率）
        sentiment_mapping_slope = adaptive_weights.get("sentiment_mapping_slope", 0.40)
        sentiment_signal_prob = 0.5 + sentiment_score * sentiment_mapping_slope
        # 放宽截断范围，允许情感信号产生更强影响
        sentiment_signal_prob = max(0.10, min(0.90, sentiment_signal_prob))
        if sentiment_score == 0 and sentiment_confidence == 0:
            signal_fallbacks += 1  # 情感信号完全回退
```

### 风险检查 (第1182-1183行)
```python
        # 7. 风险检查（使用投票置信度，默认中性值 0.5）
        voting_confidence = vote_details.get("confidence", 0.5)
```

---

## 文件3: adaptive_weights.py（映射斜率相关片段）

### 情感映射斜率 (第250-257行)
```python
    # 自适应情感映射斜率（无数据时用默认 0.40）
    sentiment_accuracy = sent_acc if sent_acc is not None else 0.5
    if sentiment_accuracy > 0.6:
        sentiment_mapping_slope = 0.55
    elif sentiment_accuracy < 0.4:
        sentiment_mapping_slope = 0.25
    else:
        sentiment_mapping_slope = 0.40
```

---

## 文件4: test_polystrat.py（情感分析测试，完整）

```python
class TestSentimentAnalysis(unittest.TestCase):
    """情感分析模块测试"""

    def setUp(self):
        from sentiment_analysis import analyze_sentiment_simple
        self.analyze_sentiment_simple = analyze_sentiment_simple

    def test_positive_sentiment(self):
        """正面情感识别"""
        result = self.analyze_sentiment_simple("Bitcoin surges to new highs, bullish sentiment")
        self.assertGreater(result["score"], 0)

    def test_negative_sentiment(self):
        """负面情感识别"""
        result = self.analyze_sentiment_simple("Market crash expected, bearish sentiment widespread")
        self.assertLess(result["score"], 0)

    def test_neutral_sentiment(self):
        """中性情感识别"""
        result = self.analyze_sentiment_simple("The weather is cloudy today")
        self.assertEqual(result["score"], 0)

    def test_negation_reverses_sentiment(self):
        """否定词应反转情感方向"""
        bullish = self.analyze_sentiment_simple("bullish market outlook")
        not_bullish = self.analyze_sentiment_simple("not bullish market outlook")
        self.assertLess(not_bullish["score"], bullish["score"],
                        "否定词应降低正面分数")

    def test_degree_words_amplify(self):
        """程度词应增强情感强度（多词场景下归一化前权重更大）"""
        bullish = self.analyze_sentiment_simple("bullish market optimistic outlook")
        very_bullish = self.analyze_sentiment_simple("very bullish market optimistic outlook")
        self.assertGreaterEqual(very_bullish["confidence"], bullish["confidence"],
                                "very 应提升情感置信度")

    def test_degree_words_diminish(self):
        """弱化程度词应降低情感置信度（多词场景）"""
        bullish = self.analyze_sentiment_simple("bullish market optimistic outlook")
        slightly_bullish = self.analyze_sentiment_simple("slightly bullish market optimistic outlook")
        self.assertLessEqual(slightly_bullish["confidence"], bullish["confidence"] + 0.1,
                             "slightly 不应大幅增加置信度")

    def test_negation_with_degree_word(self):
        """否定词+程度词组合应弱化而非增强"""
        very_bullish = self.analyze_sentiment_simple("very bullish market")
        not_very_bullish = self.analyze_sentiment_simple("not very bullish market")
        self.assertLess(not_very_bullish["score"], very_bullish["score"],
                        "否定+程度词组合应弱化情感")

    def test_overwhelming_as_degree_word(self):
        """程度副词不再出现在正负面列表中，避免冲突"""
        victory = self.analyze_sentiment_simple("overwhelming victory")
        defeat = self.analyze_sentiment_simple("overwhelming defeat")
        self.assertGreater(victory["score"], defeat["score"],
                           "overwhelming victory 应比 overwhelming defeat 更正面")

    def test_empty_input(self):
        """空输入应返回中性"""
        result = self.analyze_sentiment_simple("")
        self.assertEqual(result["score"], 0)
        self.assertEqual(result["label"], "neutral")

    def test_none_input(self):
        """None 输入应返回中性"""
        result = self.analyze_sentiment_simple(None)
        self.assertEqual(result["score"], 0)

    def test_numeric_input(self):
        """数字输入应返回中性"""
        result = self.analyze_sentiment_simple(12345)
        self.assertEqual(result["score"], 0)

    def test_output_structure(self):
        """输出结构应包含所有必要字段"""
        result = self.analyze_sentiment_simple("bullish outlook")
        self.assertIn("score", result)
        self.assertIn("label", result)
        self.assertIn("confidence", result)
        self.assertIn("explanation", result)
        self.assertIn(result["label"], ["positive", "negative", "neutral"])

    def test_score_bounded(self):
        """分数应在 [-1, 1] 范围内"""
        result = self.analyze_sentiment_simple(
            "bullish surge skyrocket rally optimistic favorable great excellent amazing"
        )
        self.assertGreaterEqual(result["score"], -1)
        self.assertLessEqual(result["score"], 1)

    def test_confidence_bounded(self):
        """置信度应在 [0, 1] 范围内"""
        result = self.analyze_sentiment_simple("bullish market outlook today")
        self.assertGreaterEqual(result["confidence"], 0)
        self.assertLessEqual(result["confidence"], 1)
```

---

## 已知修复历史（供交叉验证）

以下问题已在近期修复，请验证修复质量：

1. **词汇冲突**：`overwhelming`/`decisive`/`landslide` 原先同时出现在正面和负面列表，已移至 `degree_words`
2. **LLM 情感分析被绕过**：原主流程只用 `analyze_sentiment_simple`，已改为 `analyze_news_sentiment`（LLM优先+自动降级）
3. **microstructure_signal 未初始化**：已添加默认值
4. **否定词+程度词冲突**：原代码 "not very bullish" 会增强正面，现改为弱化
5. **sentiment_confidence 硬编码 0.5**：已改为使用分析器返回的真实置信度
6. **只分析2条新闻**：已扩展为5条
7. **映射截断过窄**：`max(0.15, min(0.85))` → `max(0.10, min(0.90))`
8. **JSON 解析脆弱**：已支持嵌套 JSON 和 Markdown 代码块
9. **LLM 无重试**：已添加1次重试
10. **输入无验证**：已添加类型检查

请验证以上修复是否彻底，是否引入新问题，以及是否仍有遗漏。
