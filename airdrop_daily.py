#!/usr/bin/env python3
"""
Airdrop Daily Monitor - 每日空投机会扫描
使用 requests + 公开数据源，不依赖 hermes_tools
"""

import json
import os
import sys
import re
from datetime import datetime

try:
    import requests
except ImportError:
    print("ERROR: requests 库未安装", file=sys.stderr)
    sys.exit(1)

# ============ 配置 ============
CACHE_FILE = os.path.expanduser("~/.hermes/profiles/life/home/.hermes/airdrop_daily_cache.json")

# 重点追踪项目
TRACKED_PROJECTS = {
    "Ink (Kraken L2)": {
        "status": "已发币，持续交互中",
        "action": "桥接资金 + 使用 dApps",
        "price": "$0.0012"
    },
    "LayerZero S2": {
        "status": "eligibility checker 已开放",
        "action": "检查钱包资格",
        "link": "https://layerzero.network"
    },
    "Base 链 AI 项目": {
        "status": "CHARMS (AI 角色) + BEEP (AI 交易)",
        "action": "持续交互 Base dApps",
    },
    "Solana 生态": {
        "status": "关注新协议空投",
        "action": "使用 Phantom 钱包交互新项目",
    }
}

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
}

# ============ 工具函数 ============

def load_cache():
    if not os.path.exists(CACHE_FILE):
        return {"seen": [], "last_run": None}
    try:
        with open(CACHE_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError, IOError):
        return {"seen": [], "last_run": None}

def save_cache(data):
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, "w") as f:
        json.dump(data, f, indent=2)

def search_crypto_airdrops():
    """使用 CoinGecko API 获取热门空投信息"""
    results = []
    
    # CoinGecko trending (免费 API)
    try:
        resp = requests.get(
            "https://api.coingecko.com/api/v3/search/trending",
            headers=HTTP_HEADERS,
            timeout=15
        )
        if resp.status_code == 200:
            data = resp.json()
            for coin in data.get("coins", [])[:5]:
                item = coin.get("item", {})
                results.append({
                    "title": f"🔥 热门: {item.get('name', 'Unknown')} ({item.get('symbol', '').upper()})",
                    "desc": f"市值排名 #{item.get('market_cap_rank', '?')} | 24h涨幅数据可用",
                    "url": f"https://www.coingecko.com/en/coins/{item.get('id', '')}",
                    "source": "coingecko_trending"
                })
    except Exception as e:
        print(f"CoinGecko API 错误: {e}", file=sys.stderr)
    
    # DeFiLlama 空投追踪
    try:
        resp = requests.get(
            "https://airdrops.llama.fi/overview",
            headers=HTTP_HEADERS,
            timeout=15
        )
        if resp.status_code == 200:
            # 简单解析，提取项目名
            text = resp.text
            # 匹配可能的空投项目
            airdrop_pattern = re.findall(r'"name":"([^"]+)".*?"category":"([^"]+)"', text[:5000])
            for name, category in airdrop_pattern[:3]:
                results.append({
                    "title": f"🎯 DeFiLlama 推荐: {name}",
                    "desc": f"类别: {category} | 建议检查资格",
                    "url": "https://airdrops.llama.fi",
                    "source": "defillama"
                })
    except Exception as e:
        print(f"DeFiLlama API 错误: {e}", file=sys.stderr)
    
    return results

def generate_report(search_results, cache):
    """生成最终报告"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    report = []
    report.append(f"🪙 **空投日报** | {now}")
    report.append("")
    
    # 搜索结果
    if search_results:
        report.append(f"**📊 今日发现 {len(search_results)} 个机会**")
        report.append("")
        
        seen = cache.get("seen", [])
        new_count = 0
        for i, r in enumerate(search_results[:5], 1):
            title = r["title"]
            # 标记新发现
            if title not in seen:
                new_count += 1
                marker = "🆕"
                seen.append(title)
            else:
                marker = "🔄"
            
            report.append(f"{marker} **{i}. {title}**")
            report.append(f"   {r['desc']}")
            report.append(f"   🔗 {r['url']}")
            report.append("")
        
        if new_count > 0:
            report.append(f"📢 {new_count} 个新发现!")
            report.append("")
    
    # 重点追踪项目
    report.append("**🎯 重点项目追踪**")
    report.append("")
    for project, info in TRACKED_PROJECTS.items():
        report.append(f"• **{project}**")
        report.append(f"  状态: {info['status']}")
        report.append(f"  操作: {info['action']}")
        if 'price' in info:
            report.append(f"  价格: {info['price']}")
        report.append("")
    
    # 风险提示
    report.append("---")
    report.append("⚠️ **安全提示**:")
    report.append("• 不要授权未知合约")
    report.append("• 只用官方链接")
    report.append("• 私钥/助记词绝不分享")
    
    # 更新缓存
    cache["seen"] = seen[-50:]  # 只保留最近 50 条
    cache["last_run"] = now
    save_cache(cache)
    
    return "\n".join(report)

def main():
    cache = load_cache()
    
    print("开始扫描空投机会...", file=sys.stderr)
    search_results = search_crypto_airdrops()
    print(f"搜索到 {len(search_results)} 条结果", file=sys.stderr)
    
    report = generate_report(search_results, cache)
    
    # stdout 输出会被 cron 捕获并发送
    print(report)

if __name__ == "__main__":
    main()