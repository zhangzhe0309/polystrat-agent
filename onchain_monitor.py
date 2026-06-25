#!/usr/bin/env python3
"""
链上数据监控模块
- 监控 Polymarket 市场数据
- 分析交易量变化
- 提供市场情绪信号
"""
import requests
import json
from datetime import datetime, timezone

# Polymarket API
GAMMA_API = "https://gamma-api.polymarket.com"

def get_market_volume(market_slug):
    """
    获取市场交易量
    
    Args:
        market_slug: 市场 slug
    
    Returns:
        dict: 交易量数据
    """
    try:
        url = f"{GAMMA_API}/markets/{market_slug}"
        resp = requests.get(url, timeout=10)
        
        if resp.status_code == 200:
            market = resp.json()
            
            volume = float(market.get("volume", 0))
            liquidity = float(market.get("liquidityNum", 0))
            
            return {
                "volume": volume,
                "liquidity": liquidity,
                "volume_liquidity_ratio": volume / liquidity if liquidity > 0 else 0
            }
        else:
            return {"volume": 0, "liquidity": 0, "volume_liquidity_ratio": 0}
            
    except Exception as e:
        print(f"⚠️ 获取市场交易量失败: {e}")
        return {"volume": 0, "liquidity": 0, "volume_liquidity_ratio": 0}

def get_trending_markets(limit=10):
    """
    获取热门市场
    
    Args:
        limit: 最大结果数
    
    Returns:
        list: 热门市场列表
    """
    try:
        url = f"{GAMMA_API}/markets"
        params = {
            "closed": "false",
            "limit": limit * 2,
            "active": "true",
            "order": "volume24hr",
            "ascending": "false"
        }
        
        resp = requests.get(url, params=params, timeout=10)
        
        if resp.status_code == 200:
            markets = resp.json()
            
            trending = []
            for market in markets:
                volume = float(market.get("volume", 0))
                liquidity = float(market.get("liquidityNum", 0))
                
                # 过滤有交易量的市场
                if volume > 10000:
                    trending.append({
                        "title": market.get("question", ""),
                        "slug": market.get("slug", ""),
                        "volume": volume,
                        "liquidity": liquidity,
                        "yes_price": float(json.loads(market.get("outcomePrices", "[0.5]"))[0]) if market.get("outcomePrices") else 0.5
                    })
            
            return trending[:limit]
        else:
            print(f"⚠️ 获取热门市场失败: {resp.status_code}")
            return []
            
    except Exception as e:
        print(f"⚠️ 获取热门市场失败: {e}")
        return []

def analyze_volume_change(market_slug, hours=24):
    """
    分析交易量变化
    
    Args:
        market_slug: 市场 slug
        hours: 时间范围（小时）
    
    Returns:
        dict: 交易量变化分析
    """
    # 注意：这里返回模拟数据，实际实现需要历史数据
    # 可以通过定时任务记录数据来实现
    
    return {
        "volume_change": 0.15,  # 15% 增长
        "trend": "increasing",
        "confidence": 0.5
    }

def get_market_momentum(market_title):
    """
    获取市场动量
    
    Args:
        market_title: 市场标题
    
    Returns:
        dict: 市场动量数据
    """
    try:
        # 搜索市场
        url = f"{GAMMA_API}/markets"
        params = {
            "limit": 20,
            "active": "true"
        }
        
        resp = requests.get(url, params=params, timeout=10)
        
        if resp.status_code == 200:
            markets = resp.json()
            
            # 找到匹配的市场
            target_market = None
            for market in markets:
                question = market.get("question", "").lower()
                if market_title.lower() in question or question in market_title.lower():
                    target_market = market
                    break
            
            if target_market:
                slug = target_market.get("slug", "")
                volume_data = get_market_volume(slug)
                volume_change = analyze_volume_change(slug)
                
                # 计算动量分数
                momentum_score = 0
                if volume_data["volume_liquidity_ratio"] > 0.5:
                    momentum_score += 0.3
                if volume_change["volume_change"] > 0.1:
                    momentum_score += 0.3
                if volume_data["volume"] > 50000:
                    momentum_score += 0.2
                
                return {
                    "market_found": True,
                    "volume": volume_data["volume"],
                    "liquidity": volume_data["liquidity"],
                    "volume_change": volume_change["volume_change"],
                    "momentum_score": min(1, momentum_score),
                    "recommendation": "strong_buy" if momentum_score > 0.7 else "buy" if momentum_score > 0.5 else "hold"
                }
            
        return {"market_found": False, "volume": 0, "liquidity": 0, "momentum_score": 0, "recommendation": "hold"}
        
    except Exception as e:
        print(f"⚠️ 市场动量分析失败: {e}")
        return {"market_found": False, "volume": 0, "liquidity": 0, "momentum_score": 0, "recommendation": "hold"}

def get_onchain_signal(market_title):
    """
    获取链上信号
    
    Args:
        market_title: 市场标题
    
    Returns:
        dict: 链上信号
    """
    # 1. 获取热门市场
    trending = get_trending_markets(limit=5)
    
    # 2. 分析市场动量
    momentum = get_market_momentum(market_title)
    
    # 3. 综合信号
    signal = {
        "trending_markets": len(trending),
        "market_volume": momentum.get("volume", 0),
        "volume_change": momentum.get("volume_change", 0),
        "momentum_score": momentum.get("momentum_score", 0),
        "recommendation": momentum.get("recommendation", "hold"),
        "confidence": 0.6 if momentum.get("market_found") else 0.3
    }
    
    return signal

if __name__ == "__main__":
    # 测试链上数据监控
    print("🔗 链上数据监控模块测试")
    print("=" * 50)
    
    # 测试热门市场
    print("\n1. 热门市场:")
    trending = get_trending_markets(limit=5)
    print(f"   找到 {len(trending)} 个热门市场")
    for market in trending[:3]:
        print(f"   - {market['title'][:40]}... | 交易量: ${market['volume']:,.0f}")
    
    # 测试市场动量
    print("\n2. 市场动量分析:")
    momentum = get_market_momentum("Trump president")
    print(f"   市场找到: {momentum['market_found']}")
    print(f"   交易量: ${momentum['volume']:,.0f}")
    print(f"   动量分数: {momentum['momentum_score']:.2f}")
    print(f"   建议: {momentum['recommendation']}")
    
    # 测试链上信号
    print("\n3. 链上信号:")
    signal = get_onchain_signal("Trump president")
    print(f"   热门市场: {signal['trending_markets']} 个")
    print(f"   市场交易量: ${signal['market_volume']:,.0f}")
    print(f"   动量分数: {signal['momentum_score']:.2f}")
    print(f"   建议: {signal['recommendation']}")
    print(f"   置信度: {signal['confidence']:.2f}")
