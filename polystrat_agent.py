#!/usr/bin/env python3
"""
简易版 PolyStrat — AI 自主交易 Agent v2
功能：
1. 扫描 Polymarket 活跃市场
2. 搜索相关新闻（GNews + Currents + RSS）
3. 情感分析（LLM + 关键词）
4. LLM 分析概率（4模型投票）
5. 风险管理（仓位/止损/分散）
6. 自动下单（DRY_RUN 模式）
7. 输出结果（Hermes Cron 推送）
"""

import os
import sys
import json
import re
import time
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 加载 .env 文件（Hermes profile 环境变量）
from dotenv import load_dotenv
load_dotenv(Path.home() / ".hermes" / "profiles" / "life" / ".env")
load_dotenv()  # 也加载项目目录的 .env（如果有）

# 导入自定义模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from news_search import search_news_for_market
from sentiment_analysis import analyze_news_sentiment, analyze_sentiment_simple
from risk_management import should_trade, calculate_position_size, get_risk_report, set_trade_log_path as set_risk_log_path
from onchain_monitor import get_onchain_signal
from adaptive_weights import calculate_adaptive_weights, load_trade_history, set_trade_log_path as set_adaptive_log_path
from ml_optimizer import get_ml_signal
from multi_platform import get_multiplatform_signal
from smart_keywords import get_search_queries
from advanced_voting import create_voting_system
from dynamic_optimizer import (
    calculate_llm_model_weights,
    get_dynamic_price_thresholds,
    get_dynamic_dedup_hours,
    format_optimization_report,
)
from polystrat_logger import log, log_error, log_api_call, log_performance
from safe_file_ops import atomic_write_json, atomic_read_json, append_to_json_array
from circuit_breaker import check_breaker, record_trade_result, get_breaker_status
from trade_limits import (
    check_trade_allowed,
    record_trade,
    get_limits_status,
    LIMITS_CONFIG,
)
from settlement_tracker import (
    update_settled_trades,
    format_settlement_report as fmt_settlement_report,
)
from settlement_tracker import set_trade_log_path as set_settlement_log_path
from market_microstructure import calculate_microstructure_signal, format_microstructure_report

# === 配置 ===
# LLM Ensemble 链：双主力(reasoning) + 双辅助(快速验证)
# Primary: MiniMax M2.7 + Nemotron 3 Super (reasoning模型，输出完整推理链)
# Secondary: Llama 3.3 70B + GLM-5.1 (快速方向验证)
LLM_PROVIDERS = [
    {
        "name": "MiniMax M2.7",
        "api_key": os.environ.get("NVIDIA_API_KEY_2", ""),
        "base_url": "https://integrate.api.nvidia.com/v1",
        "model": "minimaxai/minimax-m2.7",
        "temperature": 0.5,
        "priority": 1,
        "role": "primary",
    },
    {
        "name": "Nemotron 3 Super",
        "api_key": os.environ.get("NVIDIA_API_KEY", ""),
        "base_url": "https://integrate.api.nvidia.com/v1",
        "model": "nvidia/nemotron-3-super-120b-a12b",
        "temperature": 0.5,
        "priority": 2,
        "role": "primary",
    },
    {
        "name": "Llama 3.3 70B",
        "api_key": os.environ.get("NVIDIA_API_KEY", ""),
        "base_url": "https://integrate.api.nvidia.com/v1",
        "model": "meta/llama-3.3-70b-instruct",
        "temperature": 0.3,
        "priority": 3,
        "role": "secondary",
    },
    {
        "name": "GLM-5.1",
        "api_key": os.environ.get("GLM_API_KEY", ""),
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-5.1",
        "temperature": 0.4,
        "priority": 4,
        "role": "secondary",
    },
]

# 最少有效投票数（至少2票才认为分析有效）
MIN_VALID_VOTES = 2

# 按优先级排序
LLM_PROVIDERS.sort(key=lambda x: x.get("priority", 99))

# Polymarket
POLYMARKET_FUNDER = os.environ.get("POLYMARKET_FUNDER_ADDRESS", "")
POLYMARKET_KEY = os.environ.get("POLYMARKET_PRIVATE_KEY", "")
SIGNATURE_TYPE = int(os.environ.get("SIGNATURE_TYPE", "1"))
DRY_RUN = True  # 先跑测试版
BET_AMOUNT = 2.0
EDGE_THRESHOLD = 0.04  # LLM 概率与市场价差 >4% 才下单（优化后）
MAX_TRADES_PER_RUN = 3
DEDUP_HOURS = 24  # 24小时内不重复交易同一市场
MIN_LIQUIDITY = 5000  # 最小流动性 $5000

# 甜蜜点市场配置（聚焦高胜率区间）
SWEET_SPOT_CONFIG = {
    "min_price": 0.10,      # 最低 10¢（避免极端事件）
    "max_price": 0.30,      # 最高 30¢（甜蜜点上限）
    "min_liquidity": 20000, # 最低流动性 $20k（确保可执行性）
    "min_disagreement": 15, # 最低投票分歧 15%（市场有争议）
    "max_disagreement": 40, # 最高投票分歧 40%（避免噪声）
    "min_confidence": 0.6,  # 最低投票置信度 60%
    "preferred_categories": ["Politics", "Sports", "Crypto", "Economics"],
}

# 启用甜蜜点模式（True=聚焦甜蜜点，False=使用原始阈值）
SWEET_SPOT_MODE = True

# 市场微观结构信号配置
MICROSTRUCTURE_CONFIG = {
    "enabled": True,           # 启用微观结构信号
    "weight": 0.10,            # 权重 10%
    "min_confidence": 0.3,     # 最低置信度
    "prefer_tight_spread": True,  # 优先选择价差小的市场
}

# 权重配置（优化后：降低LLM共线性风险，提高ML/链上权重）
# 信号源: LLM, 情感, 链上, ML, 微观结构
SIGNAL_WEIGHTS = {
    "llm": 0.20,  # LLM 分析权重（降低，为微观结构腾出空间）
    "sentiment": 0.15,  # 新闻情感权重
    "onchain": 0.25,  # 链上信号权重
    "ml": 0.25,  # ML 信号权重
    "microstructure": 0.15,  # 市场微观结构信号权重
}

# 验证权重归一化
assert abs(sum(SIGNAL_WEIGHTS.values()) - 1.0) < 1e-6, "权重总和必须为1.0"

