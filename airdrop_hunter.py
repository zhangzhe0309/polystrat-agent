#!/usr/bin/env python3
"""
空投猎手模块
- 检测新链/新项目
- 监控空投机会
- 自动交互建议
"""
import os
import json
import requests
from datetime import datetime, timezone
from pathlib import Path
from polystrat_logger import log, log_error

# 缓存目录
from config_center import AIRDROP_CACHE_DIR as CACHE_DIR
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 已知空投数据源（只使用可用的公开 API）
AIRDROP_SOURCES = {
    "defillama": "https://api.llama.fi/protocols",
}

def get_latest_airdrops():
    """
    获取最新空投信息
    
    Returns:
        list: 空投列表
    """
    airdrops = []
    
    # 从多个来源获取
    airdrops.extend(get_airdrops_from_defillama())
    
    # 去重
    seen = set()
    unique_airdrops = []
    for a in airdrops:
        key = a.get("name", "").lower()
        if key not in seen:
            seen.add(key)
            unique_airdrops.append(a)
    
    return unique_airdrops

def get_airdrops_from_defillama():
    """
    从 DeFiLlama 获取新协议（可能有空投）
    
    Returns:
        list: 协议列表
    """
    try:
        resp = requests.get(
            "https://api.llama.fi/protocols",
            timeout=15
        )
        
        if resp.status_code == 200:
            protocols = resp.json()
            
            # 筛选可能有空投的协议
            # 特征：新上线、有融资、无代币
            potential_airdrops = []
            
            for p in protocols[:100]:  # 只看前100个
                name = p.get("name", "")
                chain = p.get("chain", "")
                category = p.get("category", "")
                tvl = p.get("tvl", 0)
                mcap = p.get("mcap", 0)
                
                # 没有市值 = 可能没有代币
                if mcap == 0 and tvl > 1000000:  # TVL > 1M
                    potential_airdrops.append({
                        "name": name,
                        "chain": chain,
                        "category": category,
                        "tvl": tvl,
                        "mcap": mcap,
                        "source": "defillama",
                        "url": f"https://defillama.com/protocol/{p.get('slug', '')}",
                        "potential": "high" if tvl > 10000000 else "medium"
                    })
            
            return potential_airdrops
        else:
            log_error("airdrop", f"DeFiLlama API 错误: {resp.status_code}")
            return []
            
    except Exception as e:
        log_error("airdrop", e, "获取 DeFiLlama 数据失败")
        return []

def get_new_chains():
    """
    获取新链信息
    
    Returns:
        list: 新链列表
    """
    try:
        resp = requests.get(
            "https://api.llama.fi/v2/chains",
            timeout=15
        )
        
        if resp.status_code == 200:
            chains = resp.json()
            
            # 筛选新链（TVL增长快）
            new_chains = []
            for c in chains:
                name = c.get("name", "")
                tvl = c.get("tvl", 0)
                
                # 只关注有一定TVL的链
                if tvl > 10000000:  # TVL > 10M
                    new_chains.append({
                        "name": name,
                        "tvl": tvl,
                        "token_symbol": c.get("tokenSymbol", ""),
                        "gecko_id": c.get("gecko_id", ""),
                    })
            
            # 按 TVL 排序
            new_chains.sort(key=lambda x: x["tvl"], reverse=True)
            
            return new_chains[:20]
        else:
            log_error("airdrop", f"获取链数据失败: {resp.status_code}")
            return []
            
    except Exception as e:
        log_error("airdrop", e, "获取链数据失败")
        return []

def format_airdrop_report(airdrops):
    """
    格式化空投报告
    
    Args:
        airdrops: 空投列表
    
    Returns:
        str: 报告内容
    """
    if not airdrops:
        return "未发现空投机会"
    
    lines = []
    lines.append("🪙 空投猎手报告")
    lines.append("=" * 50)
    lines.append(f"发现 {len(airdrops)} 个潜在空投机会")
    lines.append("")
    
    # 按潜力排序
    high_potential = [a for a in airdrops if a.get("potential") == "high"]
    medium_potential = [a for a in airdrops if a.get("potential") == "medium"]
    
    if high_potential:
        lines.append("🔥 高潜力:")
        for a in high_potential[:5]:
            lines.append(f"  - {a['name']} ({a['chain']})")
            lines.append(f"    TVL: ${a['tvl']:,.0f}")
            lines.append(f"    类别: {a['category']}")
            lines.append(f"    链接: {a['url']}")
            lines.append("")
    
    if medium_potential:
        lines.append("⭐ 中等潜力:")
        for a in medium_potential[:5]:
            lines.append(f"  - {a['name']} ({a['chain']})")
            lines.append(f"    TVL: ${a['tvl']:,.0f}")
            lines.append("")
    
    return "\n".join(lines)

def format_chains_report(chains):
    """
    格式化新链报告
    
    Args:
        chains: 新链列表
    
    Returns:
        str: 报告内容
    """
    if not chains:
        return "未发现新链"
    
    lines = []
    lines.append("⛓️ 新链监控报告")
    lines.append("=" * 50)
    lines.append(f"监控 {len(chains)} 条链")
    lines.append("")
    
    for c in chains[:10]:
        lines.append(f"  - {c['name']}")
        lines.append(f"    TVL: ${c['tvl']:,.0f}")
        if c['token_symbol']:
            lines.append(f"    代币: {c['token_symbol']}")
        lines.append("")
    
    return "\n".join(lines)

if __name__ == "__main__":
    print("=" * 50)
    print("空投猎手测试")
    print("=" * 50)
    
    # 测试1: 获取潜在空投
    print("\n1. 获取潜在空投:")
    airdrops = get_latest_airdrops()
    print(f"   发现 {len(airdrops)} 个潜在空投")
    print(format_airdrop_report(airdrops))
    
    # 测试2: 获取新链
    print("\n2. 获取新链:")
    chains = get_new_chains()
    print(f"   发现 {len(chains)} 条链")
    print(format_chains_report(chains[:5]))
    
    print("\n✅ 空投猎手测试完成")
