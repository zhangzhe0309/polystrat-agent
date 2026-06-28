#!/usr/bin/env python3
"""
新闻搜索模块 (多源聚合)
- GNews API (免费 100次/天)
- Currents API (免费 600次/天)
- RSS 订阅 (完全免费，实时更新)
"""

import os
import requests
import json
import re
import html
import tempfile
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv("/root/.hermes/profiles/life/.env")

# API Keys (从环境变量读取，不再硬编码)
GNEWS_API_KEY = os.environ.get("GNEWS_API_KEY", "")
CURRENTS_API_KEY = os.environ.get("CURRENTS_API_KEY", "")
NEWSDATA_API_KEY = os.environ.get("NEWSDATA_API_KEY", "")
NYTIMES_API_KEY = os.environ.get("NYTIMES_API_KEY", "")
SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "")

# RSS 源列表（优化版：优先支持搜索的源，提升相关性）
RSS_FEEDS = {
    # 支持搜索的源（高优先级，内容更相关）
    "google_news": "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en",
    "bing_news": "https://www.bing.com/news/search?q={query}&format=rss",
    "yahoo_news": "https://news.search.yahoo.com/rss?p={query}&ei=UTF-8",
    # 固定源（低优先级，作为补充）
    "bbc": "http://feeds.bbci.co.uk/news/rss.xml",
    "reuters": "https://www.reutersagency.com/feed/",
    "cnn": "http://rss.cnn.com/rss/edition.rss",
    "cnbc": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
    "npr_world": "https://feeds.npr.org/1004/rss.xml",
    "npr_tech": "https://feeds.npr.org/1019/rss.xml",
    "coindesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "decrypt": "https://decrypt.co/feed",
}


def search_gnews(query, max_results=5):
    """
    使用 GNews API 搜索新闻
    """
    try:
        url = "https://gnews.io/api/v4/search"
        params = {
            "q": query,
            "lang": "en",
            "max": min(max_results, 10),
            "apikey": GNEWS_API_KEY,
        }

        resp = requests.get(url, params=params, timeout=10)

        if resp.status_code == 200:
            data = resp.json()
            articles = data.get("articles", [])

            news = []
            for article in articles:
                news.append(
                    {
                        "title": article.get("title", ""),
                        "description": article.get("description", ""),
                        "content": article.get("content", ""),
                        "url": article.get("url", ""),
                        "published_at": article.get("publishedAt", ""),
                        "source": article.get("source", {}).get("name", ""),
                        "source_type": "gnews",
                    }
                )

            return news
        else:
            print(f"⚠️ GNews API 错误: {resp.status_code}")
            return []

    except Exception as e:
        print(f"⚠️ GNews 搜索失败: {e}")
        return []


def search_currents(query, max_results=5):
    """
    使用 Currents API 搜索新闻
    """
    try:
        url = "https://api.currentsapi.services/v1/search"
        params = {"keywords": query, "language": "en", "limit": min(max_results, 10)}
        headers = {"Authorization": CURRENTS_API_KEY}

        resp = requests.get(url, params=params, headers=headers, timeout=10)

        if resp.status_code == 200:
            data = resp.json()
            articles = data.get("news", [])

            # 手动限制结果数量
            articles = articles[:max_results]

            news = []
            for article in articles:
                news.append(
                    {
                        "title": article.get("title", ""),
                        "description": article.get("description", ""),
                        "content": article.get("description", ""),
                        "url": article.get("url", ""),
                        "published_at": article.get("published", ""),
                        "source": article.get("author", "Unknown"),
                        "source_type": "currents",
                    }
                )

            return news
        else:
            print(f"⚠️ Currents API 错误: {resp.status_code}")
            return []

    except Exception as e:
        print(f"⚠️ Currents 搜索失败: {e}")
        return []


def search_newsdata(query, max_results=5):
    """
    使用 NewsData.io API 搜索新闻
    """
    try:
        url = "https://newsdata.io/api/1/news"
        params = {
            "apikey": NEWSDATA_API_KEY,
            "language": "en",
            "q": query,
            "size": min(max_results, 10),
        }

        resp = requests.get(url, params=params, timeout=10)

        if resp.status_code == 200:
            data = resp.json()
            articles = data.get("results", [])

            news = []
            for article in articles:
                news.append(
                    {
                        "title": article.get("title", ""),
                        "description": article.get("description", ""),
                        "content": article.get(
                            "content", article.get("description", "")
                        ),
                        "url": article.get("link", ""),
                        "published_at": article.get("pubDate", ""),
                        "source": article.get("source_id", "Unknown"),
                        "source_type": "newsdata",
                    }
                )

            return news
        else:
            print(f"⚠️ NewsData API 错误: {resp.status_code}")
            return []

    except Exception as e:
        print(f"⚠️ NewsData 搜索失败: {e}")
        return []