# 兼容旧代码
LLM_WEIGHT = SIGNAL_WEIGHTS["llm"]
NEWS_WEIGHT = SIGNAL_WEIGHTS["sentiment"]

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"

# 日志目录
LOG_DIR = Path("/root/.hermes/profiles/life/home/.hermes/polymarket_bot/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)
TRADE_LOG = (
    LOG_DIR / "polystrat_trades_dryrun.json"
    if DRY_RUN
    else LOG_DIR / "polystrat_trades.json"
)

# 同步交易日志路径到子模块（DRY_RUN/LIVE 一致性）
set_adaptive_log_path(TRADE_LOG)
set_settlement_log_path(TRADE_LOG)
set_risk_log_path(TRADE_LOG)


def fetch_active_markets(limit=50):
    """从 Gamma API 获取活跃市场，按流动性排序"""
    try:
        resp = requests.get(
            f"{GAMMA_API}/markets",
            params={
                "closed": "false",
                "limit": limit,
                "active": "true",
                "order": "liquidityNum",
                "ascending": "false",
            },
            timeout=30,
        )
        resp.raise_for_status()
        markets = resp.json()
        # 过滤：必须有价格和流动性
        valid = []
        for m in markets:
            title = m.get("question", "")
            outcomes = m.get("outcomes", "")
            prices = m.get("outcomePrices", "")
            liquidity = float(m.get("liquidityNum", 0))
            cid = m.get("conditionId", "")
            tokens = m.get("clobTokenIds", "")
            slug = m.get("slug", "")
            end_date = m.get("endDate", "")

            if not title or not prices:
                continue

            # 解析价格
            try:
                if isinstance(prices, str):
                    price_list = json.loads(prices)
                else:
                    price_list = prices
                if len(price_list) < 1:
                    continue
                yes_price = float(price_list[0])
            except Exception:
                continue

            # 跳过极端价格（>97¢ 或 <3¢）- 扩大范围
            if yes_price > 0.97 or yes_price < 0.03:
                continue

            # 解析 token IDs
            try:
                if isinstance(tokens, str):
                    token_list = json.loads(tokens)
                else:
                    token_list = tokens
            except Exception:
                token_list = []

            # 解析 outcomes
            try:
                if isinstance(outcomes, str):
                    outcome_list = json.loads(outcomes)
                else:
                    outcome_list = outcomes
            except Exception:
                outcome_list = ["Yes", "No"]

            # 检测市场分类（扩展分类）
            title_lower = title.lower()
            if any(
                x in title_lower
                for x in [
                    "bitcoin",
                    "btc",
                    "crypto",
                    "eth",
                    "solana",
                    "blockchain",
                    "defi",
                ]
            ):
                category = "Crypto"
            elif any(
                x in title_lower
                for x in [
                    "trump",
                    "biden",
                    "election",
                    "president",
                    "democrat",
                    "republican",
                    "newsom",
                    "aoc",
                    "congress",
                    "senate",
                ]
            ):
                category = "Politics"
            elif any(
                x in title_lower
                for x in [
                    "world cup",
                    "fifa",
                    "soccer",
                    "football",
                    "nba",
                    "nfl",
                    "mlb",
                    "tennis",
                    "golf",
                    "boxing",
                ]
            ):
                category = "Sports"
            elif any(
                x in title_lower
                for x in [
                    "gta",
                    "album",
                    "movie",
                    "oscar",
                    "grammy",
                    "rihanna",
                    "carti",
                    "taylor",
                    "beyonce",
                    "kanye",
                ]
            ):
                category = "Entertainment"
            elif any(
                x in title_lower
                for x in [
                    "war",
                    "china",
                    "russia",
                    "iran",
                    "ukraine",
                    "taiwan",
                    "israel",
                    "nato",
                    "military",
                ]
            ):
                category = "Geopolitics"
            elif any(
                x in title_lower
                for x in [
                    "fed",
                    "interest",
                    "inflation",
                    "gdp",
                    "stock",
                    "recession",
                    "economy",
                    "unemployment",
                ]
            ):
                category = "Economics"
            elif any(
                x in title_lower
                for x in [
                    "ai",
                    "artificial intelligence",
                    "chatgpt",
                    "openai",
                    "google",
                    "apple",
                    "tech",
                ]
            ):
                category = "Technology"
            elif any(
                x in title_lower
                for x in [
                    "climate",
                    "weather",
                    "hurricane",
                    "earthquake",
                    "flood",
                    "temperature",
                ]
            ):
                category = "Weather"
            elif any(
                x in title_lower
                for x in ["space", "nasa", "spacex", "mars", "moon", "rocket"]
            ):
                category = "Science"
            elif any(
                x in title_lower
                for x in [
                    "health",
                    "covid",
                    "vaccine",
                    "disease",
                    "pandemic",
                    "hospital",
                ]
            ):
                category = "Health"
            else:
                category = "Other"

            valid.append(
                {
                    "title": title,
                    "yes_price": yes_price,
                    "no_price": 1.0 - yes_price,
                    "liquidity": liquidity,
                    "condition_id": cid,
                    "yes_token": token_list[0] if len(token_list) > 0 else "",
                    "no_token": token_list[1] if len(token_list) > 1 else "",
                    "slug": slug,
                    "outcomes": outcome_list,
                    "end_date": end_date,
                    "category": category,
                }
            )
        return valid
    except Exception as e:
        print(f"❌ 获取市场失败: {e}")
        return []


def search_news(query, max_results=3):
    """搜索相关新闻（使用 DuckDuckGo Lite）"""
    try:
        # 使用 DuckDuckGo Lite 版本
        resp = requests.get(
            "https://lite.duckduckgo.com/lite/",
            params={"q": query},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        # 简单提取搜索结果摘要
        text = resp.text
        # 提取结果片段
        results = []
        # 从 HTML 中提取文本内容
        clean = re.sub(r"<[^>]+>", " ", text)
        clean = re.sub(r"\s+", " ", clean)
        # 取前 2000 字符作为上下文
        context = clean[:2000]
        return context
    except Exception:
        return ""


def llm_analyze_probability(
    market_title, news_context, current_yes_price, category="Other"
):
    """使用多 LLM 分析市场概率，使用高级投票系统（加权+异常值过滤）"""
    if not LLM_PROVIDERS:
        return None, [], {}

    # 根据分类添加上下文
    category_context = {
        "Crypto": "这是一个加密货币市场。关注技术发展、监管消息、市场情绪。",
        "Politics": "这是一个政治市场。关注民调、政策变化、选举动态。",
        "Sports": "这是一个体育市场。关注球队表现、伤病、历史数据。",
        "Entertainment": "这是一个娱乐市场。关注行业动态、艺人活动、历史模式。",
        "Geopolitics": "这是一个地缘政治市场。关注国际关系、冲突动态、外交进展。",
        "Economics": "这是一个经济市场。关注经济数据、央行政策、市场预期。",
    }

    context_hint = category_context.get(category, "请综合分析相关信息。")

    prompt = f"""你是一个预测市场分析师。根据以下信息，判断这个预测市场事件发生的概率。

市场问题: {market_title}
市场分类: {category}
当前市场价: Yes = {current_yes_price * 100:.0f}¢ (即市场认为有 {current_yes_price * 100:.0f}% 的概率)

分析提示: {context_hint}

相关新闻/背景信息:
{news_context if news_context else "暂无相关新闻"}

请分析并给出你认为的实际概率（0-100之间的整数）。
只输出一个数字，不要解释。例如: 65"""

    # 遍历所有 provider，收集概率
    predictions_dict = {}
    model_results = []
    for provider in LLM_PROVIDERS:
        api_key = provider["api_key"]
        if not api_key:
            continue

        for attempt in range(2):
            try:
                resp = requests.post(
                    f"{provider['base_url']}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": provider["model"],
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 1000,
                        "temperature": provider.get("temperature", 0.3),
                    },
                    timeout=45,
                )
                if resp.status_code == 429:
                    break  # 限流，跳到下一个 provider
                resp.raise_for_status()
                msg = resp.json()["choices"][0]["message"]
                # 兼容推理模型：content 可能在 reasoning_content 中
                content = (msg.get("content") or "").strip()
                if not content:
                    content = (msg.get("reasoning_content") or "").strip()
                match = re.search(r"(\d+)", content)
                if match:
                    prob = int(match.group(1))
                    if 0 <= prob <= 100:
                        predictions_dict[provider["name"]] = prob
                        model_results.append(f"{provider['name']}:{prob}¢")
                break  # 成功，不再重试
            except Exception:
                if attempt < 1:
                    time.sleep(1)
                    continue
                break

    # 使用高级投票系统（传入动态模型权重）
    if predictions_dict:
        # 获取 LLM 模型动态权重（基于历史准确率）
        try:
            from dynamic_optimizer import calculate_llm_model_weights

            model_weights = calculate_llm_model_weights()
        except Exception:
            model_weights = None

        voting_system = create_voting_system(model_weights=model_weights)
        vote_result = voting_system.vote(predictions_dict)

        # 最少投票数检查
        n_votes = len(predictions_dict)
        if n_votes < MIN_VALID_VOTES:
            log.warning(f"LLM投票不足: {n_votes}/{MIN_VALID_VOTES} 票，跳过该市场")
            return None, model_results, {"confidence": 0, "disagreement": 100, "need_review": True}

        avg = vote_result["final_prediction"] / 100.0
        confidence = vote_result["confidence"]
        disagreement = vote_result["disagreement"]

        # 记录投票详情
        if vote_result["need_review"]:
            log.warning(f"LLM投票分歧大: {disagreement:.1f}%, 置信度: {confidence:.2f}")

        return (
            avg,
            model_results,
            {
                "confidence": confidence,
                "disagreement": disagreement,
                "need_review": vote_result["need_review"],
            },
        )

    return None, [], {}


def place_order(token_id, side, amount, price):
    """下单（DRY_RUN 模式返回模拟结果）"""
    if DRY_RUN:
        return {
            "status": "DRY_RUN",
            "message": f"模拟 {side} ${amount:.2f} @ {price * 100:.0f}¢",
        }

    try:
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import OrderArgs, OrderType

        client = ClobClient(
            CLOB_API,
            key=POLYMARKET_KEY,
            chain_id=137,
            signature_type=SIGNATURE_TYPE,
            funder=POLYMARKET_FUNDER,
        )
        creds = client.derive_api_key()
        client.set_api_creds(creds)

        order = OrderArgs(
            price=round(price, 2),
            size=amount,
            side=side,
            token_id=token_id,
        )
        signed = client.create_order(order)
        resp = client.post_order(signed, OrderType.GTC)
        return {"status": "SUCCESS", "response": resp}
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}


