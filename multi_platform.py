#!/usr/bin/env python3
"""
多平台支持模块
- Polymarket (当前)
- Azuro (扩展)
- 跨平台价格比较
- 套利机会发现
"""
import requests
import json
from datetime import datetime, timezone

# 平台配置
PLATFORMS = {
    "polymarket": {
        "name": "Polymarket",
        "api_base": "https://gamma-api.polymarket.com",
        "chain": "Polygon",
        "fees": 0.02,  # 2%
        "enabled": True
    },
    "azuro": {
        "name": "Azuro",
        "api_base": "https://api.azuro.org",
        "chain": "Polygon/Gnosis",
        "fees": 0.01,  # 1%
        "enabled": False  # API 暂不可用
    }
}

def fetch_polymarket_markets(limit=10):
    """
    获取 Polymarket 市场
    """
    try:
        url = f"{PLATFORMS['polymarket']['api_base']}/markets"
        params = {
            "closed": "false",
            "limit": limit,
            "active": "true"
        }
        
        resp = requests.get(url, params=params, timeout=10)
        
        if resp.status_code == 200:
            markets = resp.json()
            
            result = []
            for market in markets:
                prices = market.get("outcomePrices", "[]")
                try:
                    price_list = json.loads(prices) if isinstance(prices, str) else prices
                    yes_price = float(price_list[0]) if price_list else 0.5
                except (json.JSONDecodeError, ValueError, TypeError) as e:
                    print(f"⚠️ Polymarket价格解析失败: {e}")
                    yes_price = 0.5
                
                result.append({
                    "platform": "polymarket",
                    "title": market.get("question", ""),
                    "yes_price": yes_price,
                    "no_price": 1 - yes_price,
                    "liquidity": float(market.get("liquidityNum", 0)),
                    "volume": float(market.get("volume", 0)),
                    "condition_id": market.get("conditionId", ""),
                    "slug": market.get("slug", "")
                })
            
            return result
        else:
            print(f"⚠️ Polymarket API 错误: {resp.status_code}")
            return []
            
    except Exception as e:
        print(f"⚠️ Polymarket 获取失败: {e}")
        return []

def fetch_azuro_markets(limit=10):
    """
    获取 Azuro 市场
    """
    try:
        # Azuro API (简化版)
        url = "https://api.azuro.org/v1/markets"
        params = {
            "limit": limit,
            "status": "active"
        }
        
        resp = requests.get(url, params=params, timeout=10)
        
        if resp.status_code == 200:
            markets = resp.json()
            
            result = []
            for market in markets:
                result.append({
                    "platform": "azuro",
                    "title": market.get("title", ""),
                    "yes_price": float(market.get("yes_price", 0.5)),
                    "no_price": float(market.get("no_price", 0.5)),
                    "liquidity": float(market.get("liquidity", 0)),
                    "volume": float(market.get("volume", 0)),
                    "condition_id": market.get("id", ""),
                    "slug": market.get("slug", "")
                })
            
            return result
        else:
            print(f"⚠️ Azuro API 错误: {resp.status_code}")
            return []
            
    except Exception as e:
        print(f"⚠️ Azuro 获取失败: {e}")
        return []

def fetch_all_markets(limit_per_platform=10):
    """
    获取所有平台市场
    """
    all_markets = []
    
    # Polymarket
    if PLATFORMS["polymarket"]["enabled"]:
        polymarket = fetch_polymarket_markets(limit_per_platform)
        all_markets.extend(polymarket)
    
    # Azuro
    if PLATFORMS["azuro"]["enabled"]:
        azuro = fetch_azuro_markets(limit_per_platform)
        all_markets.extend(azuro)
    
    return all_markets