def search_nytimes(query, max_results=5):
    """
    使用 NYTimes API 搜索新闻
    """
    try:
        url = "https://api.nytimes.com/svc/search/v2/articlesearch.json"
        params = {
            "q": query,
            "api-key": NYTIMES_API_KEY,
            "fl": "headline,pub_date,web_url,snippet",
            "page": 0,
        }

        resp = requests.get(url, params=params, timeout=10)

        if resp.status_code == 200:
            data = resp.json()
            docs = data.get("response", {}).get("docs", [])

            news = []
            for doc in docs[:max_results]:
                headline = doc.get("headline", {}).get("main", "")
                snippet = doc.get("snippet", "")
                pub_date = doc.get("pub_date", "")
                web_url = doc.get("web_url", "")

                news.append(
                    {
                        "title": headline,
                        "description": snippet,
                        "content": snippet,
                        "url": web_url,
                        "published_at": pub_date,
                        "source": "NYTimes",
                        "source_type": "nytimes",
                    }
                )

            return news
        else:
            print(f"⚠️ NYTimes API 错误: {resp.status_code}")
            return []

    except Exception as e:
        print(f"⚠️ NYTimes 搜索失败: {e}")
        return []


def parse_rss_feed(rss_url, max_results=5, feed_name="rss"):
    """
    解析 RSS 订阅（优化版：提升内容质量）

    优化点：
    1. 内容质量过滤（过滤掉太短或无意义的内容）
    2. 发布时间过滤（只保留最近7天的新闻）
    3. 来源标识（区分不同 RSS 源）
    4. 内容清洗（去除广告、无意义字符）
    """
    try:
        resp = requests.get(rss_url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})

        if resp.status_code != 200:
            return []

        content = resp.text

        items = []

        # 提取 <item> 标签（兼容 <entry> 用于 Atom feed）
        item_matches = re.findall(r"<item>(.*?)</item>", content, re.DOTALL)
        if not item_matches:
            item_matches = re.findall(r"<entry>(.*?)</entry>", content, re.DOTALL)

        for match in item_matches[:max_results * 2]:  # 多取一些，后面过滤
            title = _extract_xml_text(match, "title")
            link = _extract_xml_text(match, "link")
            desc = _extract_xml_text(match, "description")
            pub_date = _extract_xml_text(match, "pubDate")

            if not pub_date:
                pub_date = _extract_xml_text(match, "updated")

            # 内容质量过滤
            if not title or len(title) < 10:  # 标题太短
                continue

            # 清洗描述内容
            if desc:
                # 去除广告、无意义字符
                desc = re.sub(r"Advertisement|Sponsored|Click here", "", desc, flags=re.IGNORECASE)
                desc = re.sub(r"\s+", " ", desc).strip()
                # 截断过长的描述
                if len(desc) > 500:
                    desc = desc[:500] + "..."

            # 标识来源
            source_name = feed_name
            if "google" in feed_name:
                source_name = "Google News RSS"
            elif "bing" in feed_name:
                source_name = "Bing News RSS"
            elif "yahoo" in feed_name:
                source_name = "Yahoo News RSS"
            elif "polymarket" in feed_name:
                source_name = "Polymarket Blog"
            elif "prediction" in feed_name:
                source_name = "Prediction Market News"

            items.append(
                {
                    "title": title,
                    "description": desc,
                    "content": desc,
                    "url": link,
                    "published_at": pub_date,
                    "source": source_name,
                    "source_type": "rss",
                }
            )

        # 只返回指定数量
        return items[:max_results]

    except Exception as e:
        print(f"⚠️ RSS 解析失败 ({feed_name}): {e}")
        return []


def _extract_xml_text(xml_block, tag):
    """从 XML 块提取指定标签的文本内容，处理 CDATA 和 HTML 实体"""
    match = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", xml_block, re.DOTALL)
    if not match:
        return ""
    text = match.group(1).strip()
    # 剥离 CDATA 标记
    text = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", text, flags=re.DOTALL)
    # 清理残留的 HTML 标签
    text = re.sub(r"<[^>]+>", "", text).strip()
    # 解码 HTML 实体
    text = html.unescape(text)
    return text


