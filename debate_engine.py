#!/usr/bin/env python3
"""
Debate Engine v2 — 多空辩论决策模式（多平台版）

核心设计:
- Bull/Bear/Judge 分别使用不同平台API，避免单平台限流
- 每个角色有 fallback 链：主力 → 备选1 → 备选2
- 自动 429 重试（exponential backoff）
- 与现有 llm_analyze_probability() 完全解耦，可独立调用
- 输出格式兼容现有 vote_details 结构

API分配策略（避免同平台）:
- Bull:  Groq Llama 3.3 70B → GitHub GPT-4o-mini → AGNES agnes-2.0-flash
- Bear:  GitHub GPT-4o-mini → AGNES agnes-2.0-flash → Groq Llama 3.3 70B
- Judge: AGNES agnes-2.0-flash → Groq Llama 3.3 70B → GitHub GPT-4o-mini

作者: PolyStrat Team
日期: 2026-07-08
版本: v2.0 (多平台fallback)
"""

import os
import re
import json
import time
import requests
from datetime import datetime, timezone
from polystrat_logger import log


# === 多平台 Provider 配置 ===
# 按速度排序: Groq 0.2s > AGNES 0.6s > GitHub 1.7s > NVIDIA 5.4s > OpenRouter 6.4s > GLM 17s

def _load_env():
    """加载 .env 文件中的 API keys"""
    env_path = os.path.expanduser("~/.hermes/.env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    if not os.environ.get(k):
                        os.environ[k] = v

_load_env()

PROVIDERS = {
    "groq": {
        "name": "Groq Llama 3.3 70B",
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
        "key_env": "GROQ_API_KEY",
        "timeout": (5, 30),
        "max_tokens": 2000,
        "rpm_limit": 30,  # Groq free tier ~30 RPM
    },
    "github": {
        "name": "GitHub GPT-4o-mini",
        "base_url": "https://models.inference.ai.azure.com",
        "model": "gpt-4o-mini",
        "key_env": "GITHUB_API_KEY",
        "timeout": (5, 30),
        "max_tokens": 2000,
        "rpm_limit": 60,
    },
    "agnes": {
        "name": "AGNES agnes-2.0-flash",
        "base_url": "https://apihub.agnes-ai.com/v1",
        "model": "agnes-2.0-flash",
        "key_env": "AGNES_API_KEY",
        "timeout": (5, 60),
        "max_tokens": 2000,
        "rpm_limit": 60,
        "note": "agnes-2.0-flash 内置thinking，Bull/Bear角色需10-35s，Judge角色仅1-2s",
    },
    "gemini": {
        "name": "Gemini 3.1 Pro",
        "base_url": "http://localhost:3404/v1",
        "model": "gemini-3.1-pro-low",
        "key_env": "GEMINI_DUMMY",
        "timeout": (5, 30),
        "max_tokens": 2000,
        "rpm_limit": 60,
    },
    "nvidia": {
        "name": "NVIDIA DeepSeek V4",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "model": "deepseek-ai/deepseek-v4-flash",
        "key_env": "NVIDIA_API_KEY_2",
        "timeout": (5, 30),
        "max_tokens": 2000,
        "rpm_limit": 40,
    },
    "openrouter": {
        "name": "OpenRouter Llama 3.3 70B",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "meta-llama/llama-3.3-70b-instruct",
        "key_env": "OPENROUTER_API_KEY",
        "timeout": (5, 30),
        "max_tokens": 2000,
        "rpm_limit": 20,
    },
    "glm": {
        "name": "GLM-5.1 (z.ai)",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-5.1",
        "key_env": "GLM_API_KEY",
        "timeout": (5, 45),
        "max_tokens": 2000,
        "rpm_limit": 60,
    },
}

# === 辩论角色 → 平台分配 ===
# 🔧 引入最新架构的 Gemini 3.1 Pro 模型，以及将 NVIDIA 更正为 DeepSeek V4
#   github=GPT族 | nvidia=DeepSeek族 | groq=Llama族 | gemini=Gemini族
#   - Bull: Gemini(3.1Pro) → GitHub → Groq → NVIDIA → AGNES → OpenRouter → GLM
#   - Bear: NVIDIA(DeepSeek) → Gemini → GitHub → Groq → AGNES → OpenRouter → GLM
#   - Judge: Groq(Llama) → Gemini → GitHub → NVIDIA → AGNES → OpenRouter → GLM
ROLE_PROVIDERS = {
    "bull": ["gemini", "github", "groq", "nvidia", "agnes", "openrouter", "glm"],
    "bear": ["nvidia", "gemini", "github", "groq", "agnes", "openrouter", "glm"],
    "judge": ["groq", "gemini", "github", "nvidia", "agnes", "openrouter", "glm"],
}

# === 429 ���试配置 ===
MAX_RETRIES = 1           # 每个provider最多重试1次（快速fallback比等待更好）
RETRY_BASE_DELAY = 2      # 基础等待2秒
RETRY_MAX_DELAY = 8       # 最大等待8秒


def _get_api_key(provider_id):
    """获取指定provider的API key"""
    p = PROVIDERS.get(provider_id)
    if not p:
        return None
    if provider_id == "gemini":
        return "proxy-handled"  # 走本地端口，不验key
    return os.environ.get(p["key_env"], "")


def _call_llm(messages, provider_id, temperature=0.3, max_retries=MAX_RETRIES):
    """
    调用指定平台的 LLM API，带 429 重试
    
    Args:
        messages: OpenAI 格式的消息列表
        provider_id: provider ID (e.g., "groq", "github")
        temperature: 生成温度
        max_retries: 最大重试次数
    
    Returns:
        str: LLM 返回的文本内容
    
    Raises:
        ValueError: 无 API key
        requests.HTTPError: 非429错误或重试耗尽
    """
    p = PROVIDERS.get(provider_id)
    if not p:
        raise ValueError(f"Unknown provider: {provider_id}")
    
    api_key = _get_api_key(provider_id)
    if not api_key:
        raise ValueError(f"No API key for {provider_id} ({p['key_env']})")
    
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(
                f"{p['base_url']}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": p["model"],
                    "messages": messages,
                    "max_tokens": p["max_tokens"],
                    "temperature": temperature,
                },
                timeout=p["timeout"],
            )
            
            if resp.status_code == 429:
                # 429限流 — 只重试1次，快速fallback更好
                if attempt < max_retries:
                    delay = min(RETRY_BASE_DELAY * (2 ** attempt), RETRY_MAX_DELAY)
                    log.warning(f"{p['name']} 429限流, 等待{delay:.0f}s 后重试")
                    time.sleep(delay)
                    continue
                else:
                    # 重试耗尽，直接抛出让fallback链接管
                    log.warning(f"{p['name']} 429限流，重试耗尽，fallback")
                    resp.raise_for_status()
            
            # 非429的HTTP错误，直接抛出（不需要重试）
            resp.raise_for_status()
            
            data = resp.json()
            msg = data["choices"][0]["message"]
            content = (msg.get("content") or "").strip()
            if not content:
                content = (msg.get("reasoning_content") or "").strip()
            return content
            
        except requests.HTTPError as e:
            last_error = e
            status = getattr(resp, 'status_code', 0)
            if status == 429 and attempt < max_retries:
                continue
            raise
        except (requests.Timeout, requests.ConnectionError) as e:
            last_error = e
            # 超时/连接错误只重试1次
            if attempt < max_retries:
                log.warning(f"{p['name']} 超时，重试 {attempt+1}/{max_retries}")
                time.sleep(1)
                continue
            raise
        except Exception as e:
            last_error = e
            raise
    
    raise last_error or RuntimeError("Unexpected retry loop exit")