def find_arbitrage_opportunities(markets, threshold=0.05):
    """
    发现套利机会
    
    Args:
        markets: 市场列表
        threshold: 价差阈值 (5%)
    
    Returns:
        list: 套利机会列表
    """
    # 按标题分组
    market_groups = {}
    for market in markets:
        title = market.get("title", "").lower()
        if title not in market_groups:
            market_groups[title] = []
        market_groups[title].append(market)
    
    # 查找套利机会
    arbitrage_opportunities = []
    
    for title, group in market_groups.items():
        if len(group) < 2:
            continue
        
        # 比较不同平台的价格
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                market_a = group[i]
                market_b = group[j]
                
                # 计算价差
                yes_diff = abs(market_a["yes_price"] - market_b["yes_price"])
                no_diff = abs(market_a["no_price"] - market_b["no_price"])
                
                # 如果价差超过阈值
                if yes_diff > threshold or no_diff > threshold:
                    # 确定套利方向
                    if market_a["yes_price"] < market_b["yes_price"]:
                        buy_platform = market_a["platform"]
                        sell_platform = market_b["platform"]
                        buy_price = market_a["yes_price"]
                        sell_price = market_b["yes_price"]
                    else:
                        buy_platform = market_b["platform"]
                        sell_platform = market_a["platform"]
                        buy_price = market_b["yes_price"]
                        sell_price = market_a["yes_price"]
                    
                    profit = sell_price - buy_price
                    
                    arbitrage_opportunities.append({
                        "title": title[:50],
                        "buy_platform": buy_platform,
                        "sell_platform": sell_platform,
                        "buy_price": buy_price,
                        "sell_price": sell_price,
                        "profit": profit,
                        "profit_pct": profit / buy_price * 100,
                        "market_a": market_a,
                        "market_b": market_b
                    })
    
    # 按利润率排序
    arbitrage_opportunities.sort(key=lambda x: -x["profit_pct"])
    
    return arbitrage_opportunities

def get_platform_stats():
    """
    获取平台统计
    """
    stats = {}
    
    for platform_key, platform_config in PLATFORMS.items():
        if platform_config["enabled"]:
            if platform_key == "polymarket":
                markets = fetch_polymarket_markets(20)
            elif platform_key == "azuro":
                markets = fetch_azuro_markets(20)
            else:
                markets = []
            
            stats[platform_key] = {
                "name": platform_config["name"],
                "markets_count": len(markets),
                "total_liquidity": sum(m.get("liquidity", 0) for m in markets),
                "total_volume": sum(m.get("volume", 0) for m in markets),
                "fees": platform_config["fees"]
            }
    
    return stats

def get_multiplatform_signal(title):
    """
    获取多平台信号
    
    Args:
        title: 市场标题
    
    Returns:
        dict: 多平台信号
    """
    # 获取所有平台市场
    all_markets = fetch_all_markets(20)
    
    # 查找匹配的市场
    matching_markets = []
    for market in all_markets:
        if title.lower() in market.get("title", "").lower() or market.get("title", "").lower() in title.lower():
            matching_markets.append(market)
    
    if not matching_markets:
        return {
            "found": False,
            "platforms": [],
            "recommendation": "市场未找到"
        }
    
    # 分析价格
    prices = [m["yes_price"] for m in matching_markets]
    avg_price = sum(prices) / len(prices)
    price_std = (sum((p - avg_price) ** 2 for p in prices) / len(prices)) ** 0.5
    
    # 查找套利机会
    arbitrage = find_arbitrage_opportunities(matching_markets, threshold=0.03)
    
    return {
        "found": True,
        "platforms": [m["platform"] for m in matching_markets],
        "prices": {m["platform"]: m["yes_price"] for m in matching_markets},
        "avg_price": avg_price,
        "price_std": price_std,
        "arbitrage_count": len(arbitrage),
        "arbitrage_opportunities": arbitrage[:3],  # 最多3个
        "recommendation": "套利机会" if arbitrage else "无套利机会"
    }

if __name__ == "__main__":
    # 测试多平台支持
    print("🌐 多平台支持模块测试")
    print("=" * 50)
    
    # 获取平台统计
    print("\n1. 平台统计:")
    stats = get_platform_stats()
    for platform, stat in stats.items():
        print(f"   {stat['name']}: {stat['markets_count']} 个市场")
    
    # 获取所有市场
    print("\n2. 市场数据:")
    all_markets = fetch_all_markets(5)
    print(f"   总计: {len(all_markets)} 个市场")
    for market in all_markets[:3]:
        print(f"   - [{market['platform']}] {market['title'][:40]}... | Yes: {market['yes_price']:.2f}")
    
    # 查找套利机会
    print("\n3. 套利机会:")
    arbitrage = find_arbitrage_opportunities(all_markets, threshold=0.03)
    print(f"   找到 {len(arbitrage)} 个套利机会")
    for opp in arbitrage[:2]:
        print(f"   - {opp['title'][:30]}...")
        print(f"     买入: {opp['buy_platform']} @ {opp['buy_price']:.2f}")
        print(f"     卖出: {opp['sell_platform']} @ {opp['sell_price']:.2f}")
        print(f"     利润: {opp['profit_pct']:.1f}%")
    
    # 测试多平台信号
    print("\n4. 多平台信号测试:")
    signal = get_multiplatform_signal("Trump president")
    print(f"   市场找到: {signal['found']}")
    if signal['found']:
        print(f"   平台: {', '.join(signal['platforms'])}")
        print(f"   价格: {signal['prices']}")
        print(f"   套利机会: {signal['arbitrage_count']}")
