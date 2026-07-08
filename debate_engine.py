#!/usr/bin/env python3
"""
Debate Engine — 多空辩论决策模式

纯 Groq 实现，无 NVIDIA API 依赖。
让两个 LLM 子代理分别从看多/看空角度分析市场，
再由裁判 LLM 综合双方论点做出最终概率判断。

设计原则:
- 只使用 Groq（无限流、快速）
- 与现有 llm_analyze_probability() 完全解耦，可独立调用
- 输出格式兼容现有 vote_details 结构
- 辩论过程可追溯（保存双方论点+裁判理由）

作者: PolyStrat Team
日期: 2026-07-08
"""

import os
import re
import json
import time
import requests
from datetime import datetime, timezone
from polystrat_logger import log


# === Groq API 配置 ===
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_BULL_MODEL = "llama-3.3-70b-versatile"
GROQ_BEAR_MODEL = "llama-3.3-70b-versatile"
GROQ_JUDGE_MODEL = "llama-3.3-70b-versatile"
GROQ_TIMEOUT = 15  # 秒


def _get_groq_key():
    """获取 Groq API key"""
    return os.environ.get("GROQ_API_KEY", "")


def _call_groq(messages, model=GROQ_JUDGE_MODEL, timeout=GROQ_TIMEOUT):
    """调用 Groq API（通用函数）"""
    api_key = _get_groq_key()
    if not api_key:
        raise ValueError("No GROQ_API_KEY set")
    
    resp = requests.post(
        f"{GROQ_BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": messages,
            "max_tokens": 3000,
            "temperature": 0.3,
        },
        timeout=(3, timeout),
    )
    resp.raise_for_status()
    msg = resp.json()["choices"][0]["message"]
    content = (msg.get("content") or "").strip()
    if not content:
        content = (msg.get("reasoning_content") or "").strip()
    return content


