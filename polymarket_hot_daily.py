#!/usr/bin/env python3
"""
Polymarket 热门市场日报
- 实时获取 Polymarket 热门交易市场（宏观、政治、体育、加密）
- 提供简要分析、价格与成交量
"""

import json
import os
import sys
import re
from datetime import datetime, timezone
import requests

DATA_FILE = os.path.expanduser("~/.hermes/polymarket_hot_cache.json")

def load_cache():
    if not os.path.exists(DATA_FILE):
        return {"seen": [], "last_run": None}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError, IOError):
        return {"seen": [], "last_run": None}

def save_cache(data):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def fetch_hot_markets():
    """通过 Gamma API 实时抓取热门市场"""
    url = "https://gamma-api.polymarket.com/markets"
    params = {
        "closed": "false",
        "limit": 25,
        "active": "true",
        "order": "volume24hr",
        "ascending": "false"
    }
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        markets = resp.json()
    except Exception as e:
        print(f"Gamma API 请求失败: {e}", file=sys.stderr)
        return []

    results = []
    for m in markets:
        q = m.get("question", "")
        vol = float(m.get("volume24hr") or 0)
        liq = float(m.get("liquidityNum") or 0)
        slug = m.get("slug", "")
        prices = m.get("outcomePrices")
        outcomes = m.get("outcomes")

        if isinstance(prices, str):
            try: prices = json.loads(prices)
            except (ValueError, TypeError): continue
        if isinstance(outcomes, str):
            try: outcomes = json.loads(outcomes)
            except (ValueError, TypeError): continue

        ql = q.lower()
        if any(k in ql for k in ['fed', 'interest rate', 'inflation', 'recession', 'gdp', 'yield', 'treasury']):
            cat = "macro"
        elif any(k in ql for k in ['president', 'election', 'trump', 'biden', 'hegseth', 'senate', 'governor', 'war', 'israel', 'iran', 'ukraine', 'russia']):
            cat = "politics"
        elif any(k in ql for k in ['bitcoin', 'btc', 'ethereum', 'eth', 'solana', 'sol', 'crypto']):
            cat = "crypto"
        elif any(k in ql for k in ['open', 'cup', 'nba', 'nfl', 'champions', 'fc', 'vs', 'valorant', 'tournament', 'tennis']):
            cat = "sports"
        else:
            cat = "general"

        p_desc = ""
        if prices and outcomes and len(prices) >= 2:
            try:
                p_desc = f"{outcomes[0]}: {float(prices[0])*100:.1f}% | {outcomes[1]}: {float(prices[1])*100:.1f}%"
            except (ValueError, TypeError, IndexError):
                pass

        score = min(10, max(3, int(vol / 250000)))
        results.append({
            "question": q,
            "category": cat,
            "url": f"https://polymarket.com/event/{slug}" if slug else "https://polymarket.com",
            "score": score,
            "volume24hr": vol,
            "liquidity": liq,
            "notes": f"24h交易量: ${vol:,.0f} | 当前概率: {p_desc}",
            "title": f"Polymarket - {q}",
            "desc": f"24小时成交量 ${vol:,.0f}，池子流动性 ${liq:,.0f}。"
        })

    # 去重并取前5
    seen = set()
    unique = []
    for item in results:
        if item["question"] not in seen:
            seen.add(item["question"])
            unique.append(item)
    return unique[:5]

def format_message(markets):
    """格式化推送消息"""
    if not markets:
        return "📈 Polymarket 热门市场日报\n\n今日无热门市场线索，静默。"

    lines = []
    lines.append("📈 Polymarket 热门市场日报")
    lines.append(f"日期：{datetime.now(timezone.utc).strftime('%Y-%m-%d')}")
    lines.append("")
    lines.append("🔥 今日热门市场 TOP 5：")
    lines.append("")

    for i, mkt in enumerate(markets, 1):
        if mkt["score"] >= 7:
            emoji = "🟢"
        elif mkt["score"] >= 4:
            emoji = "🟡"
        else:
            emoji = "🔴"

        lines.append(f"{i}. {emoji} [{mkt['category'].upper()}] {mkt['question']}")
        lines.append(f"   热度：{mkt['score']}/10 | {mkt['notes']}")
        lines.append(f"   来源：{mkt['title']}")
        if mkt["desc"] and mkt["desc"] != mkt["title"]:
            lines.append(f"   描述：{mkt['desc']}")
        lines.append(f"   链接：{mkt['url']}")
        lines.append("")

    lines.append("💡 使用建议")
    lines.append("- 关注价格变化：>60% 表示看涨，<40% 表示看跌")
    lines.append("- 检查成交量：高成交量通常表示更准确的预测")
    lines.append("- 注意事件时间：临近事件时市场更有效")
    lines.append("")
    lines.append("数据来源：Polymarket Gamma 官方接口（实时）")

    return "\n".join(lines)

def main():
    force = "--force" in sys.argv
    cache = load_cache()
    last_run = cache.get("last_run")
    if last_run and not force:
        try:
            last_time = datetime.fromisoformat(last_run.replace("Z", "+00:00"))
            if (datetime.now(timezone.utc) - last_time).total_seconds() < 4 * 3600:
                print(f"[缓存命中] 距离上次运行不到4小时，静默")
                sys.exit(0)
        except Exception:
            pass

    markets = fetch_hot_markets()
    if not markets:
        print("[未发现热门市场] 静默")
        cache["last_run"] = datetime.now(timezone.utc).isoformat()
        save_cache(cache)
        sys.exit(0)

    message = format_message(markets)
    print(message)

    cache["last_run"] = datetime.now(timezone.utc).isoformat()
    seen_questions = {mkt["question"] for mkt in markets}
    cache["seen"] = list(set(cache.get("seen", [])) | seen_questions)
    if len(cache["seen"]) > 100:
        cache["seen"] = cache["seen"][-100:]
    save_cache(cache)

if __name__ == "__main__":
    main()