def _call_with_fallback(messages, role, temperature=0.3):
    """
    按角色 fallback 链调用 LLM
    
    Args:
        messages: 消息列表
        role: "bull", "bear", 或 "judge"
        temperature: 生成温度
    
    Returns:
        tuple: (content, provider_id, error)
    """
    provider_chain = ROLE_PROVIDERS.get(role, ["groq", "github", "agnes"])
    errors = []
    
    for pid in provider_chain:
        api_key = _get_api_key(pid)
        if not api_key:
            errors.append(f"{pid}: no key")
            continue
        
        try:
            content = _call_llm(messages, pid, temperature)
            return content, pid, None
        except Exception as e:
            p = PROVIDERS[pid]
            err_msg = f"{p['name']}: {type(e).__name__}"
            log.warning(f"Debate {role} fallback: {err_msg}")
            errors.append(err_msg)
            continue
    
    # 所有 provider 都失败
    return None, None, "; ".join(errors)


class DebateEngine:
    """多空辩论决策引擎 v2（多平台版）"""
    
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
                'verdict_probability': float,
                'verdict_confidence': float/str,
                'bull_argument': str,
                'bear_argument': str,
                'judge_reasoning': str,
                'key_factors': list,
                'disagreement_intensity': float,
                'debate_log': list,
                'bull_implied_probability': float,
                'bear_implied_probability': float,
                'providers_used': dict,  # 新增: 记录用了哪些平台
            }
        """
        debate_log = []
        providers_used = {}
        
        # Step 1: Bull Agent 分析
        bull_result = self._analyze_bull(market_title, category, current_price,
                                          news_context, context_hint, debate_log)
        providers_used["bull"] = bull_result.get("provider", "unknown")
        
        # Step 2: Bear Agent 分析
        bear_result = self._analyze_bear(market_title, category, current_price,
                                          news_context, context_hint, debate_log)
        providers_used["bear"] = bear_result.get("provider", "unknown")
        
        # Step 3: Judge 综合裁决
        judge_result = self._judge_debate(
            market_title, category, current_price,
            bull_result, bear_result, news_context, context_hint, debate_log
        )
        providers_used["judge"] = judge_result.get("provider", "unknown")
        
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
            'bull_implied_probability': bull_prob,
            'bear_implied_probability': bear_prob,
            'providers_used': providers_used,
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

        content, provider_id, error = _call_with_fallback(
            [{"role": "user", "content": prompt}], "bull", self.temperature
        )
        
        if error:
            log.error(f"Bull Agent 全部失败: {error}")
            debate_log[-1].update({'success': False, 'error': error})
            return {
                'role': 'bull',
                'full_text': '',
                'summary': f'Bull分析失败: {error}',
                'implied_probability': current_price,
                'confidence': 'LOW',
                'success': False,
                'provider': 'none',
            }
        
        # 解析概率
        prob_match = re.search(r'PROB:(\d+)', content)
        probability = int(prob_match.group(1)) if prob_match else 65
        
        # 解析信心
        confidence = _parse_confidence(content)
        
        result = {
            'role': 'bull',
            'full_text': content,
            'summary': content[:500] + "..." if len(content) > 500 else content,
            'implied_probability': probability / 100.0,
            'confidence': confidence,
            'success': True,
            'provider': provider_id,
        }
        
        debate_log[-1].update({
            'probability': probability,
            'confidence': confidence,
            'success': True,
            'provider': provider_id,
        })
        
        return result
    
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

        content, provider_id, error = _call_with_fallback(
            [{"role": "user", "content": prompt}], "bear", self.temperature
        )
        
        if error:
            log.error(f"Bear Agent 全部失败: {error}")
            debate_log[-1].update({'success': False, 'error': error})
            return {
                'role': 'bear',
                'full_text': '',
                'summary': f'Bear分析失败: {error}',
                'implied_probability': 1 - current_price,
                'confidence': 'LOW',
                'success': False,
                'provider': 'none',
            }
        
        # 解析概率（注意：这里是NOT发生的概率）
        prob_match = re.search(r'PROBA:(\d+)', content)
        proba_not = int(prob_match.group(1)) if prob_match else 60
        implied_yes = (100 - proba_not) / 100.0
        
        # 解析信心
        confidence = _parse_confidence(content)
        
        result = {
            'role': 'bear',
            'full_text': content,
            'summary': content[:500] + "..." if len(content) > 500 else content,
            'implied_probability': implied_yes,
            'confidence': confidence,
            'success': True,
            'provider': provider_id,
        }
        
        debate_log[-1].update({
            'implied_yes_probability': round(implied_yes, 3),
            'confidence': confidence,
            'success': True,
            'provider': provider_id,
        })
        
        return result
    
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
        
        prompt = f"""你是一个资深的预测市场裁判官。你需要综合评估多空双方的论点，基于事实独立做出最终的概率判断。

