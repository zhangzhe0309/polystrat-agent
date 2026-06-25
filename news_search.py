#!/usr/bin/env python3
"""
新闻搜索模块 (多源聚合)
- GNews API (免费 100次/天)
- Currents API (免费 600次/天)
- RSS 订阅 (完全免费，实时更新)
"""
import requests
import json
import re
from datetime import datetime

# API Keys
GNEWS_API_KEY = "757bb7eafdedf9bd79b4be14ed99d5ee"
CURRENTS_API_KEY = "s1yGNIPiAtyC_kw6uMqE-9mTwuBRojhvRyxMSLqOtPTK58B2"
NEWSDATA_API_KEY = "pub_3715a1d1099a46cd9ab05b7584ce0812"
NYTIMES_API_KEY = "oIArLoX9WQR37xL2GCuHYJJeLB9RPU44vQJveqD4HCcmK7y9"
SERPAPI_KEY = "a2764cbb3462340be68cbf72b9207aa1bcd039e82a7ff2d9776a1fe1393d8f9e"

# RSS 源列表
RSS_FEEDS = {
    "google_news": "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en",
    "bbc": "http://feeds.bbci.co.uk/news/rss.xml",
    "reuters": "https://www.reutersagency.com/feed/",
    "cnn": "http://rss.cnn.com/rss/edition.rss",
    "cnbc": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
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
            "apikey": GNEWS_API_KEY
        }
        
        resp = requests.get(url, params=params, timeout=10)
        
        if resp.status_code == 200:
            data = resp.json()
            articles = data.get("articles", [])
            
            news = []
            for article in articles:
                news.append({
                    "title": article.get("title", ""),
                    "description": article.get("description", ""),
                    "content": article.get("content", ""),
                    "url": article.get("url", ""),
                    "published_at": article.get("publishedAt", ""),
                    "source": article.get("source", {}).get("name", ""),
                    "source_type": "gnews"
                })
            
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
        params = {
            "keywords": query,
            "language": "en",
            "limit": min(max_results, 10)
        }
        headers = {
            "Authorization": CURRENTS_API_KEY
        }
        
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        
        if resp.status_code == 200:
            data = resp.json()
            articles = data.get("news", [])
            
            # 手动限制结果数量
            articles = articles[:max_results]
            
            news = []
            for article in articles:
                news.append({
                    "title": article.get("title", ""),
                    "description": article.get("description", ""),
                    "content": article.get("description", ""),
                    "url": article.get("url", ""),
                    "published_at": article.get("published", ""),
                    "source": article.get("author", "Unknown"),
                    "source_type": "currents"
                })
            
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
            "size": min(max_results, 10)
        }
        
        resp = requests.get(url, params=params, timeout=10)
        
        if resp.status_code == 200:
            data = resp.json()
            articles = data.get("results", [])
            
            news = []
            for article in articles:
                news.append({
                    "title": article.get("title", ""),
                    "description": article.get("description", ""),
                    "content": article.get("content", article.get("description", "")),
                    "url": article.get("link", ""),
                    "published_at": article.get("pubDate", ""),
                    "source": article.get("source_id", "Unknown"),
                    "source_type": "newsdata"
                })
            
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
            "page": 1
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
                
                news.append({
                    "title": headline,
                    "description": snippet,
                    "content": snippet,
                    "url": web_url,
                    "published_at": pub_date,
                    "source": "NYTimes",
                    "source_type": "nytimes"
                })
            
            return news
        else:
            print(f"⚠️ NYTimes API 错误: {resp.status_code}")
            return []
            
    except Exception as e:
        print(f"⚠️ NYTimes 搜索失败: {e}")
        return []

def parse_rss_feed(rss_url, max_results=5):
    """
    解析 RSS 订阅
    """
    try:
        resp = requests.get(rss_url, timeout=10)
        
        if resp.status_code != 200:
            return []
        
        content = resp.text
        
        # 简单的 XML 解析（不依赖外部库）
        items = []
        
        # 提取 <item> 标签
        item_pattern = r'<item>(.*?)</item>'
        matches = re.findall(item_pattern, content, re.DOTALL)
        
        for match in matches[:max_results]:
            # 提取标题
            title_match = re.search(r'<title>(.*?)</title>', match, re.DOTALL)
            title = title_match.group(1).strip() if title_match else ""
            
            # 提取链接
            link_match = re.search(r'<link>(.*?)</link>', match, re.DOTALL)
            link = link_match.group(1).strip() if link_match else ""
            
            # 提取描述
            desc_match = re.search(r'<description>(.*?)</description>', match, re.DOTALL)
            desc = desc_match.group(1).strip() if desc_match else ""
            
            # 提取发布时间
            pub_match = re.search(r'<pubDate>(.*?)</pubDate>', match, re.DOTALL)
            pub_date = pub_match.group(1).strip() if pub_match else ""
            
            # 清理 HTML 标签
            title = re.sub(r'<[^>]+>', '', title).strip()
            desc = re.sub(r'<[^>]+>', '', desc).strip()
            
            if title:
                items.append({
                    "title": title,
                    "description": desc,
                    "content": desc,
                    "url": link,
                    "published_at": pub_date,
                    "source": "RSS",
                    "source_type": "rss"
                })
        
        return items
        
    except Exception as e:
        print(f"⚠️ RSS 解析失败: {e}")
        return []

