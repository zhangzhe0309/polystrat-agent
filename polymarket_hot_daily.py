#!/usr/bin/env python3
"""
Polymarket 热门市场日报 - no_agent mode
- 搜索热门 Polymarket 市场（政治、体育、加密）
- 提供简要分析和价格
- 每日 20 点推送
"""

import json
import os
import sys
import re
from datetime import datetime, timezone

try:
    from hermes_tools import web_search
except ImportError:
    print("ERROR: 无法导入 hermes_tools", file=sys.stderr)
    sys.exit(1)

# ============ 配置区 ============
# 热门类别
CATEGORIES = {
    "politics": ["election", "president", "trump", "biden", "reelection", "首相", "总统选举"],
    "sports": ["super bowl", "world cup", "nba", "nfl", "fifa", "世界杯", "欧冠", "奥运会"],
    "crypto": ["bitcoin", "ethereum", "solana", "btc", "eth", "价格突破", "ETF"],
}
# 热门关键词
HOT_KEYWORDS = ["热门", "trending", "大额", "巨鲸", "追踪", "关注度高", "成交额"]
DATA_FILE = os.path.expanduser("~/.hermes/profiles/life/home/.hermes/polymarket_hot_cache.json")

# ============ 工具函数 ============

def load_cache():
    if not os.path.exists(DATA_FILE):
        return {"seen": [], "last_run": None}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"seen": [], "last_run": None}

def save_cache(data):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def fetch_hot_markets():
    """搜索热门 Polymarket 市场"""
    markets = []
    
    # 搜索每个类别
    for cat, keywords in CATEGORIES.items():
        for kw in keywords[:2]:  # 每类取前2个关键词避免太多请求
            query = f'polymarket "{kw}" site:polymarket.com'
            try:
                results = web_search(query=query, limit=5)
                items = results.get("data", {}).get("web", [])
                
                for item in items:
                    title = item.get("title", "").lower()
                    desc = item.get("description", "").lower()
                    url = item.get("url", "")
                    
                    # 过滤掉非市场页面（如关于、博客等）
                    if any(x in url for x in ['/blog', '/about', '/help', '/careers']):
                        continue
                    
                    # 提取市场问题
                    question = extract_question(title, desc)
                    if not question:
                        continue
                    
                    # 计算热度分数
                    score = 0
                    notes = []
                    
                    # 检查是否是热门话题
                    if any(hk in title or hk in desc for hk in HOT_KEYWORDS):
                        score += 2
                        notes.append("被标记为热门")
                    
                    # 检查类别相关性
                    if cat == "politics":
                        score += 1
                        notes.append("政治市场")
                    elif cat == "sports":
                        score += 1
                        notes.append("体育市场")
                    elif cat == "crypto":
                        score += 1
                        notes.append("加密市场")
                    
                    # 检查时间敏感性（临近事件）
                    if any(word in desc for word in ["今天", "明日", "今晚", "明天", "今晚", "24小时"]):
                        score += 2
                        notes.append("临近事件")
                    
                    # 检查是否有价格信息
                    price_match = re.search(r'(\d{1,3})%', title + " " + desc)
                    if price_match:
                        score += 1
                        notes.append(f"显示价格: {price_match.group(1)}%")
                    
                    if score >= 2:  # 阈值
                        markets.append({
                            "question": question,
                            "category": cat,
                            "url": url,
                            "score": score,
                            "notes": "; ".join(notes),
                            "title": item.get("title", "")[:100],
                            "desc": item.get("description", "")[:200]
                        })
                        
            except Exception as e:
                print(f"搜索 {cat}->{kw} 失败：{e}", file=sys.stderr)
                continue
    
    # 去重（按问题）
    seen = set()
    unique_markets = []
    for m in markets:
        if m["question"] not in seen:
            seen.add(m["question"])
            unique_markets.append(m)
    
    # 按分数排序
    unique_markets.sort(key=lambda x: x["score"], reverse=True)
    return unique_markets[:5]  # 返回前5个

def extract_question(title, desc):
    """从标题/描述中提取市场问题"""
    # Polymarket 市场通常是疑问句
    # 尝试从标题中提取
    patterns = [
        r'[\"“]([^\"”]+[？?])[\"”]',  # 引号内的问句
        r'([^。！!？?]{10,}[？?])',    # 中文问句
        r'([^。.!?!]{10,}[?])',       # 英文问句
        r'Will\s+[^?]+?\?',          # Will 开头的问题
        r'Will\s+[^?]+?\s+by\s+\d{4}', # Will ... by YYYY
    ]
    
    for pattern in patterns:
        match = re.search(pattern, title + " " + desc, re.IGNORECASE)
        if match:
            q = match.group(1).strip()
            if len(q) > 10 and len(q) < 200:
                # 清理
                q = re.sub(r'\s+', ' ', q)
                return q
    
    # 如果没找到问句，返回标题作为备选
    if len(title) > 10 and len(title) < 150:
        return title.strip()
    
    return None

def format_message(markets):
    """格式化推送消息"""
    if not markets:
        return "📈 Polymarket 热门市场日报\n\n今日无热门市场线索，静默。"
    
    lines = []
    lines.append("📈 Polymarket 热门市场日报")
    lines.append(f"日期：{datetime.now(timezone.utc).strftime('%Y-%m-%d')}")
    lines.append("")
    lines.append("🔥 今日热门市场：")
    lines.append("")
    
    for i, mkt in enumerate(markets, 1):
        # 根据分数选择表情
        if mkt["score"] >= 5:
            emoji = "🟢"
        elif mkt["score"] >= 3:
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
    lines.append("数据来源：网络搜索（非实时价格）")
    lines.append("💡 提示：使用 `hermes web_extract --urls <market_url>` 获取详细信息")
    
    return "\n".join(lines)

# ============ 主逻辑 ============

def main():
    # 0. 检查上次运行时间（避免频繁运行）
    cache = load_cache()
    last_run = cache.get("last_run")
    if last_run:
        last_time = datetime.fromisoformat(last_run.replace("Z", "+00:00"))
        if (datetime.now(timezone.utc) - last_time).total_seconds() < 4 * 3600:  # 4小时内不重复
            print(f"[缓存命中] 距离上次运行不到4小时，静默")
            sys.exit(0)
    
    # 1. 搜索热门市场
    print("正在搜索热门 Polymarket 市场...")
    markets = fetch_hot_markets()
    
    if not markets:
        print("[未发现热门市场] 静默")
        # 仍然更新最后运行时间
        cache["last_run"] = datetime.now(timezone.utc).isoformat()
        save_cache(cache)
        sys.exit(0)
    
    # 2. 生成消息
    message = format_message(markets)
    
    # 3. 输出（Hermes cron 会捕获 stdout）
    print(message)
    
    # 4. 更新缓存
    cache["last_run"] = datetime.now(timezone.utc).isoformat()
    # 保存已见问题
    seen_questions = {mkt["question"] for mkt in markets}
    cache["seen"] = list(set(cache.get("seen", [])) | seen_questions)
    # 保持seen列表不超过100项
    if len(cache["seen"]) > 100:
        cache["seen"] = cache["seen"][-100:]
    save_cache(cache)

if __name__ == "__main__":
    main()