市场问题: {market_title}
市场分类: {category}

【看多方论点】
{bull_summary}

【看空方论点】
{bear_summary}

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
- 🔧 基于事实和论点独立判断事件发生的真实概率，不要参考任何市场价格信息（防止锚定偏差）
- 如果双方都有合理之处，给出一个折中的概率
- 只输出上述格式内容"""

        content, provider_id, error = _call_with_fallback(
            [{"role": "user", "content": prompt}], "judge", self.temperature
        )
        
        if error:
            log.error(f"Judge Agent 全部失败: {error}")
            return self._judge_fallback(bull_result, bear_result, current_price, debate_log)
        
        # 解析概率
        prob_match = re.search(r'VERDICT:(\d+)', content)
        probability = prob_match.group(1) if prob_match else None
        probability = int(probability) / 100.0 if probability else 0.5
        
        # 解析信心
        confidence = _parse_confidence(content)
        
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
            'provider': provider_id,
        }
        
        debate_log[-1].update({
            'verdict_probability': probability,
            'confidence': confidence,
            'key_factors': key_factors[:3],
            'success': True,
            'provider': provider_id,
        })
        
        return result
    
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
            'provider': 'fallback',
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


def _parse_confidence(text):
    """从文本中解析信心水平（兼容中英文/大小写）"""
    # 匹配 信心水平/信心度/Confidence 标签后的等级（大小写不敏感）
    m = re.search(r'(?:信心水平|信心度|Confidence)[:：\s]*\s*(HIGH|MEDIUM|LOW)', text, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    # 兜底：全文最后出现的等级（LLM 可能用小写或不同格式）
    levels = re.findall(r'\b(HIGH|MEDIUM|LOW)\b', text, re.IGNORECASE)
    if levels:
        return levels[-1].upper()
    return 'MEDIUM'


def create_voting_system(model_weights=None):
    """创建 Debate 投票系统（兼容现有接口）"""
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