def save_trade(trade_info):
    """保存交易记录（使用原子写入+正确的文件锁）"""
    append_to_json_array(TRADE_LOG, trade_info)


def format_output(decisions, edge_threshold=None):
    """格式化输出结果

    Args:
        decisions: 决策列表
        edge_threshold: 动态优势阈值（来自自适应权重），默认使用全局 EDGE_THRESHOLD
    """
    if not decisions:
        return ""  # 静默

    # 使用动态阈值，回退到全局默认值
    effective_threshold = edge_threshold if edge_threshold is not None else EDGE_THRESHOLD

    lines = []
    lines.append("🤖 PolyStrat AI 分析报告")
    lines.append(f"⏰ {datetime.now(timezone.utc).strftime('%m-%d %H:%M')} UTC")
    lines.append(f"📊 模式: {'🧪 测试' if DRY_RUN else '💰 实盘'}")
    lines.append("")

    trades_made = 0
    for d in decisions:
        edge = d["edge"]
        direction = d["direction"]
        market = d["market"]
        category = market.get("category", "")

        # 显示所有分析过的市场（使用动态阈值）
        emoji = (
            "🟢"
            if abs(edge) >= effective_threshold and trades_made < MAX_TRADES_PER_RUN
            else "⚪"
        )
        cat_emoji = {
            "Crypto": "₿",
            "Politics": "🏛",
            "Sports": "⚽",
            "Entertainment": "🎬",
            "Geopolitics": "🌍",
            "Economics": "📊",
            "Technology": "🤖",
            "Weather": "🌤",
            "Science": "🔬",
            "Health": "🏥",
        }.get(category, "📌")
        lines.append(f"{emoji} {cat_emoji} {market['title'][:50]}")
        lines.append(
            f"   市场价: Yes {market['yes_price'] * 100:.0f}¢ | No {market['no_price'] * 100:.0f}¢"
        )
        lines.append(f"   AI判断: Yes {d['llm_prob'] * 100:.0f}¢")
        # 显示情感分析
        sentiment_score = d.get("sentiment_score", 0)
        if sentiment_score != 0:
            sentiment_label = (
                "正面"
                if sentiment_score > 0.1
                else "负面"
                if sentiment_score < -0.1
                else "中性"
            )
            lines.append(f"   新闻情感: {sentiment_label} ({sentiment_score:+.2f})")
        # 显示链上信号
        onchain_signal = d.get("onchain_signal", {})
        if onchain_signal and onchain_signal.get("recommendation") != "hold":
            lines.append(
                f"   链上信号: {onchain_signal.get('recommendation', 'hold')} (置信度: {onchain_signal.get('confidence', 0):.2f})"
            )
        # 显示 ML 信号
        ml_signal = d.get("ml_signal", {})
        if ml_signal and ml_signal.get("confidence", 0) > 0.5:
            lines.append(
                f"   ML信号: {ml_signal.get('recommendation', '数据不足')} (置信度: {ml_signal.get('confidence', 0):.2f})"
            )
        # 显示套利机会
        arbitrage_opportunities = d.get("arbitrage_opportunities", [])
        if arbitrage_opportunities:
            lines.append(f"   🔥 套利机会: {len(arbitrage_opportunities)} 个")
            for opp in arbitrage_opportunities[:1]:
                lines.append(
                    f"      买入: {opp.get('buy_platform', '')} @ {opp.get('buy_price', 0):.2f}"
                )
                lines.append(
                    f"      卖出: {opp.get('sell_platform', '')} @ {opp.get('sell_price', 0):.2f}"
                )
                lines.append(f"      利润: {opp.get('profit_pct', 0):.1f}%")
        # 显示最终概率
        final_prob = d.get("final_prob", d["llm_prob"])
        if abs(final_prob - d["llm_prob"]) > 0.01:
            lines.append(f"   综合判断: Yes {final_prob * 100:.0f}¢")
        # 显示各模型判断
        model_results = d.get("model_results", [])
        if model_results:
            lines.append(f"   模型投票: {' | '.join(model_results)}")
        lines.append(f"   优势: {direction} {abs(edge) * 100:+.1f}%")
        # 显示投票置信度
        vote_details = d.get("vote_details", {})
        if vote_details:
            vconf = vote_details.get("confidence", 0)
            vdis = vote_details.get("disagreement", 0)
            lines.append(f"   投票置信: {vconf:.2f} | 分歧: {vdis:.1f}")
        # 显示风险检查
        risk_check = d.get("risk_check", {})
        if risk_check and not risk_check.get("should_trade", True):
            lines.append(f"   ⚠️ 风险拦截: {risk_check.get('reason', '')}")
        # 显示结算时间
        end_date = market.get("end_date", "")
        if end_date:
            try:
                dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                days_left = (dt - datetime.now(timezone.utc)).days
                lines.append(f"   结算: {dt.strftime('%Y-%m-%d')} | 剩余{days_left}天")
            except Exception:
                pass

        if abs(edge) >= effective_threshold and trades_made < MAX_TRADES_PER_RUN:
            result = d.get("order_result")
            if result:
                status = result.get("status", "")
                if status == "DRY_RUN":
                    lines.append(f"   ✅ 已模拟下单: {direction} ${BET_AMOUNT:.2f}")
                elif status == "SUCCESS":
                    lines.append(f"   ✅ 已实盘下单: {direction} ${BET_AMOUNT:.2f}")
                else:
                    lines.append(f"   ❌ 下单失败: {result.get('message', '')}")
            else:
                lines.append(f"   ⚠️ 未下单（token_id 缺失）")
            trades_made += 1

        lines.append("")

    if trades_made > 0:
        lines.append(f"📈 本轮共下单 {trades_made} 笔")
    else:
        lines.append("💤 本轮无符合条件的机会")

    return "\n".join(lines)