def search_rss(query, max_results=5):
    """
    使用 RSS 搜索新闻
    """
    all_news = []
    
    # 使用 Google News RSS
    rss_url = RSS_FEEDS["google_news"].format(query=query)
    news = parse_rss_feed(rss_url, max_results)
    all_news.extend(news)
    
    return all_news[:max_results]

def search_news_for_market(market_title, max_results=5):
    """
    为特定市场搜索新闻（多源聚合）
    """
    # 提取关键词（保留更多关键词）
    keywords = market_title.replace("?", "").replace("before GTA VI", "").strip()
    # 只取前60个字符
    keywords = keywords[:60]
    
    all_news = []
    
    # 1. GNews API
    gnews = search_gnews(keywords, max_results)
    all_news.extend(gnews)
    
    # 2. Currents API
    currents = search_currents(keywords, max_results)
    all_news.extend(currents)
    
    # 3. NewsData.io API
    newsdata = search_newsdata(keywords, max_results)
    all_news.extend(newsdata)
    
    # 4. NYTimes API
    nytimes = search_nytimes(keywords, max_results)
    all_news.extend(nytimes)
    
    # 5. SerpAPI
    serpapi = search_serpapi(keywords, max_results)
    all_news.extend(serpapi)
    
    # 6. RSS 订阅
    rss = search_rss(keywords, max_results)
    all_news.extend(rss)
    
    # 去重（按标题）
    seen_titles = set()
    unique_news = []
    for news in all_news:
        title = news.get("title", "").lower()
        if title and title not in seen_titles:
            seen_titles.add(title)
            unique_news.append(news)
    
    # 确保每个来源至少有结果
    # 按来源分组，每个来源取前2条
    source_results = {}
    for news in unique_news:
        src = news.get("source_type", "unknown")
        if src not in source_results:
            source_results[src] = []
        if len(source_results[src]) < 2:
            source_results[src].append(news)
    
    # 合并结果
    final_results = []
    for src, items in source_results.items():
        final_results.extend(items)
    
    # 如果还不够，补充剩余的
    if len(final_results) < max_results * 2:
        remaining = [n for n in unique_news if n not in final_results]
        final_results.extend(remaining[:max_results * 2 - len(final_results)])
    
    return final_results[:max_results * 2]

def search_news_simple(query, max_results=5):
    """
    简单的新闻搜索
    """
    return search_news_for_market(query, max_results)

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
        with open(usage_file, 'r') as f:
            usage = json.load(f)
    except:
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
            "engine": "google"
        }
        
        resp = requests.get(url, params=params, timeout=15)
        
        if resp.status_code == 200:
            # 更新使用次数
            usage["daily_count"] = usage.get("daily_count", 0) + 1
            with open(usage_file, 'w') as f:
                json.dump(usage, f)
            
            data = resp.json()
            results = data.get("organic_results", [])
            
            news = []
            for item in results[:max_results]:
                news.append({
                    "title": item.get("title", ""),
                    "description": item.get("snippet", ""),
                    "content": item.get("snippet", ""),
                    "url": item.get("link", ""),
                    "published_at": item.get("date", ""),
                    "source": item.get("source", "Google"),
                    "source_type": "serpapi"
                })
            
            return news
        else:
            print(f"⚠️ SerpAPI 错误: {resp.status_code}")
            return []
            
    except Exception as e:
        print(f"⚠️ SerpAPI 搜索失败: {e}")
        return []

    """
    简单的新闻搜索
    """
    return search_news_for_market(query, max_results)

if __name__ == "__main__":
    # 测试新闻搜索
    print("📰 新闻搜索模块测试 (多源聚合)")
    print("=" * 50)
    
    test_queries = [
        "Trump president",
        "Bitcoin price",
        "GTA VI release"
    ]
    
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
