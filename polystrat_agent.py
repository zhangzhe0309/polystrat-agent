#!/usr/bin/env python3
"""
简易版 PolyStrat — AI 自主交易 Agent v2
功能：
1. 扫描 Polymarket 活跃市场
2. 搜索相关新闻（GNews + Currents + RSS）
3. 情感分析（LLM + 关键词）
4. LLM 分析概率（3模型投票）
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

# 导入自定义模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from news_search import search_news_for_market
from sentiment_analysis import analyze_news_sentiment, analyze_sentiment_simple
from risk_management import should_trade, calculate_position_size, get_risk_report
from onchain_monitor import get_onchain_signal
from adaptive_weights import calculate_adaptive_weights, load_trade_history
from ml_optimizer import get_ml_signal
from multi_platform import get_multiplatform_signal
from smart_keywords import get_search_queries
from dynamic_optimizer import (
    calculate_llm_model_weights, get_llm_model_weight,
    get_news_source_quota, calculate_position_with_liquidity,
    get_dynamic_price_thresholds, get_dynamic_dedup_hours,
    format_optimization_report)
from polystrat_logger import log, log_error, log_api_call, log_performance
from safe_file_ops import atomic_write_json, atomic_read_json, append_to_json_array

# === 配置 ===
# LLM Ensemble 链：Qwen 3.5 + Kimi K2.6 + Llama 3.3 70B（三模型投票）
LLM_PROVIDERS = [
    {
        "name": "Qwen 3.5",
        "api_key": os.environ.get("NVIDIA_API_KEY_2", ""),
        "base_url": "https://integrate.api.nvidia.com/v1",
        "model": "qwen/qwen3.5-397b-a17b",
    },
    {
        "name": "Kimi K2.6",
        "api_key": os.environ.get("NVIDIA_API_KEY_2", ""),
        "base_url": "https://integrate.api.nvidia.com/v1",
        "model": "moonshotai/kimi-k2.6",
    },
    {
        "name": "Llama 3.3 70B",
        "api_key": os.environ.get("NVIDIA_API_KEY_2", ""),
        "base_url": "https://integrate.api.nvidia.com/v1",
        "model": "meta/llama-3.3-70b-instruct",
    },
]

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

# 权重配置（优化后）
LLM_WEIGHT = 0.5  # LLM 分析权重
NEWS_WEIGHT = 0.5  # 新闻情感权重

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"

# 日志目录
LOG_DIR = Path("/root/.hermes/profiles/life/home/.hermes/polymarket_bot/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)
TRADE_LOG = LOG_DIR / "polystrat_trades.json"


def fetch_active_markets(limit=20):
    """从 Gamma API 获取活跃市场，按流动性排序"""
    try:
        resp = requests.get(
            f"{GAMMA_API}/markets",
            params={
                "closed": "false",
                "limit": limit,
                "active": "true",
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
            if any(x in title_lower for x in ['bitcoin', 'btc', 'crypto', 'eth', 'solana', 'blockchain', 'defi']):
                category = "Crypto"
            elif any(x in title_lower for x in ['trump', 'biden', 'election', 'president', 'democrat', 'republican', 'newsom', 'aoc', 'congress', 'senate']):
                category = "Politics"
            elif any(x in title_lower for x in ['world cup', 'fifa', 'soccer', 'football', 'nba', 'nfl', 'mlb', 'tennis', 'golf', 'boxing']):
                category = "Sports"
            elif any(x in title_lower for x in ['gta', 'album', 'movie', 'oscar', 'grammy', 'rihanna', 'carti', 'taylor', 'beyonce', 'kanye']):
                category = "Entertainment"
            elif any(x in title_lower for x in ['war', 'china', 'russia', 'iran', 'ukraine', 'taiwan', 'israel', 'nato', 'military']):
                category = "Geopolitics"
            elif any(x in title_lower for x in ['fed', 'interest', 'inflation', 'gdp', 'stock', 'recession', 'economy', 'unemployment']):
                category = "Economics"
            elif any(x in title_lower for x in ['ai', 'artificial intelligence', 'chatgpt', 'openai', 'google', 'apple', 'tech']):
                category = "Technology"
            elif any(x in title_lower for x in ['climate', 'weather', 'hurricane', 'earthquake', 'flood', 'temperature']):
                category = "Weather"
            elif any(x in title_lower for x in ['space', 'nasa', 'spacex', 'mars', 'moon', 'rocket']):
                category = "Science"
            elif any(x in title_lower for x in ['health', 'covid', 'vaccine', 'disease', 'pandemic', 'hospital']):
                category = "Health"
            else:
                category = "Other"

            valid.append({
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
            })
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
        clean = re.sub(r'<[^>]+>', ' ', text)
        clean = re.sub(r'\s+', ' ', clean)
        # 取前 2000 字符作为上下文
        context = clean[:2000]
        return context
    except Exception:
        return ""


def llm_analyze_probability(market_title, news_context, current_yes_price, category="Other"):
    """使用多 LLM 分析市场概率，取平均值（Ensemble）"""
    if not LLM_PROVIDERS:
        return None, []

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
当前市场价: Yes = {current_yes_price*100:.0f}¢ (即市场认为有 {current_yes_price*100:.0f}% 的概率)

分析提示: {context_hint}

相关新闻/背景信息:
{news_context if news_context else "暂无相关新闻"}

请分析并给出你认为的实际概率（0-100之间的整数）。
只输出一个数字，不要解释。例如: 65"""

    # 遍历所有 provider，收集概率
    probabilities = []
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
                        "max_tokens": 10,
                        "temperature": 0.1,
                    },
                    timeout=20,
                )
                if resp.status_code == 429:
                    break  # 限流，跳到下一个 provider
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"].strip()
                match = re.search(r'(\d+)', content)
                if match:
                    prob = int(match.group(1))
                    if 0 <= prob <= 100:
                        probabilities.append(prob / 100.0)
                        model_results.append(f"{provider['name']}:{prob}¢")
                break  # 成功，不再重试
            except Exception:
                if attempt < 1:
                    time.sleep(1)
                    continue
                break

    # 返回平均值和各模型结果
    if probabilities:
        avg = sum(probabilities) / len(probabilities)
        return avg, model_results
    return None, []


