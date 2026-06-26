#!/usr/bin/env python3
"""
跨平台套利模块
- 比较 Polymarket, Manifold, Kalshi 价格
- 检测套利机会
- 计算潜在利润
"""
import os
import json
import requests
from datetime import datetime, timezone
from pathlib import Path
from polystrat_logger import log, log_error

# 导入各平台 API
from manifold_api import get_popular_markets as get_manifold_markets, search_markets as search_manifold
from polymarket_api import get_active_markets as get_polymarket_markets  # 假设已存在

# 缓存目录
CACHE_DIR = Path("/root/.hermes/profiles/life/data/arbitrage_cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

def normalize_title(title):
    """
    标准化标题用于比较
    
    Args:
        title: 原始标题
    
    Returns:
        str: 标准化后的标题
    """
    import re
    
    # 转换为小写
    title = title.lower()
    
    # 移除标点符号
    title = re.sub(r'[^\w\s]', '', title)
    
    # 移除多余空格
    title = re.sub(r'\s+', ' ', title).strip()
    
    return title

def calculate_similarity(title1, title2):
    """
    计算两个标题的相似度
    
    Args:
        title1: 标题1
        title2: 标题2
    
    Returns:
        float: 相似度 (0-1)
    """
    # 标准化
    t1 = normalize_title(title1)
    t2 = normalize_title(title2)
    
    # 分词
    words1 = set(t1.split())
    words2 = set(t2.split())
    
    # 计算 Jaccard 相似度
    intersection = words1.intersection(words2)
    union = words1.union(words2)
    
    if not union:
        return 0.0
    
    return len(intersection) / len(union)

def find_arbitrage_opportunities(threshold=0.05, min_similarity=0.5):
    """
    查找跨平台套利机会
    
    Args:
        threshold: 价差阈值 (5%)
        min_similarity: 最小相似度
    
    Returns:
        list: 套利机会列表
    """
    opportunities = []
    
    try:
        # 获取各平台市场
        manifold_markets = get_manifold_markets(limit=50)
        
        # TODO: 获取 Polymarket 和 Kalshi 市场
        # polymarket_markets = get_polymarket_markets(limit=50)
        # kalshi_markets = get_kalshi_markets(limit=50)
        
        # 暂时只比较 Manifold 内部的市场
        # 后续添加跨平台比较
        
        # 比较 Manifold 市场之间的价差
        for i, m1 in enumerate(manifold_markets):
            for j, m2 in enumerate(manifold_markets):
                if i >= j:
                    continue
                
                # 计算相似度
                similarity = calculate_similarity(m1["title"], m2["title"])
                
                if similarity >= min_similarity:
                    # 计算价差
                    price_diff = abs(m1["probability"] - m2["probability"])
                    
                    if price_diff >= threshold:
                        opportunities.append({
                            "market1": m1,
                            "market2": m2,
                            "similarity": similarity,
                            "price_diff": price_diff,
                            "potential_profit": price_diff * 100,  # 假设 $100 投入
                            "platform1": m1.get("platform", "manifold"),
                            "platform2": m2.get("platform", "manifold")
                        })
        
        # 按价差排序
        opportunities.sort(key=lambda x: x["price_diff"], reverse=True)
        
        return opportunities
        
    except Exception as e:
        log_error("arbitrage", e, "查找套利机会失败")
        return []

def format_opportunity(opp):
    """
    格式化套利机会
    
    Args:
        opp: 套利机会
    
    Returns:
        str: 格式化后的字符串
    """
    m1 = opp["market1"]
    m2 = opp["market2"]
    
    return f"""
套利机会:
  市场1: {m1["title"][:50]}...
    平台: {opp["platform1"]}
    概率: {m1["probability"]:.1%}
  
  市场2: {m2["title"][:50]}...
    平台: {opp["platform2"]}
    概率: {m2["probability"]:.1%}
  
  相似度: {opp["similarity"]:.1%}
  价差: {opp["price_diff"]:.1%}
  潜在利润: ${opp["potential_profit"]:.2f} (假设 $100 投入)
"""

def get_arbitrage_report():
    """
    获取套利报告
    
    Returns:
        str: 报告内容
    """
    opportunities = find_arbitrage_opportunities()
    
    if not opportunities:
        return "未发现套利机会"
    
    lines = []
    lines.append("📊 跨平台套利报告")
    lines.append("=" * 50)
    lines.append(f"发现 {len(opportunities)} 个套利机会")
    lines.append("")
    
    for i, opp in enumerate(opportunities[:5], 1):
        lines.append(f"机会 {i}:")
        lines.append(format_opportunity(opp))
    
    return "\n".join(lines)

if __name__ == "__main__":
    print("=" * 50)
    print("跨平台套利测试")
    print("=" * 50)
    
    # 测试: 查找套利机会
    print("\n查找套利机会:")
    report = get_arbitrage_report()
    print(report)
    
    print("\n✅ 套利测试完成")
