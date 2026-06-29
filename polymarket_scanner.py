#!/usr/bin/env python3
"""
Polymarket 市场扫描器 v3 (final)
=================================
使用 Gamma API 获取涨跌市场 + 价格数据。
零成本 · 无需API Key · 纯学习模式
"""
import json, os, sys, time
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

GAMMA = "https://gamma-api.polymarket.com"

def _get(url, retries=2):
    req = Request(url, headers={"Accept":"application/json","User-Agent":"PMScanner/3.0"})
    for i in range(retries):
        try:
            with urlopen(req, timeout=12) as r:
                return json.loads(r.read().decode())
        except HTTPError as e:
            if e.code == 429:
                time.sleep(1); continue
            return None
        except (URLError, socket.timeout) as e:
            print(f"⚠️ API请求失败: {e}")
            return None
    return None

def scan():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    out = []
    
    # 1. 获取加密涨跌事件（用"Up or Down"标签过滤）
    out.append(f"📊 Polymarket 市场扫描 — {now}")
    out.append("=" * 56)
    
    # 获取所有活跃的 Up or Down 事件
    all_crypto = _get(f"{GAMMA}/events?closed=false&limit=100&tag=crypto&order=volume24hr")
    updown_events = []
    if all_crypto and isinstance(all_crypto, list):
        for ev in all_crypto:
            title = ev.get("title","")
            if "up" in title.lower() and "down" in title.lower():
                for coin in ["bitcoin","btc","ethereum","eth","solana","sol","doge","dogecoin","xrp","bnb","hyperliquid"]:
                    if coin in title.lower():
                        updown_events.append(ev)
                        break
    
    out.append(f"\n🪙 加密涨跌市场 ({len(updown_events)}个活跃事件)")
    out.append("-" * 56)
    
    for ev in updown_events:
        title = ev.get("title","?")
        vol24h = float(ev.get("volume24hr",0) or 0)
        slug = ev.get("slug","")
        mkts = ev.get("markets",[]) or []
        
        # 取第一个市场的价格
        prices_str = ""
        if mkts:
            m0 = mkts[0]
            raw_prices = m0.get("outcomePrices","[]")
            try:
                pp = json.loads(raw_prices) if isinstance(raw_prices, str) else raw_prices
                if pp and len(pp) >= 2:
                    yes_p = float(pp[0]) * 100
                    no_p = float(pp[1]) * 100
                    # 如果都是50/50就没实际交易
                    if abs(yes_p - 50) < 0.1:
                        prices_str = "⏳ 待开盘"
                    else:
                        prices_str = f"YES ${yes_p:.0f}¢ / NO ${no_p:.0f}¢"
            except (json.JSONDecodeError, ValueError, IndexError, TypeError):
                prices_str = ""
        
        v_str = f" | 24hVol: ${vol24h:,.0f}" if vol24h > 0 else ""
        mkt_count = len(mkts)
        out.append(f"  • {title[:55]}{v_str}")
        out.append(f"    市场数: {mkt_count} | {prices_str}")
    
    # 2. 热门市场
    hot_mkts = _get(f"{GAMMA}/markets?closed=false&limit=30&order=volume")
    if hot_mkts and isinstance(hot_mkts, list):
        out.append(f"\n🔥 热门市场 Top15")
        out.append("-" * 56)
        for m in hot_mkts[:15]:
            q = m.get("question","?")
            raw_prices = m.get("outcomePrices","[]")
            try:
                pp = json.loads(raw_prices) if isinstance(raw_prices, str) else raw_prices
                ps = " → ".join([f"${float(v)*100:.0f}¢" for v in pp]) if pp else ""
            except (json.JSONDecodeError, ValueError, TypeError):
                ps = ""
            vol = float(m.get("volume",0) or 0)
            bid = m.get("bestBid","N/A")
            ask = m.get("bestAsk","N/A")
            out.append(f"  • {q[:55]}")
            if ps:
                out.append(f"    Vol: ${vol:,.0f} | {ps} | Bid/Ask: ${bid}/{ask}")
            else:
                out.append(f"    Vol: ${vol:,.0f} | Bid/Ask: ${bid}/{ask}")
    
    # 3. 加密事件
    if all_crypto and isinstance(all_crypto, list):
        out.append(f"\n🔬 加密类事件 (24h成交量)")
        out.append("-" * 56)
        sorted_ev = sorted(all_crypto, key=lambda x: float(x.get("volume24hr",0) or 0), reverse=True)
        for ev in sorted_ev[:10]:
            title = ev.get("title","?")
            vol24h = float(ev.get("volume24hr",0) or 0)
            out.append(f"  • {title[:55]}")
            if vol24h > 0:
                out.append(f"    24hVol: ${vol24h:,.0f}")
    
    out.append("\n" + "=" * 56)
    out.append("ℹ️  DRY-RUN 模式 · 零成本 · 公开API · 不交易")
    return "\n".join(out)

if __name__ == "__main__":
    print("🔄 扫描中...")
    print(scan())