def place_order(token_id, side, amount, price):
    """下单（DRY_RUN 模式返回模拟结果）"""
    if DRY_RUN:
        return {
            "status": "DRY_RUN",
            "message": f"模拟 {side} ${amount:.2f} @ {price*100:.0f}¢"
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


def format_output(decisions):
    """格式化输出结果"""
    if not decisions:
        return ""  # 静默

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

        # 显示所有分析过的市场
        emoji = "🟢" if abs(edge) >= EDGE_THRESHOLD and trades_made < MAX_TRADES_PER_RUN else "⚪"
        cat_emoji = {"Crypto": "₿", "Politics": "🏛", "Sports": "⚽", "Entertainment": "🎬", "Geopolitics": "🌍", "Economics": "📊", "Technology": "🤖", "Weather": "🌤", "Science": "🔬", "Health": "🏥"}.get(category, "📌")
        lines.append(f"{emoji} {cat_emoji} {market['title'][:50]}")
        lines.append(f"   市场价: Yes {market['yes_price']*100:.0f}¢ | No {market['no_price']*100:.0f}¢")
        lines.append(f"   AI判断: Yes {d['llm_prob']*100:.0f}¢")
        # 显示情感分析
        sentiment_score = d.get("sentiment_score", 0)
        if sentiment_score != 0:
            sentiment_label = "正面" if sentiment_score > 0.1 else "负面" if sentiment_score < -0.1 else "中性"
            lines.append(f"   新闻情感: {sentiment_label} ({sentiment_score:+.2f})")
        # 显示链上信号
        onchain_signal = d.get("onchain_signal", {})
        if onchain_signal and onchain_signal.get("recommendation") != "hold":
            lines.append(f"   链上信号: {onchain_signal.get('recommendation', 'hold')} (置信度: {onchain_signal.get('confidence', 0):.2f})")
        # 显示 ML 信号
        ml_signal = d.get("ml_signal", {})
        if ml_signal and ml_signal.get("confidence", 0) > 0.5:
            lines.append(f"   ML信号: {ml_signal.get('recommendation', '数据不足')} (置信度: {ml_signal.get('confidence', 0):.2f})")
        # 显示套利机会
        arbitrage_opportunities = d.get("arbitrage_opportunities", [])
        if arbitrage_opportunities:
            lines.append(f"   🔥 套利机会: {len(arbitrage_opportunities)} 个")
            for opp in arbitrage_opportunities[:1]:
                lines.append(f"      买入: {opp.get('buy_platform', '')} @ {opp.get('buy_price', 0):.2f}")
                lines.append(f"      卖出: {opp.get('sell_platform', '')} @ {opp.get('sell_price', 0):.2f}")
                lines.append(f"      利润: {opp.get('profit_pct', 0):.1f}%")
        # 显示最终概率
        final_prob = d.get("final_prob", d['llm_prob'])
        if abs(final_prob - d['llm_prob']) > 0.01:
            lines.append(f"   综合判断: Yes {final_prob*100:.0f}¢")
        # 显示各模型判断
        model_results = d.get("model_results", [])
        if model_results:
            lines.append(f"   模型投票: {' | '.join(model_results)}")
        lines.append(f"   优势: {direction} {abs(edge)*100:+.1f}%")
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

        if abs(edge) >= EDGE_THRESHOLD and trades_made < MAX_TRADES_PER_RUN:
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
    
    # 1. 获取活跃市场（取前10个，减少处理时间）
    markets = fetch_active_markets(limit=10)
    if not markets:
        return  # 无市场，静默

    decisions = []
    trades_made = 0  # 实际下单计数
    
    # 获取账户余额（模拟）
    balance = 1000.0  # 模拟余额
    
    # 加载交易历史并计算自适应权重
    trade_history = load_trade_history()
    adaptive_weights = calculate_adaptive_weights(trade_history)
    
    # === 动态优化：LLM 模型权重 + 价格阈值 ===
    llm_model_weights = calculate_llm_model_weights(trade_history)
    dynamic_thresholds = get_dynamic_price_thresholds(trade_history)
    
    # === 修复：构建已交易市场集合（动态去重窗口） ===
    traded_markets_24h = set()
    now = datetime.now(timezone.utc)
    for t in trade_history:
        try:
            trade_time = datetime.fromisoformat(t.get("timestamp", "").replace("Z", "+00:00"))
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
    
    # 使用自适应权重
    llm_weight = adaptive_weights.get("llm_weight", LLM_WEIGHT)
    sentiment_weight = adaptive_weights.get("sentiment_weight", 0.3)
    onchain_weight = adaptive_weights.get("onchain_weight", 0.2)
    edge_threshold = adaptive_weights.get("edge_threshold", EDGE_THRESHOLD)
    
    # 输出权重配置（包含动态优化信息）
    print(f"⚖️ 自适应权重配置:")
    print(f"   LLM: {llm_weight:.3f} | 情感: {sentiment_weight:.3f} | 链上: {onchain_weight:.3f}")
    print(f"   优势阈值: {edge_threshold:.2%}")
    print(f"   样本大小: {adaptive_weights.get('sample_size', 0)}")
    print()
    
    # 输出 LLM 模型动态权重
    print(f"🤖 LLM 模型动态权重:")
    for model, weight in llm_model_weights.items():
        print(f"   {model}: {weight:.1%}")
    print()
    
    # 输出动态价格阈值
    print(f"💰 动态价格阈值: {dynamic_thresholds['min_price']:.0%} - {dynamic_thresholds['max_price']:.0%}")
    print()

    for market in markets:
        title = market["title"]
        yes_price = market["yes_price"]
        category = market.get("category", "Other")
        liquidity = market.get("liquidity", 0)
        condition_id = market.get("condition_id", "")  # 唯一标识，用于去重

        # 跳过极端价格（>97¢ 或 <3¢ 的市场没太大空间）
        if yes_price > dynamic_thresholds["max_price"] or yes_price < dynamic_thresholds["min_price"]:
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
            
            news_text = "\n".join([n.get("title", "") for n in news_list[:3]])
        except Exception as e:
            news_list = []
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
                sentiment_score = sum(sentiment_scores) / len(sentiment_scores) if sentiment_scores else 0
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
            arbitrage_opportunities = multiplatform_signal.get("arbitrage_opportunities", [])
        except Exception as e:
            multiplatform_signal = {"found": False, "arbitrage_count": 0}
            has_arbitrage = False
            arbitrage_opportunities = []
            print(f"⚠️ 多平台信号分析失败: {e}")

        # 6. LLM 分析概率（传入分类，返回平均值和各模型结果）
        llm_prob, model_results = llm_analyze_probability(title, news_text, yes_price, category)
        if llm_prob is None:
            continue

        # 7. ML 信号分析（在 LLM 分析之后，因为需要 llm_prob）
        try:
            ml_signal = get_ml_signal(
                llm_prob,
                sentiment_score,
                0,  # edge 在后面计算
                yes_price,
                "Yes" if llm_prob > yes_price else "No",
                BET_AMOUNT
            )
            ml_prob = ml_signal.get("ml_prob", 0.5)
            ml_confidence = ml_signal.get("confidence", 0.5)
        except Exception as e:
            ml_signal = {"ml_prob": 0.5, "confidence": 0.5, "recommendation": "数据不足"}
            ml_prob = 0.5
            ml_confidence = 0.5
            print(f"⚠️ ML 信号分析失败: {e}")

        # 7. 综合判断（加权平均 - 使用自适应权重 + ML）
        # 将情感分数转换为概率调整 (-1 到 1 -> -0.1 到 0.1)
        sentiment_adjustment = sentiment_score * 0.1
        
        # 链上信号调整
        onchain_adjustment = 0
        if onchain_recommendation == "strong_buy":
            onchain_adjustment = 0.05
        elif onchain_recommendation == "buy":
            onchain_adjustment = 0.02
        elif onchain_recommendation == "sell":
            onchain_adjustment = -0.02
        
        # ML 信号调整
        ml_adjustment = (ml_prob - 0.5) * 0.1  # ML 概率偏离 0.5 的调整
        
        # 使用自适应权重计算最终概率
        final_prob = (llm_prob * llm_weight) + ((llm_prob + sentiment_adjustment) * sentiment_weight) + ((llm_prob + onchain_adjustment + ml_adjustment) * onchain_weight)
        final_prob = max(0, min(1, final_prob))  # 限制在 0-1

        # 8. 计算优势
        edge = final_prob - yes_price

        if edge > 0:
            direction = "Yes"
            token_id = market["yes_token"]
            order_price = yes_price
        else:
            direction = "No"
            token_id = market["no_token"]
            order_price = market["no_price"]

        # 7. 风险检查
        should_trade_flag, risk_reason = should_trade(
            market,
            confidence=sentiment_confidence,
            news_sentiment=sentiment_score,
            balance=balance
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
            "risk_check": {"should_trade": should_trade_flag, "reason": risk_reason}
        }

        # 8. 如果优势足够大，且通过风险检查，下单
        if abs(edge) >= edge_threshold and trades_made < MAX_TRADES_PER_RUN and token_id and should_trade_flag:
            # 计算仓位大小（使用流动性适配版本）
            # 内置硬上限: min(流动性调整, 余额5%, 基础仓位2倍)
            position_size = calculate_position_with_liquidity(
                balance, 
                sentiment_confidence, 
                liquidity,
                base_amount=BET_AMOUNT
            )
            
            result = place_order(token_id, "BUY", position_size, order_price)
            decision["order_result"] = result

            # 记录交易（包含 condition_id 用于去重）
            save_trade({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "mode": "DRY_RUN" if DRY_RUN else "LIVE",
                "market": title,
                "condition_id": condition_id,
                "category": category,
                "direction": direction,
                "market_price": yes_price if direction == "Yes" else market["no_price"],
                "llm_prob": llm_prob,
                "sentiment_score": sentiment_score,
                "final_prob": final_prob,
                "edge": edge,
                "amount": position_size,
                "status": result.get("status"),
                "token_id": token_id,
                "risk_reason": risk_reason,
                "end_date": market.get("end_date", ""),
                "result": "pending"  # 初始状态：待结算
            })
            trades_made += 1

        decisions.append(decision)

        # 避免 API 限流
        time.sleep(1)

    # 9. 输出结果
    output = format_output(decisions)
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
        print(f"⚠️ 风险报告生成失败: {e}")
        print(output)
    
    # 输出动态优化报告
    try:
        print(format_optimization_report())
    except Exception as e:
        print(f"⚠️ 优化报告生成失败: {e}")
        print(output)


if __name__ == "__main__":
    main()
