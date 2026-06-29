#!/usr/bin/env python3
"""
Manifold Markets API 模块
- 免费预测市场（虚拟货币 mana）
- 开放 API，无需 API Key（读取）
- 可用于测试和套利分析
"""
import os
import json
import requests
from datetime import datetime, timezone
from pathlib import Path
from polystrat_logger import log, log_error
from retry_helper import retry_request

# Manifold API 配置
MANIFOLD_API = "https://api.manifold.markets/v0"
MANIFOLD_API_KEY = os.environ.get("MANIFOLD_API_KEY", "")  # 可选，用于写入操作

# 缓存目录
from config_center import MANIFOLD_CACHE_DIR as CACHE_DIR
CACHE_DIR.mkdir(parents=True, exist_ok=True)

def get_popular_markets(limit=20, sort="liquidity"):
    """
    获取热门市场
    
    Args:
        limit: 返回数量
        sort: 排序方式 (liquidity, volume, lastBetTime)
    
    Returns:
        list: 市场列表
    """
    try:
        # 使用 search-markets 端点获取活跃市场
        # 注意：Manifold API 不支持 sort/order 参数
        resp = requests.get(
            f"{MANIFOLD_API}/search-markets",
            params={
                "term": "",  # 空搜索获取所有
                "limit": limit
            },
            timeout=15
        )
        
        if resp.status_code == 200:
            markets = resp.json()
            return [format_market(m) for m in markets]
        else:
            log_error("manifold", f"API错误: {resp.status_code}")
            return []
            
    except Exception as e:
        log_error("manifold", e, "获取热门市场失败")
        return []

def search_markets(query, limit=10):
    """
    搜索市场
    
    Args:
        query: 搜索关键词
        limit: 返回数量
    
    Returns:
        list: 市场列表
    """
    try:
        # Manifold 搜索 API
        resp = requests.get(
            f"{MANIFOLD_API}/search-markets",
            params={
                "term": query,
                "limit": limit
            },
            timeout=15
        )
        
        if resp.status_code == 200:
            markets = resp.json()
            return [format_market(m) for m in markets]
        else:
            log_error("manifold", f"搜索API错误: {resp.status_code}")
            return []
            
    except Exception as e:
        log_error("manifold", e, f"搜索市场失败: {query}")
        return []

def get_market_by_id(market_id):
    """
    通过ID获取市场详情
    
    Args:
        market_id: 市场ID
    
    Returns:
        dict: 市场信息
    """
    try:
        resp = requests.get(
            f"{MANIFOLD_API}/markets/{market_id}",
            timeout=15
        )
        
        if resp.status_code == 200:
            market = resp.json()
            return format_market(market)
        else:
            log_error("manifold", f"获取市场详情失败: {resp.status_code}")
            return None
            
    except Exception as e:
        log_error("manifold", e, f"获取市场详情失败: {market_id}")
        return None

def get_market_bets(market_id, limit=50):
    """
    获取市场投注记录
    
    Args:
        market_id: 市场ID
        limit: 返回数量
    
    Returns:
        list: 投注列表
    """
    try:
        resp = requests.get(
            f"{MANIFOLD_API}/bets",
            params={
                "contractId": market_id,
                "limit": limit
            },
            timeout=15
        )
        
        if resp.status_code == 200:
            return resp.json()
        else:
            log_error("manifold", f"获取投注记录失败: {resp.status_code}")
            return []
            
    except Exception as e:
        log_error("manifold", e, f"获取投注记录失败: {market_id}")
        return []

def format_market(market):
    """
    格式化市场数据
    
    Args:
        market: 原始市场数据
    
    Returns:
        dict: 格式化后的市场信息
    """
    # 提取概率
    probability = market.get("probability", 0.5)
    
    # 提取流动性
    liquidity = market.get("liquidity", 0)
    
    # 提取交易量
    volume = market.get("volume", 0)
    
    # 提取创建时间
    created_time = market.get("createdTime", 0)
    if created_time:
        created_dt = datetime.fromtimestamp(created_time / 1000, tz=timezone.utc)
    else:
        created_dt = None
    
    # 提取关闭时间
    close_time = market.get("closeTime", 0)
    if close_time:
        close_dt = datetime.fromtimestamp(close_time / 1000, tz=timezone.utc)
    else:
        close_dt = None
    
    return {
        "id": market.get("id", ""),
        "title": market.get("question", ""),
        "description": market.get("description", "")[:200],
        "probability": probability,
        "liquidity": liquidity,
        "volume": volume,
        "platform": "manifold",
        "url": market.get("url", ""),
        "creator": market.get("creatorUsername", ""),
        "created_time": created_dt.isoformat() if created_dt else None,
        "close_time": close_dt.isoformat() if close_dt else None,
        "is_closed": market.get("isResolved", False),
        "resolution": market.get("resolution", None)
    }

def compare_with_polymarket(manifold_title, polymarket_markets):
    """
    比较 Manifold 和 Polymarket 价格
    
    Args:
        manifold_title: Manifold 市场标题
        polymarket_markets: Polymarket 市场列表
    
    Returns:
        list: 套利机会
    """
    opportunities = []
    
    # 搜索 Polymarket 中的匹配市场
    for pm in polymarket_markets:
        pm_title = pm.get("title", "").lower()
        mf_title = manifold_title.lower()
        
        # 简单匹配：检查关键词
        # TODO: 改进匹配算法
        if any(word in pm_title for word in mf_title.split()[:3]):
            manifold_prob = pm.get("manifold_prob", 0.5)
            polymarket_prob = pm.get("yes_price", 0.5)
            
            # 计算价差
            price_diff = abs(manifold_prob - polymarket_prob)
            
            if price_diff > 0.05:  # 5% 以上价差
                opportunities.append({
                    "manifold_title": manifold_title,
                    "polymarket_title": pm.get("title", ""),
                    "manifold_prob": manifold_prob,
                    "polymarket_prob": polymarket_prob,
                    "price_diff": price_diff,
                    "potential_profit": price_diff * 100  # 假设 $100 投入
                })
    
    return opportunities

def get_cross_platform_opportunities(limit=20):
    """
    获取跨平台套利机会
    
    Args:
        limit: 返回数量
    
    Returns:
        list: 套利机会列表
    """
    # TODO: 实现跨平台套利检测
    # 需要同时获取 Manifold 和 Polymarket 数据
    pass

if __name__ == "__main__":
    print("=" * 50)
    print("Manifold Markets API 测试")
    print("=" * 50)
    
    # 测试1: 获取热门市场
    print("\n1. 获取热门市场:")
    markets = get_popular_markets(limit=5)
    print(f"   获取到 {len(markets)} 个市场")
    for m in markets[:3]:
        print(f"   - {m['title'][:50]}...")
        print(f"     概率: {m['probability']:.1%}, 流动性: {m['liquidity']:.0f}")
    
    # 测试2: 搜索市场
    print("\n2. 搜索市场 (Bitcoin):")
    results = search_markets("Bitcoin", limit=3)
    print(f"   找到 {len(results)} 个市场")
    for m in results[:2]:
        print(f"   - {m['title'][:50]}...")
        print(f"     概率: {m['probability']:.1%}")
    
    print("\n✅ Manifold API 测试完成")
