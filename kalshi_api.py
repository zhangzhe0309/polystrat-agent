#!/usr/bin/env python3
"""
Kalshi API 模块
- 美国合规预测市场（真实资金）
- CFTC 监管
- REST API
"""
import os
import json
import requests
from datetime import datetime, timezone
from pathlib import Path
from polystrat_logger import log, log_error

# Kalshi API 配置
KALSHI_API = "https://external-api.kalshi.com/trade-api/v2"

# 缓存目录
CACHE_DIR = Path("/root/.hermes/profiles/life/data/kalshi_cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

def get_markets(series_ticker=None, status="open", limit=20):
    """
    获取市场列表
    
    Args:
        series_ticker: 系列代码（可选）
        status: 市场状态 (open, closed, settled)
        limit: 返回数量
    
    Returns:
        list: 市场列表
    """
    try:
        params = {
            "status": status,
            "limit": limit
        }
        
        if series_ticker:
            params["series_ticker"] = series_ticker
        
        resp = requests.get(
            f"{KALSHI_API}/markets",
            params=params,
            timeout=15
        )
        
        if resp.status_code == 200:
            data = resp.json()
            markets = data.get("markets", [])
            return [format_market(m) for m in markets]
        else:
            log_error("kalshi", f"获取市场失败: {resp.status_code}")
            return []
            
    except Exception as e:
        log_error("kalshi", e, "获取市场失败")
        return []

def get_market_by_ticker(ticker):
    """
    通过代码获取市场详情
    
    Args:
        ticker: 市场代码
    
    Returns:
        dict: 市场信息
    """
    try:
        resp = requests.get(
            f"{KALSHI_API}/markets/{ticker}",
            timeout=15
        )
        
        if resp.status_code == 200:
            market = resp.json().get("market", {})
            return format_market(market)
        else:
            log_error("kalshi", f"获取市场详情失败: {resp.status_code}")
            return None
            
    except Exception as e:
        log_error("kalshi", e, f"获取市场详情失败: {ticker}")
        return None

def get_market_orderbook(ticker):
    """
    获取市场订单簿
    
    Args:
        ticker: 市场代码
    
    Returns:
        dict: 订单簿数据
    """
    try:
        resp = requests.get(
            f"{KALSHI_API}/markets/{ticker}/orderbook",
            timeout=15
        )
        
        if resp.status_code == 200:
            return resp.json().get("orderbook", {})
        else:
            log_error("kalshi", f"获取订单簿失败: {resp.status_code}")
            return {}
            
    except Exception as e:
        log_error("kalshi", e, f"获取订单簿失败: {ticker}")
        return {}

def format_market(market):
    """
    格式化市场数据
    
    Args:
        market: 原始市场数据
    
    Returns:
        dict: 格式化后的市场信息
    """
    # 提取价格（yes/no）
    yes_bid = market.get("yes_bid", 0)
    no_bid = market.get("no_bid", 0)
    
    # Kalshi 用 centicounts (1/100 of a cent)
    yes_price = yes_bid / 100 if yes_bid else 0.5
    no_price = no_bid / 100 if no_bid else 0.5
    
    # 提取流动性
    open_interest = market.get("open_interest", 0)
    
    # 提取交易量
    volume = market.get("volume", 0)
    
    # 提取时间
    close_time = market.get("close_time", "")
    if close_time:
        try:
            close_dt = datetime.fromisoformat(close_time.replace("Z", "+00:00"))
        except:
            close_dt = None
    else:
        close_dt = None
    
    return {
        "ticker": market.get("ticker", ""),
        "title": market.get("title", ""),
        "subtitle": market.get("subtitle", ""),
        "yes_price": yes_price,
        "no_price": no_price,
        "liquidity": open_interest,
        "volume": volume,
        "platform": "kalshi",
        "url": f"https://kalshi.com/markets/{market.get('ticker', '')}",
        "category": market.get("category", ""),
        "close_time": close_dt.isoformat() if close_dt else None,
        "status": market.get("status", ""),
        "result": market.get("result", None)
    }

def search_markets(query, limit=10):
    """
    搜索市场
    
    Args:
        query: 搜索关键词
        limit: 返回数量
    
    Returns:
        list: 市场列表
    """
    # Kalshi 没有直接搜索 API，获取所有市场后过滤
    all_markets = get_markets(limit=100)
    
    query_lower = query.lower()
    filtered = [
        m for m in all_markets
        if query_lower in m.get("title", "").lower()
    ]
    
    return filtered[:limit]

def get_popular_categories():
    """
    获取热门类别
    
    Returns:
        list: 类别列表
    """
    try:
        resp = requests.get(
            f"{KALSHI_API}/series",
            timeout=15
        )
        
        if resp.status_code == 200:
            data = resp.json()
            series = data.get("series", [])
            return [s.get("ticker", "") for s in series[:20]]
        else:
            log_error("kalshi", f"获取系列失败: {resp.status_code}")
            return []
            
    except Exception as e:
        log_error("kalshi", e, "获取系列失败")
        return []

if __name__ == "__main__":
    print("=" * 50)
    print("Kalshi API 测试")
    print("=" * 50)
    
    # 测试1: 获取市场
    print("\n1. 获取市场:")
    markets = get_markets(limit=5)
    print(f"   获取到 {len(markets)} 个市场")
    for m in markets[:3]:
        print(f"   - {m['title'][:50]}...")
        print(f"     Yes: {m['yes_price']:.2f}, No: {m['no_price']:.2f}")
    
    # 测试2: 搜索市场
    print("\n2. 搜索市场 (Bitcoin):")
    results = search_markets("Bitcoin", limit=3)
    print(f"   找到 {len(results)} 个市场")
    for m in results[:2]:
        print(f"   - {m['title'][:50]}...")
    
    # 测试3: 获取热门类别
    print("\n3. 获取热门类别:")
    categories = get_popular_categories()
    print(f"   获取到 {len(categories)} 个类别")
    for c in categories[:5]:
        print(f"   - {c}")
    
    print("\n✅ Kalshi API 测试完成")