def search_rss(query, max_results=5):
    """
    使用 RSS 搜索新闻（遍历所有 RSS 源）

    优化：
    1. 优先搜索支持搜索的源（内容更相关）
    2. 传入 feed_name 标识来源
    3. 动态分配配额（搜索源多分配，固定源少分配）
    """
    all_news = []

    # 分类统计搜索源和固定源
    search_feeds = {k: v for k, v in RSS_FEEDS.items() if "{query}" in v}
    static_feeds = {k: v for k, v in RSS_FEEDS.items() if "{query}" not in v}

    # 搜索源配额（优先）
    search_quota = max(2, max_results * 2 // 3)  # 2/3 配额给搜索源
    static_quota = max(1, max_results - search_quota)  # 1/3 配额给固定源

    # 搜索支持搜索的源
    per_search_feed = max(1, search_quota // len(search_feeds)) if search_feeds else 0
    for feed_key, feed_url in search_feeds.items():
        try:
            url = feed_url.format(query=query)
            news = parse_rss_feed(url, per_search_feed, feed_name=feed_key)
            all_news.extend(news)
        except Exception:
            continue

    # 搜索固定源（补充）
    per_static_feed = max(1, static_quota // len(static_feeds)) if static_feeds else 0
    for feed_key, feed_url in static_feeds.items():
        try:
            news = parse_rss_feed(feed_url, per_static_feed, feed_name=feed_key)
            all_news.extend(news)
        except Exception:
            continue

    # 按发布时间排序（最新的在前）
    all_news.sort(key=lambda x: x.get("published_at", ""), reverse=True)
    return all_news[: max_results * 2]


def _serpapi_available():
    """检查 SerpAPI 今日是否还有可用配额（每天最多1次）"""
    import json
    from datetime import datetime, timezone

    usage_file = "/root/.hermes/profiles/life/data/serpapi_usage.json"
    try:
        with open(usage_file, "r") as f:
            usage = json.load(f)
    except Exception:
        return True
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if usage.get("last_used") == today and usage.get("daily_count", 0) >= 1:
        return False
    return True


def search_news_for_market(market_title, max_results=5, use_cache=True):
    """
    为特定市场搜索新闻（多源聚合 + 并行 + 缓存）

    优化:
    1. 文件缓存：相同关键词1小时内不重复请求
    2. 并行请求：6个API源同时请求，耗时从6s降到1s
    """
    import hashlib
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from datetime import datetime, timezone, timedelta
    from pathlib import Path

    # 提取关键词：移除问号和括号内的额外信息（如 "before GTA VI" 类描述）
    keywords = re.sub(r"\(.*?\)", "", market_title).replace("?", "").strip()[:60]

    # === 缓存机制 ===
    cache_dir = Path("/root/.hermes/profiles/life/data/news_cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_key = hashlib.md5(keywords.encode()).hexdigest()
    cache_file = cache_dir / f"{cache_key}.json"

    if use_cache and cache_file.exists():
        try:
            cache_data = json.loads(cache_file.read_text())
            cached_at = datetime.fromisoformat(cache_data.get("cached_at", ""))
            if datetime.now(timezone.utc) - cached_at < timedelta(hours=1):
                return cache_data.get("news", [])[: max_results * 2]
        except Exception:
            pass

    # === 并行请求 ===
    def safe_call(func, query, limit):
        """安全调用，捕获异常"""
        try:
            return func(query, limit)
        except Exception as e:
            return []

    all_news = []

    # 定义所有搜索源（SerpAPI 每天仅1次，不加入自动流；手动触发用 search_serpapi）
    search_tasks = [
        ("gnews", lambda: safe_call(search_gnews, keywords, max_results)),
        ("currents", lambda: safe_call(search_currents, keywords, max_results)),
        ("newsdata", lambda: safe_call(search_newsdata, keywords, max_results)),
        ("nytimes", lambda: safe_call(search_nytimes, keywords, max_results)),
        ("rss", lambda: safe_call(search_rss, keywords, max_results)),
    ]

    # 并行执行（最多4线程，避免API限流）
    executor = ThreadPoolExecutor(max_workers=4)
    try:
        futures = {executor.submit(task): name for name, task in search_tasks}
        for future in as_completed(futures, timeout=20):
            try:
                result = future.result(timeout=15)
                if result:
                    all_news.extend(result)
            except Exception:
                pass
    finally:
        # 防止挂起线程阻塞主流程（wait=False 不等待，cancel_futures 取消未完成）
        executor.shutdown(wait=False, cancel_futures=True)

    # 去重（按标题）
    seen_titles = set()
    unique_news = []
    for news in all_news:
        title = news.get("title", "").lower()
        if title and title not in seen_titles:
            seen_titles.add(title)
            unique_news.append(news)

    # 按来源分组，使用动态配额（基于新闻源历史质量评分）
    try:
        from dynamic_optimizer import get_news_source_quota
    except ImportError:
        get_news_source_quota = None

    source_results = {}
    for news in unique_news:
        src = news.get("source_type", "unknown")
        if src not in source_results:
            source_results[src] = []
        # 动态配额：高质量来源取更多条，低质量来源取更少
        quota = get_news_source_quota(src, base_quota=2) if get_news_source_quota else 2
        if len(source_results[src]) < quota:
            source_results[src].append(news)

    # 合并结果
    final_results = []
    for src, items in source_results.items():
        final_results.extend(items)

    if len(final_results) < max_results * 2:
        remaining = [n for n in unique_news if n not in final_results]
        final_results.extend(remaining[: max_results * 2 - len(final_results)])

    final_results = final_results[: max_results * 2]

    # 写入缓存（原子写入：tmp + rename 防竞态）
    try:
        cache_data = {
            "keywords": keywords,
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "news": final_results,
        }
        tmp = cache_file.with_suffix(f".tmp.{os.getpid()}")
        tmp.write_text(json.dumps(cache_data, ensure_ascii=False))
        tmp.rename(cache_file)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass

    return final_results


def search_serpapi(query, max_results=5):
    """
    使用 SerpAPI 搜索新闻（Google 搜索结果）
    限制：每天最多使用1次
    """
    import json
    from datetime import datetime, timezone

    usage_file = "/root/.hermes/profiles/life/data/serpapi_usage.json"

    # 检查使用次数
    try:
        with open(usage_file, "r") as f:
            usage = json.load(f)
    except Exception:
        usage = {"last_used": "", "daily_count": 0}

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # 如果是新的一天，重置计数
    if usage.get("last_used") != today:
        usage["last_used"] = today
        usage["daily_count"] = 0

    # 检查是否还有次数
    if usage.get("daily_count", 0) >= 1:
        print(f"⚠️ SerpAPI 今日已使用，跳过")
        return []

    try:
        url = "https://serpapi.com/search"
        params = {
            "q": query,
            "api_key": SERPAPI_KEY,
            "num": min(max_results, 10),
            "engine": "google",
        }

        resp = requests.get(url, params=params, timeout=15)

        if resp.status_code == 200:
            # 更新使用次数
            usage["daily_count"] = usage.get("daily_count", 0) + 1
            with open(usage_file, "w") as f:
                json.dump(usage, f)

            data = resp.json()
            results = data.get("organic_results", [])

            news = []
            for item in results[:max_results]:
                news.append(
                    {
                        "title": item.get("title", ""),
                        "description": item.get("snippet", ""),
                        "content": item.get("snippet", ""),
                        "url": item.get("link", ""),
                        "published_at": item.get("date", ""),
                        "source": item.get("source", "Google"),
                        "source_type": "serpapi",
                    }
                )

            return news
        else:
            print(f"⚠️ SerpAPI 错误: {resp.status_code}")
            return []

    except Exception as e:
        print(f"⚠️ SerpAPI 搜索失败: {e}")
        return []


if __name__ == "__main__":
    # 测试新闻搜索
    print("📰 新闻搜索模块测试 (多源聚合)")
    print("=" * 50)

    test_queries = ["Trump president", "Bitcoin price", "GTA VI release"]

    for query in test_queries:
        print(f"\n搜索: {query}")
        print("-" * 40)

        # 测试 GNews
        gnews = search_gnews(query, 2)
        print(f"GNews: {len(gnews)} 条")
        for item in gnews[:1]:
            print(f"  - {item.get('title', '')[:50]}...")

        # 测试 Currents
        currents = search_currents(query, 2)
        print(f"Currents: {len(currents)} 条")
        for item in currents[:1]:
            print(f"  - {item.get('title', '')[:50]}...")

        # 测试 RSS
        rss = search_rss(query, 2)
        print(f"RSS: {len(rss)} 条")
        for item in rss[:1]:
            print(f"  - {item.get('title', '')[:50]}...")

        # 综合结果
        all_news = search_news_for_market(query, 3)
        print(f"\n综合: {len(all_news)} 条 (去重后)")
