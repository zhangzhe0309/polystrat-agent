#!/usr/bin/env python3
"""
巨鲸新开仓监控 - no_agent mode
- 监控 RN1 钱包的新交易（每 2 小时）
- 即时推送通知，供用户参考决策
- 不下注，纯通知
"""

import os
import json
import sys
import requests
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

# 不需要加载 .env（无 API key 要求）

# ============ 配置区 ============
WALLET_ADDRESSES = [
    "0x2005d16a84ceefa912d4e380cd32e7ff827875ea",  # RN1 (体育量化, $7M+ PnL)
]
MONITOR_WINDOW_HOURS = 2  # 监控过去 2 小时
DATA_API = "https://data-api.polymarket.com"
SEEN_FILE = "/root/.hermes/profiles/life/home/.hermes/whale_watch/seen_trades.json"

# 中文翻译（简化版）
TEAM_CN = {
    "Argentina": "阿根廷", "Brazil": "巴西", "France": "法国", "Germany": "德国",
    "Spain": "西班牙", "England": "英格兰", "Portugal": "葡萄牙", "Netherlands": "荷兰",
    "USA": "美国", "Japan": "日本", "South Korea": "韩国",
    "New York Yankees": "洋基", "Boston Red Sox": "红袜",
    "Los Angeles Dodgers": "道奇", "Atlanta Braves": "勇士",
}

def translate_title(title):
    t = title
    t = t.replace("Will ", "").replace(" end in a draw?", " 平局?")
    t = t.replace("win on", "获胜于").replace("win the", "赢得")
    t = t.replace("Exact Score:", "比分:").replace("Spread:", "让分:")
    t = t.replace("O/U", "大小").replace("FIFA World Cup", "世界杯")
    for en, cn in sorted(TEAM_CN.items(), key=lambda x: -len(x[0])):
        t = t.replace(en, cn)
    return t.strip()

# ============ 工具函数 ============

def load_seen():
    """加载已通知的交易"""
    if not os.path.exists(SEEN_FILE):
        return {}
    try:
        with open(SEEN_FILE) as f:
            data = json.load(f)
        # 删除 12 小时前的记录
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=12)).isoformat()
        return {k: v for k, v in data.items() if v.get("ts", "") > cutoff}
    except:
        return {}

def save_seen(data):
    os.makedirs(os.path.dirname(SEEN_FILE), exist_ok=True)
    with open(SEEN_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_recent_buys(address, cutoff_time):
    """获取钱包近期买入交易"""
    params = {
        "limit": 50, "offset": 0,
        "sortBy": "TIMESTAMP", "sortOrder": "DESC",
        "user": address,
        "startDateMin": cutoff_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    try:
        resp = requests.get(f"{DATA_API}/activity", params=params, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        
        results = []
        if isinstance(data, list):
            for a in data:
                if a.get('type') != 'TRADE' or a.get('side') != 'BUY':
                    continue
                ts = a.get('timestamp', 0)
                if isinstance(ts, (int, float)):
                    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                else:
                    try:
                        dt = datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
                    except:
                        continue
                if dt < cutoff_time:
                    continue
                results.append({
                    'asset': a.get('asset', ''),
                    'size': float(a.get('size', 0)),
                    'price': float(a.get('price', 0)),
                    'outcomeIndex': int(a.get('outcomeIndex', 0)),
                    'timestamp': dt,
                    'title': a.get('title', 'Unknown'),
                    'slug': a.get('slug', ''),
                })
        return results
    except Exception as e:
        print(f"API 错误：{e}", file=sys.stderr)
        return []

# ============ 主逻辑 ============

def main():
    cutoff = datetime.now(timezone.utc) - timedelta(hours=MONITOR_WINDOW_HOURS)
    seen = load_seen()
    new_trades = []
    
    for address in WALLET_ADDRESSES:
        trades = get_recent_buys(address, cutoff)
        for bet in trades:
            key = f"{bet['title']}|{bet['outcomeIndex']}|{bet['asset'][:20]}"
            if key in seen:
                continue
            seen[key] = {"ts": datetime.now(timezone.utc).isoformat(), "addr": address[:10]}
            new_trades.append((address, bet))
    
    save_seen(seen)
    
    if not new_trades:
        print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}] 无新交易，静默")
        sys.exit(0)
    
    # 生成通知
    lines = ["🐋 RN1 巨鲸新开仓监控"]
    lines.append(f"检测窗口：过去{MONITOR_WINDOW_HOURS}小时")
    lines.append(f"新交易：{len(new_trades)} 笔")
    lines.append("")
    
    for address, bet in new_trades:
        slug = bet.get('slug', '')
        link = f"https://polymarket.com/event/{slug}?be={address}" if slug else "N/A"
        
        outcome = "Yes" if bet['outcomeIndex'] == 0 else "No"
        confidence = "✅" if bet['price'] > 0.5 else "⚠️"
        
        lines.append(f"{confidence} {translate_title(bet['title'])}")
        lines.append(f"   方向：{outcome} @ {bet['price']*100:.0f}¢")
        lines.append(f"   巨鲸下注：${bet['size']:,.2f}")
        lines.append(f"   时间：{bet['timestamp'].strftime('%H:%M')} UTC")
        lines.append(f"   🔗 {link}")
        lines.append("")
    
    # 输出
    print("\n".join(lines))

if __name__ == "__main__":
    main()