def main():
    """主流程（集成新闻搜索、情感分析、风险管理、自适应权重 + 动态优化）"""
    import time as _time

    start_time = _time.time()
    log.info("=" * 50)
    log.info("PolyStrat 启动")

    # === 结算同步（先更新交易结果，让 ML 学习有目标变量）===
    try:
        set_settlement_log_path(TRADE_LOG)
        settle_stats = update_settled_trades()
        if settle_stats.get("updated", 0) > 0 or settle_stats.get("timeout", 0) > 0:
            log.info(
                f"结算同步: {settle_stats['wins']}胜/{settle_stats['losses']}负, PnL {settle_stats.get('total_pnl', 0):+.2f}"
            )
    except Exception as e:
        log_error("settlement", e, "结算同步失败（非致命）")

    # 1. 获取活跃市场（按流动性排序取前50，覆盖更多机会）
    markets = fetch_active_markets(limit=50)
    if not markets:
        return  # 无市场，静默

    decisions = []
    trades_made = 0  # 实际下单计数

    # 获取账户余额（从配置读取）
    balance = float(os.environ.get("POLYSTRAT_BALANCE", "1000.0"))

    # 加载交易历史并计算自适应权重
    trade_history = load_trade_history()
    adaptive_weights = calculate_adaptive_weights(trade_history)

    # === 止损检查 ===
    from risk_management import check_stop_loss as _check_stop_loss

    stop_loss_result = _check_stop_loss(balance, trade_history)
    if stop_loss_result["triggered"]:
        log.warning(f"止损触发: {stop_loss_result['reason']}")
        print(f"🛑 止损触发: {stop_loss_result['reason']}")
        print(f"   累计回撤: {stop_loss_result['drawdown_pct']:.2%}")
        # 仍继续分析市场，但不下单
        STOP_LOSS_TRIGGERED = True
    else:
        STOP_LOSS_TRIGGERED = False

    # === 动态优化：LLM 模型权重 + 价格阈值 ===
    llm_model_weights = calculate_llm_model_weights(trade_history)
    dynamic_thresholds = get_dynamic_price_thresholds(trade_history)

    # === 修复：构建已交易市场集合（动态去重窗口） ===
    traded_markets_24h = set()
    now = datetime.now(timezone.utc)
    for t in trade_history:
        try:
            trade_time = datetime.fromisoformat(
                t.get("timestamp", "").replace("Z", "+00:00")
            )
            hours_ago = (now - trade_time).total_seconds() / 3600
            # 使用动态去重窗口
            dedup_hours = get_dynamic_dedup_hours(t.get("end_date", ""))
            if hours_ago < dedup_hours:
                # 使用 condition_id 作为去重键（比 title 更可靠）
                cid = t.get("condition_id", "")
                if cid:
                    traded_markets_24h.add(cid)
                else:
                    # 兼容旧记录：无 condition_id 时用 title 小写去重
                    traded_markets_24h.add(t.get("market", "").lower())
        except Exception:
            pass

    # 使用自适应权重（包含4信号 + 动态阈值）
    llm_weight = adaptive_weights.get("llm_weight", SIGNAL_WEIGHTS["llm"])
    sentiment_weight = adaptive_weights.get(
        "sentiment_weight", SIGNAL_WEIGHTS["sentiment"]
    )
    onchain_weight = adaptive_weights.get("onchain_weight", SIGNAL_WEIGHTS["onchain"])
    ml_weight = adaptive_weights.get("ml_weight", SIGNAL_WEIGHTS["ml"])
    edge_threshold = adaptive_weights.get("edge_threshold", EDGE_THRESHOLD)

    # 归一化确保4信号权重总和=1.0（不含微观结构和套利）
    adaptive_weight_sum = llm_weight + sentiment_weight + onchain_weight + ml_weight
    if abs(adaptive_weight_sum - 1.0) > 0.01:
        llm_weight /= adaptive_weight_sum
        sentiment_weight /= adaptive_weight_sum
        onchain_weight /= adaptive_weight_sum
        ml_weight /= adaptive_weight_sum

    # 多平台/套利信号权重（从各信号等比抽取，保持总和1.0）
    ARBITRAGE_WEIGHT = 0.05
    MICROSTRUCTURE_WEIGHT = MICROSTRUCTURE_CONFIG["weight"] if MICROSTRUCTURE_CONFIG["enabled"] else 0

    # 调整权重，确保总和=1.0（含微观结构和套利）
    total_extra_weight = ARBITRAGE_WEIGHT + MICROSTRUCTURE_WEIGHT
    if total_extra_weight > 0:
        llm_weight *= 1 - total_extra_weight
        sentiment_weight *= 1 - total_extra_weight
        onchain_weight *= 1 - total_extra_weight
        ml_weight *= 1 - total_extra_weight

    # 输出权重配置（包含动态优化信息）
    print(f"⚖️ 自适应权重配置:")
    print(
        f"   LLM: {llm_weight:.3f} | 情感: {sentiment_weight:.3f} | 链上: {onchain_weight:.3f} | ML: {ml_weight:.3f}"
    )
    print(f"   优势阈值: {edge_threshold:.2%} | 套利信号: {ARBITRAGE_WEIGHT:.0%} | 微观结构: {MICROSTRUCTURE_WEIGHT:.0%}")
    print(
        f"   情感斜率: {adaptive_weights.get('sentiment_mapping_slope', 0.35):.2f} | 链上乘数: {adaptive_weights.get('onchain_multiplier', 1.0):.2f}"
    )
    print(f"   样本大小: {adaptive_weights.get('sample_size', 0)}")
    print()

    # 输出甜蜜点配置
    if SWEET_SPOT_MODE:
        print(f"🎯 甜蜜点模式: 已启用")
        print(f"   价格区间: {SWEET_SPOT_CONFIG['min_price']:.0%} - {SWEET_SPOT_CONFIG['max_price']:.0%}")
        print(f"   最低流动性: ${SWEET_SPOT_CONFIG['min_liquidity']:,}")
        print(f"   分歧区间: {SWEET_SPOT_CONFIG['min_disagreement']}% - {SWEET_SPOT_CONFIG['max_disagreement']}%")
        print(f"   最低置信度: {SWEET_SPOT_CONFIG['min_confidence']:.0%}")
        print(f"   优选类型: {', '.join(SWEET_SPOT_CONFIG['preferred_categories'])}")
        print()

    # 输出微观结构配置
    if MICROSTRUCTURE_CONFIG["enabled"]:
        print(f"📊 市场微观结构信号: 已启用")
        print(f"   权重: {MICROSTRUCTURE_CONFIG['weight']:.0%}")
        print(f"   最低置信度: {MICROSTRUCTURE_CONFIG['min_confidence']:.0%}")
        print()

    # 输出 LLM 模型动态权重
    print(f"🤖 LLM 模型动态权重:")
    for model, weight in llm_model_weights.items():
        print(f"   {model}: {weight:.1%}")
    print()

    # 输出动态价格阈值
    print(
        f"💰 动态价格阈值: {dynamic_thresholds['min_price']:.0%} - {dynamic_thresholds['max_price']:.0%}"
    )
    print()

    for market in markets:
        title = market["title"]
        yes_price = market["yes_price"]
        category = market.get("category", "Other")
        liquidity = market.get("liquidity", 0)
        condition_id = market.get("condition_id", "")  # 唯一标识，用于去重

        # 甜蜜点模式：聚焦高胜率区间
        if SWEET_SPOT_MODE:
            # 跳过甜蜜点区间外的市场
            if yes_price < SWEET_SPOT_CONFIG["min_price"] or yes_price > SWEET_SPOT_CONFIG["max_price"]:
                continue
            # 跳过低流动性市场（甜蜜点需要更高流动性）
            if liquidity < SWEET_SPOT_CONFIG["min_liquidity"]:
                continue
            # 优先选择擅长的事件类型
            if category not in SWEET_SPOT_CONFIG["preferred_categories"]:
                continue
        else:
            # 原始模式：使用动态阈值
            if (
                yes_price > dynamic_thresholds["max_price"]
                or yes_price < dynamic_thresholds["min_price"]
            ):
                continue
            # 跳过低流动性市场
            if liquidity < MIN_LIQUIDITY:
                continue

        # === 修复：跳过DEDUP_HOURS小时内已交易的市场（用 condition_id 去重） ===
        dedup_key = condition_id if condition_id else title.lower()
        if dedup_key in traded_markets_24h:
            print(f"⏭️ 跳过已交易市场: {title[:40]}...")
            continue

        # 2. 搜索相关新闻（使用智能关键词 + news_search 模块）
        search_queries = get_search_queries(title, category, max_queries=2)
        search_query = search_queries[0] if search_queries else title[:50]

        # 打印使用的关键词（调试用）
        print(f"🔍 搜索关键词: {search_query}")

        try:
            # 使用多个关键词搜索，合并结果
            all_news = []
            for query in search_queries[:2]:
                news = search_news_for_market(query, max_results=2)
                all_news.extend(news)

            # 去重
            seen_titles = set()
            news_list = []
            for n in all_news:
                t = n.get("title", "").lower()
                if t and t not in seen_titles:
                    seen_titles.add(t)
                    news_list.append(n)

            news_sources = list(set(n.get("source_type", "unknown") for n in news_list))
            news_text = "\n".join(
                [
                    f"标题: {n.get('title', '')}\n描述: {n.get('description', '')}"
                    for n in news_list[:4]
                ]
            )
        except Exception as e:
            news_list = []
            news_sources = []
            news_text = ""
            print(f"⚠️ 新闻搜索失败: {e}")

        # 3. 情感分析（简化版，使用关键词分析，避免LLM超时）
        try:
            # 使用简单情感分析（快速）
            from sentiment_analysis import analyze_sentiment_simple

            if news_list:
                sentiment_scores = []
                for news in news_list[:2]:
                    text = news.get("title", "") + " " + news.get("description", "")
                    result = analyze_sentiment_simple(text)
                    sentiment_scores.append(result["score"])
                sentiment_score = (
                    sum(sentiment_scores) / len(sentiment_scores)
                    if sentiment_scores
                    else 0
                )
                sentiment_confidence = 0.5
            else:
                sentiment_score = 0
                sentiment_confidence = 0
        except Exception as e:
            sentiment_score = 0
            sentiment_confidence = 0
            print(f"⚠️ 情感分析失败: {e}")

        # 4. 链上信号分析
        try:
            onchain_signal = get_onchain_signal(title)
            onchain_recommendation = onchain_signal.get("recommendation", "hold")
            onchain_confidence = onchain_signal.get("confidence", 0.3)
        except Exception as e:
            onchain_signal = {"recommendation": "hold", "confidence": 0.3}
            onchain_recommendation = "hold"
            onchain_confidence = 0.3
            print(f"⚠️ 链上信号分析失败: {e}")

        # 5. 多平台信号分析
        try:
            multiplatform_signal = get_multiplatform_signal(title)
            has_arbitrage = multiplatform_signal.get("arbitrage_count", 0) > 0
            arbitrage_opportunities = multiplatform_signal.get(
                "arbitrage_opportunities", []
            )
        except Exception as e:
            multiplatform_signal = {"found": False, "arbitrage_count": 0}
            has_arbitrage = False
            arbitrage_opportunities = []
            print(f"⚠️ 多平台信号分析失败: {e}")

        # 6. LLM 分析概率（使用高级投票系统，返回加权平均和投票详情）
        llm_prob, model_results, vote_details = llm_analyze_probability(
            title, news_text, yes_price, category
        )
        if llm_prob is None:
            continue

        # 记录投票详情
        if vote_details.get("need_review"):
            log.warning(f"市场 '{title[:30]}' LLM投票分歧大，置信度低")

        # 甜蜜点模式：检查投票质量
        if SWEET_SPOT_MODE:
            disagreement = vote_details.get("disagreement", 0)
            confidence = vote_details.get("confidence", 0)

            # 分歧太小 = 市场已定价，无优势
            if disagreement < SWEET_SPOT_CONFIG["min_disagreement"]:
                print(f"⏭️ 跳过 {title[:40]}... (分歧 {disagreement:.1f}% < {SWEET_SPOT_CONFIG['min_disagreement']}%)")
                continue

            # 分歧太大 = 噪声，不可靠
            if disagreement > SWEET_SPOT_CONFIG["max_disagreement"]:
                print(f"⏭️ 跳过 {title[:40]}... (分歧 {disagreement:.1f}% > {SWEET_SPOT_CONFIG['max_disagreement']}%)")
                continue

            # 置信度太低 = 模型不确定
            if confidence < SWEET_SPOT_CONFIG["min_confidence"]:
                print(f"⏭️ 跳过 {title[:40]}... (置信度 {confidence:.2f} < {SWEET_SPOT_CONFIG['min_confidence']})")
                continue

        # 7. ML 信号分析（在 LLM 分析之后，因为需要 llm_prob）
        # 先计算 edge 供 ML 使用（ML 需要 edge 作为特征）
        preliminary_edge = llm_prob - yes_price
        preliminary_direction = "Yes" if preliminary_edge > 0 else "No"

        # 计算到期时间（天数）
        end_date = market.get("end_date", "")
        time_to_expiry = 0
        if end_date:
            try:
                if "T" in end_date:
                    dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                else:
                    dt = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                time_to_expiry = max(0, (dt - datetime.now(timezone.utc)).days)
            except:
                time_to_expiry = 0

        try:
            ml_signal = get_ml_signal(
                llm_prob,
                sentiment_score,
                preliminary_edge,  # 使用真实 edge，而非 0
                yes_price,
                preliminary_direction,
                onchain_signal=onchain_signal,
                time_to_expiry=time_to_expiry,
                category=category,
                news_count=len(news_list),
                vote_details=vote_details,
                microstructure_signal=microstructure_signal,
            )
            ml_prob = ml_signal.get("ml_prob", 0.5)
            ml_confidence = ml_signal.get("confidence", 0.5)
        except Exception as e:
            ml_signal = {
                "ml_prob": 0.5,
                "confidence": 0.5,
                "recommendation": "数据不足",
            }
            ml_prob = 0.5
            ml_confidence = 0.5
            print(f"⚠️ ML 信号分析失败: {e}")

        # 7. 综合判断（各信号独立计算概率，然后加权平均）
        # 所有信号统一为概率格式 (0-1)
        # 权重来自自适应权重模块（基于历史胜率动态调整）

        # 追踪哪些信号是真实值 vs 回退值
        signal_fallbacks = 0

        # 信号1: LLM 概率（已经是概率，直接使用）
        llm_signal_prob = llm_prob
        # LLM 失败时 llm_prob 为 None → continue，不会到这里

        # 信号2: 情感概率（将 sentiment_score 转换为概率）
        # 使用自适应映射斜率（基于情感信号历史准确率）
        sentiment_mapping_slope = adaptive_weights.get("sentiment_mapping_slope", 0.35)
        sentiment_signal_prob = 0.5 + sentiment_score * sentiment_mapping_slope
        sentiment_signal_prob = max(0.15, min(0.85, sentiment_signal_prob))
        if sentiment_score == 0 and sentiment_confidence == 0:
            signal_fallbacks += 1  # 情感信号完全回退

        # 信号3: 链上概率（连续映射，纳入置信度 × 自适应乘数）
        onchain_confidence_val = onchain_signal.get("confidence", 0.3)
        onchain_mult = adaptive_weights.get("onchain_multiplier", 1.0)
        if onchain_recommendation == "strong_buy":
            onchain_signal_prob = 0.5 + 0.35 * onchain_confidence_val * onchain_mult
        elif onchain_recommendation == "buy":
            onchain_signal_prob = 0.5 + 0.15 * onchain_confidence_val * onchain_mult
        elif onchain_recommendation == "strong_sell":
            onchain_signal_prob = 0.5 - 0.35 * onchain_confidence_val * onchain_mult
        elif onchain_recommendation == "sell":
            onchain_signal_prob = 0.5 - 0.15 * onchain_confidence_val * onchain_mult
        else:
            onchain_signal_prob = 0.5
            if onchain_recommendation == "hold" and onchain_confidence_val <= 0.3:
                signal_fallbacks += 1  # 链上信号无有效数据
        onchain_signal_prob = max(0.01, min(0.99, onchain_signal_prob))  # 边界保护

        # 信号4: ML 概率（已经是概率，直接使用）
        ml_signal_prob = ml_prob
        if ml_confidence <= 0.5 and ml_prob == 0.5:
            signal_fallbacks += 1  # ML 信号无有效数据

        # 信号5: 市场微观结构信号（订单簿、价差、成交量）
        if MICROSTRUCTURE_CONFIG["enabled"]:
            try:
                microstructure_signal = calculate_microstructure_signal(
                    condition_id, token_id, market.get("slug")
                )
                microstructure_prob = microstructure_signal.get("confidence", 0.3)
                microstructure_recommendation = microstructure_signal.get("recommendation", "hold")

                # 将微观结构信号转换为概率
                if microstructure_recommendation == "buy":
                    microstructure_signal_prob = 0.5 + 0.2 * microstructure_prob
                elif microstructure_recommendation == "sell":
                    microstructure_signal_prob = 0.5 - 0.2 * microstructure_prob
                else:
                    microstructure_signal_prob = 0.5

                microstructure_signal_prob = max(0.01, min(0.99, microstructure_signal_prob))

                # 检查置信度
                if microstructure_prob < MICROSTRUCTURE_CONFIG["min_confidence"]:
                    signal_fallbacks += 1

            except Exception as e:
                microstructure_signal = {"recommendation": "hold", "confidence": 0.3}
                microstructure_signal_prob = 0.5
                signal_fallbacks += 1
                print(f"⚠️ 微观结构信号分析失败: {e}")
        else:
            microstructure_signal = {"recommendation": "hold", "confidence": 0.3}
            microstructure_signal_prob = 0.5

        # 信号6: 多平台/套利信号（方向感知：套利信号不偏向 Yes 或 No）
        # 套利本身是价格差异，不改变事件概率判断，仅作为置信度加成
        if has_arbitrage and arbitrage_opportunities:
            # 套利机会的存在增强了对当前市场定价的置信度
            # 但不改变方向判断 → 回归 0.5（中性），加成体现在权重而非偏移
            arbitrage_signal = 0.5
        else:
            arbitrage_signal = 0.5

        # 使用自适应权重进行加权平均（含微观结构和套利信号）
        final_prob = (
            llm_signal_prob * llm_weight
            + sentiment_signal_prob * sentiment_weight
            + onchain_signal_prob * onchain_weight
            + ml_signal_prob * ml_weight
            + microstructure_signal_prob * MICROSTRUCTURE_CONFIG["weight"]
            + arbitrage_signal * ARBITRAGE_WEIGHT
        )

        # 边界检查
        final_prob = max(0.01, min(0.99, final_prob))  # 防止极端值

        # 信号质量检查：超过 2 个信号回退时跳过该市场（防噪声交易）
        if signal_fallbacks >= 2:
            print(f"⏭️ 跳过 {title[:40]}... ({signal_fallbacks}/4 信号回退)")
            continue

        # 8. 计算优势
        edge = final_prob - yes_price

        if edge > 0:
            direction = "Yes"
            token_id = market.get("yes_token", "")
            order_price = yes_price
        else:
            direction = "No"
            token_id = market.get("no_token", "")
            order_price = market.get("no_price", 1 - yes_price)

        # 跳过无 token_id 的市场
        if not token_id:
            continue

        # 7. 风险检查（使用投票置信度，而非情感置信度）
        voting_confidence = vote_details.get("confidence", sentiment_confidence)
        should_trade_flag, risk_reason = should_trade(
            market,
            confidence=voting_confidence,
            news_sentiment=sentiment_score,
            balance=balance,
        )

        decision = {
            "market": market,
            "llm_prob": llm_prob,
            "sentiment_score": sentiment_score,
            "onchain_signal": onchain_signal,
            "ml_signal": ml_signal,
            "multiplatform_signal": multiplatform_signal,
            "arbitrage_opportunities": arbitrage_opportunities,
            "final_prob": final_prob,
            "edge": edge,
            "direction": direction,
            "order_result": None,
            "model_results": model_results,
            "vote_details": vote_details,  # 投票详情（置信度、分歧度）
            "risk_check": {"should_trade": should_trade_flag, "reason": risk_reason},
        }

        # 8. 如果优势足够大，且通过风险检查，下单
        if (
            abs(edge) >= edge_threshold
            and trades_made < MAX_TRADES_PER_RUN
            and token_id
            and should_trade_flag
            and not STOP_LOSS_TRIGGERED
        ):
            # 检查断路器
            try:
                breaker_ok = check_breaker()
            except Exception as e:
                log_error("breaker", e, "断路器检查失败")
                breaker_ok = False  # 断路器异常时禁止交易（fail-closed，保护资金安全）
            if not breaker_ok:
                log.warning("断路器已断开，跳过交易")
                decision["order_result"] = {"status": "BLOCKED", "reason": "断路器断开"}
                decisions.append(decision)
                continue

            # 计算仓位大小（Fractional Kelly + 投票置信度 + 流动性适配）
            # Kelly 公式: f* = edge / (1 - market_price) for Yes bets
            kelly_fraction = 0.25  # 25% Kelly 保守策略
            if direction == "Yes":
                kelly_pct = edge / (1 - yes_price) if (1 - yes_price) > 0.01 else 0
            else:
                kelly_pct = abs(edge) / yes_price if yes_price > 0.01 else 0
            kelly_pct = max(0, min(0.5, kelly_pct))  # 限制单笔不超过50%
            kelly_position = balance * kelly_pct * kelly_fraction * voting_confidence

            # 流动性调整
            if liquidity >= 50000:
                liquidity_factor = 1.5
            elif liquidity >= 10000:
                liquidity_factor = 1.0
            else:
                liquidity_factor = max(0.3, liquidity / 10000)

            # 最终仓位 = min(Kelly × 流动性调整, 硬上限)
            # trade_limits.check_trade_allowed 进一步限制单笔≤$10、仓位≤5%
            position_size = min(
                kelly_position * liquidity_factor,
                balance * 0.05,
                LIMITS_CONFIG["max_single_trade"],
            )
            # Polymarket 最小下单量 $0.50，若 Kelly 建议低于此值则跳过（边缘优势不足）
            MIN_ORDER = 0.50
            if position_size < MIN_ORDER:
                log.warning(
                    f"Kelly仓位 ${position_size:.2f} 低于最小下单额 ${MIN_ORDER}，跳过"
                )
                decision["order_result"] = {
                    "status": "SKIPPED",
                    "reason": f"Kelly仓位 ${position_size:.2f} < 最小${MIN_ORDER}",
                }
                decisions.append(decision)
                continue
            position_size = round(position_size, 2)

            # 检查交易限额
            allowed, limit_reason = check_trade_allowed(position_size, balance)
            if not allowed:
                log.warning(f"交易限额拒绝: {limit_reason}")
                decision["order_result"] = {"status": "BLOCKED", "reason": limit_reason}
                decisions.append(decision)
                continue

            # Kelly 计算出的是美元金额，CLOB 需要代币数量（shares）
            token_count = (
                position_size / order_price if order_price > 0 else position_size
            )
            result = place_order(token_id, "BUY", round(token_count, 2), order_price)
            decision["order_result"] = result

            # 记录交易（包含 condition_id 用于去重，含信号数据用于自适应学习）
            save_trade(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "mode": "DRY_RUN" if DRY_RUN else "LIVE",
                    "market": title,
                    "condition_id": condition_id,
                    "category": category,
                    "direction": direction,
                    "market_price": yes_price
                    if direction == "Yes"
                    else market["no_price"],
                    "llm_prob": llm_prob,
                    "sentiment_score": sentiment_score,
                    "onchain_signal": onchain_signal,
                    "ml_prob": ml_prob,
                    "model_results": model_results,
                    "final_prob": final_prob,
                    "edge": edge,
                    "amount": position_size,
                    "status": result.get("status"),
                    "token_id": token_id,
                    "risk_reason": risk_reason,
                    "news_sources": news_sources,
                    "end_date": market.get("end_date", ""),
                    "result": "pending",  # 初始状态：待结算
                }
            )
            trades_made += 1

            # 记录到交易限额
            record_trade(position_size)

        decisions.append(decision)

        # 避免 API 限流
        time.sleep(1)

    # 9. 输出结果（传入动态阈值，确保显示与实际交易一致）
    output = format_output(decisions, edge_threshold=edge_threshold)
    if output:
        print(output)

    # 10. 输出风险报告
    try:
        risk_report = get_risk_report()
        print(f"\n📊 风险报告:")
        print(f"   总交易: {risk_report['total_trades']}")
        print(f"   总仓位: {risk_report['total_exposure']:.2f}")
        print(f"   风险等级: {risk_report['risk_level']}")
    except Exception as e:
        log_error("main", e, "风险报告生成失败")
        print(f"⚠️ 风险报告生成失败: {e}")

    # 11. 输出断路器状态
    try:
        breaker_status = get_breaker_status()
        status_emoji = {"closed": "🟢", "open": "🔴", "half_open": "🟡"}
        print(f"\n⚡ 断路器状态:")
        print(
            f"   状态: {status_emoji.get(breaker_status['status'], '❓')} {breaker_status['status']}"
        )
        print(f"   连续亏损: {breaker_status['consecutive_losses']}")
        print(f"   今日盈亏: ${breaker_status['daily_pnl']:+.2f}")
    except Exception as e:
        log_error("main", e, "断路器状态获取失败")

    # 12. 输出交易限额状态
    try:
        limits_status = get_limits_status()
        print(f"\n📊 交易限额:")
        print(
            f"   今日交易: {limits_status['daily_trades']}/{limits_status['max_daily_trades']}"
        )
        print(
            f"   今日交易量: ${limits_status['daily_volume']:.2f}/${limits_status['max_daily_volume']:.2f}"
        )
    except Exception as e:
        log_error("main", e, "交易限额状态获取失败")

    # 输出止损状态
    if STOP_LOSS_TRIGGERED:
        print(
            f"\n🛑 止损已触发：累计回撤 {stop_loss_result['drawdown_pct']:.2%}，暂停新交易"
        )
    else:
        print(f"\n✅ 止损状态：正常（累计回撤 {stop_loss_result['drawdown_pct']:.2%}）")

    # 输出动态优化报告
    try:
        print(format_optimization_report())
    except Exception as e:
        print(f"⚠️ 优化报告生成失败: {e}")

    # 运行汇总
    elapsed = _time.time() - start_time
    print(f"\n📋 运行汇总:")
    print(f"   扫描市场: {len(markets)} 个")
    print(f"   分析决策: {len(decisions)} 个")
    print(f"   本轮下单: {trades_made} 笔")
    print(f"   耗时: {elapsed:.1f} 秒")
    if len(decisions) == 0 and len(markets) > 0:
        print(f"   ⚠️ 所有市场均被跳过（去重/价格/流动性过滤）")


if __name__ == "__main__":
    main()