class DebateEngine:
    """多空辩论决策引擎"""
    
    def __init__(self, temperature=0.3):
        self.temperature = temperature
    
    def run_debate(self, market_title, category, current_price, news_context="",
                   context_hint=""):
        """
        运行一场完整的辩论
        
        Args:
            market_title: 市场标题
            category: 市场分类
            current_price: 当前 Yes 价格 (0-1)
            news_context: 相关新闻/背景信息
            context_hint: 分类特定的分析提示
        
        Returns:
            dict: {
                'verdict_probability': float,    # 裁判给出的概率 (0-1)
                'verdict_confidence': float,     # 裁判置信度 (0-1)
                'bull_argument': str,            # 看多方论点摘要
                'bear_argument': str,            # 看空方论点摘要
                'judge_reasoning': str,          # 裁判推理过程
                'key_factors': list,             # 关键影响因素
                'disagreement_intensity': float, # 双方分歧强度 (0-1)
                'debate_log': list,              # 完整辩论日志（调试用）
            }
        """
        debate_log = []
        
        # Step 1: Bull Agent 分析
        bull_result = self._analyze_bull(market_title, category, current_price, 
                                          news_context, context_hint, debate_log)
        
        # Step 2: Bear Agent 分析
        bear_result = self._analyze_bear(market_title, category, current_price,
                                          news_context, context_hint, debate_log)
        
        # Step 3: Judge 综合裁决
        judge_result = self._judge_debate(
            market_title, category, current_price,
            bull_result, bear_result, news_context, context_hint, debate_log
        )
        
        # 计算分歧强度
        bull_prob = bull_result.get('implied_probability', current_price)
        bear_prob = bear_result.get('implied_probability', 1 - current_price)
        disagreement_intensity = abs(bull_prob - bear_prob)
        
        return {
            'verdict_probability': judge_result['probability'],
            'verdict_confidence': judge_result['confidence'],
            'bull_argument': bull_result['summary'],
            'bear_argument': bear_result['summary'],
            'judge_reasoning': judge_result['reasoning'],
            'key_factors': judge_result.get('key_factors', []),
            'disagreement_intensity': disagreement_intensity,
            'debate_log': debate_log,
            # 附加字段供测试脚本使用
            'bull_implied_probability': bull_prob,
            'bear_implied_probability': bear_prob,
        }
    
    def _analyze_bull(self, market_title, category, current_price,
                      news_context, context_hint, debate_log):
        """Bull Agent: 分析为什么事件会成真"""
        debate_log.append({
            'step': 'bull_analysis',
            'timestamp': datetime.now(timezone.utc).isoformat(),
        })
        
        prompt = f"""你是一个专业的预测市场分析师，扮演【看多方】角色。

你的任务：分析以下市场事件发生的可能性，提供看多的论据和概率估计。

市场问题: {market_title}
市场分类: {category}
当前市场价: Yes = {current_price * 100:.0f}¢ (即市场认为有 {current_price * 100:.0f}% 的概率)
{f'分析提示: {context_hint}' if context_hint else ''}

相关新闻/背景信息:
{news_context if news_context else "暂无相关新闻"}

请按以下格式输出：

【核心论点】
列出3-5个支持事件会发生的关键论据，每个论据一句话。

【概率估计】
给出你认为事件发生的概率，格式: PROB:XX (XX为0-100的整数)

【信心水平】
HIGH / MEDIUM / LOW（基于证据充分程度）

【关键不确定性】
列出1-2个可能导致你判断失误的风险因素

要求：
- 论据要具体，引用新闻中的事实
- 概率估计要有理有据
- 即使市场定价已经很高，也要诚实评估
- 只输出上述格式内容，不要额外解释"""

        try:
            content = _call_groq(
                [{"role": "user", "content": prompt}],
                model=GROQ_BULL_MODEL,
            )
            
            # 解析概率
            prob_match = re.search(r'PROB:(\d+)', content)
            probability = int(prob_match.group(1)) if prob_match else 65
            
            # 解析信心
            confidence = 'MEDIUM'
            if 'HIGH' in content.split('信心水平')[-1][:20]:
                confidence = 'HIGH'
            elif 'LOW' in content.split('信心水平')[-1][:20]:
                confidence = 'LOW'
            
            result = {
                'role': 'bull',
                'full_text': content,
                'summary': content[:500] + "..." if len(content) > 500 else content,
                'implied_probability': probability / 100.0,
                'confidence': confidence,
                'success': True,
            }
            
            debate_log[-1].update({
                'probability': probability,
                'confidence': confidence,
                'success': True,
            })
            
            return result
            
        except Exception as e:
            log.error(f"Bull Agent 失败: {e}")
            debate_log[-1].update({'success': False, 'error': str(e)})
            return {
                'role': 'bull',
                'full_text': '',
                'summary': f'Bull分析失败: {e}',
                'implied_probability': current_price,
                'confidence': 'LOW',
                'success': False,
            }
    
    def _analyze_bear(self, market_title, category, current_price,
                      news_context, context_hint, debate_log):
        """Bear Agent: 分析为什么事件不会成真"""
        debate_log.append({
            'step': 'bear_analysis',
            'timestamp': datetime.now(timezone.utc).isoformat(),
        })
        
        prompt = f"""你是一个专业的预测市场分析师，扮演【看空方】角色。

你的任务：分析以下市场事件不发生的可能性，提供看空的论据和概率估计。

市场问题: {market_title}
市场分类: {category}
当前市场价: Yes = {current_price * 100:.0f}¢ (即市场认为有 {current_price * 100:.0f}% 的概率)
{f'分析提示: {context_hint}' if context_hint else ''}

相关新闻/背景信息:
{news_context if news_context else "暂无相关新闻"}

请按以下格式输出：

【核心论点】
列出3-5个支持事件不会发生的关键论据，每个论据一句话。

【概率估计】
给出你认为事件【不会】发生的概率，格式: PROBA:XX (XX为0-100的整数，指NOT发生的概率)

【信心水平】
HIGH / MEDIUM / LOW（基于证据充分程度）

【关键不确定性】
列出1-2个可能导致你判断失误的风险因素

要求：
- 论据要具体，引用新闻中的事实
- 概率估计要有理有据
- 即使市场定价很低，也要诚实评估
- 只输出上述格式内容，不要额外解释"""

        try:
            content = _call_groq(
                [{"role": "user", "content": prompt}],
                model=GROQ_BEAR_MODEL,
            )
            
            # 解析概率（注意：这里是NOT发生的概率）
            prob_match = re.search(r'PROBA:(\d+)', content)
            proba_not = int(prob_match.group(1)) if prob_match else 60
            implied_yes = (100 - proba_not) / 100.0
            
            # 解析信心
            confidence = 'MEDIUM'
            if 'HIGH' in content.split('信心水平')[-1][:20]:
                confidence = 'HIGH'
            elif 'LOW' in content.split('信心水平')[-1][:20]:
                confidence = 'LOW'
            
            result = {
                'role': 'bear',
                'full_text': content,
                'summary': content[:500] + "..." if len(content) > 500 else content,
                'implied_probability': implied_yes,
                'confidence': confidence,
                'success': True,
            }
            
            debate_log[-1].update({
                'implied_yes_probability': round(implied_yes, 3),
                'confidence': confidence,
                'success': True,
            })
            
            return result
            
        except Exception as e:
            log.error(f"Bear Agent 失败: {e}")
            debate_log[-1].update({'success': False, 'error': str(e)})
            return {
                'role': 'bear',
                'full_text': '',
                'summary': f'Bear分析失败: {e}',
                'implied_probability': 1 - current_price,
                'confidence': 'LOW',
                'success': False,
            }
    
    def _judge_debate(self, market_title, category, current_price,
                      bull_result, bear_result, news_context, context_hint, debate_log):
        """Judge Agent: 综合双方论点做出裁决"""
        debate_log.append({
            'step': 'judge_decision',
            'timestamp': datetime.now(timezone.utc).isoformat(),
        })
        
        bull_summary = bull_result.get('summary', '无')
        bear_summary = bear_result.get('summary', '无')
        bull_prob = bull_result.get('implied_probability', current_price)
        bear_prob = bear_result.get('implied_probability', 1 - current_price)
        
        prompt = f"""你是一个资深的预测市场裁判官。你需要综合评估多空双方的论点，做出最终的概率判断。

市场问题: {market_title}
市场分类: {category}
当前市场价: Yes = {current_price * 100:.0f}¢

【看多方论点】
{bull_summary}
看多方隐含概率: Yes = {bull_prob * 100:.0f}%

【看空方论点】
{bear_summary}
看空方隐含概率: Yes = {bear_prob * 100:.0f}%

请综合评估后输出：

【裁决分析】
简要分析双方论点的强弱，指出你认为最有说服力的论据和可能被忽视的因素。

【最终概率】
给出你认为事件发生的概率，格式: VERDICT:XX (XX为0-100的整数)

【信心水平】
HIGH / MEDIUM / LOW

【关键因素】
列出影响你判断的前3个关键因素，用逗号分隔

要求：
- 客观公正，不要被任何一方立场左右
- 结合当前市场价格，判断哪一方更有优势
- 如果双方都有合理之处，给出一个折中的概率
- 只输出上述格式内容"""

        try:
            content = _call_groq(
                [{"role": "user", "content": prompt}],
                model=GROQ_JUDGE_MODEL,
            )
            
            # 解析概率
            prob_match = re.search(r'VERDICT:(\d+)', content)
            probability = prob_match.group(1) if prob_match else None
            probability = int(probability) / 100.0 if probability else 0.5
            
            # 解析信心
            confidence = 'MEDIUM'
            if 'HIGH' in content.split('信心水平')[-1][:20]:
                confidence = 'HIGH'
            elif 'LOW' in content.split('信心水平')[-1][:20]:
                confidence = 'LOW'
            
            # 解析关键因素
            factors_section = content.split('【关键因素】')[-1] if '【关键因素】' in content else ''
            key_factors = [f.strip() for f in factors_section.split(',') if f.strip()]
            
            result = {
                'role': 'judge',
                'reasoning': content,
                'probability': probability,
                'confidence': confidence,
                'key_factors': key_factors[:3],
                'success': True,
            }
            
            debate_log[-1].update({
                'verdict_probability': probability,
                'confidence': confidence,
                'key_factors': key_factors[:3],
                'success': True,
            })
            
            return result
            
        except Exception as e:
            log.error(f"Judge Agent 失败: {e}")
            debate_log[-1].update({'success': False, 'error': str(e)})
            return self._judge_fallback(bull_result, bear_result, current_price, debate_log)
    
    def _judge_fallback(self, bull_result, bear_result, current_price, debate_log):
        """Judge 失败时的 fallback：使用 Bull/Bear 加权平均"""
        debate_log.append({
            'step': 'judge_fallback',
            'timestamp': datetime.now(timezone.utc).isoformat(),
        })
        
        bull_prob = bull_result.get('implied_probability', current_price)
        bear_prob = bear_result.get('implied_probability', 1 - current_price)
        bull_confidence = bull_result.get('confidence', 'MEDIUM')
        bear_confidence = bear_result.get('confidence', 'MEDIUM')
        
        # 权重映射
        conf_weight = {'HIGH': 1.0, 'MEDIUM': 0.6, 'LOW': 0.3}
        bull_w = conf_weight.get(bull_confidence, 0.6)
        bear_w = conf_weight.get(bear_confidence, 0.6)
        
        # 加权平均
        total_w = bull_w + bear_w
        if total_w > 0:
            verdict_prob = (bull_prob * bull_w + bear_prob * bear_w) / total_w
        else:
            verdict_prob = current_price
        
        # 确保在合理范围内
        verdict_prob = max(0.01, min(0.99, verdict_prob))
        
        result = {
            'role': 'judge',
            'reasoning': f'Judge 不可用，使用 Bull({bull_prob*100:.0f}%/{bull_confidence}) + Bear({bear_prob*100:.0f}%/{bear_confidence}) 加权平均',
            'probability': verdict_prob,
            'confidence': 'MEDIUM',
            'key_factors': ['Bull/Bear 加权平均 (Judge fallback)'],
            'success': True,
        }
        
        debate_log[-1].update({
            'verdict_probability': verdict_prob,
            'confidence': 'MEDIUM',
            'method': 'weighted_average_fallback',
            'bull_prob': bull_prob,
            'bear_prob': bear_prob,
            'success': True,
        })
        
        return result


def create_voting_system(model_weights=None):
    """
    创建 Debate 投票系统（兼容现有接口）
    """
    return DebateEngine()


# 便捷函数
def run_debate_for_market(market_title, category, current_price, news_context="",
                          context_hint=""):
    """快捷函数：为单个市场运行辩论"""
    engine = DebateEngine()
    return engine.run_debate(
        market_title=market_title,
        category=category,
        current_price=current_price,
        news_context=news_context,
        context_hint=context_hint,
    )
