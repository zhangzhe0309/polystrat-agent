import requests
import json
import os
import sys

def get_top_markets():
    url = "https://gamma-api.polymarket.com/markets"
    params = {
        "closed": "false",
        "limit": 50,
        "active": "true",
        "order": "volume24hr",
        "ascending": "false"
    }
    resp = requests.get(url, params=params, timeout=15)
    markets = resp.json()

    top_markets = []
    for m in markets:
        q = m.get("question", "")
        vol = float(m.get("volume24hr") or 0)
        liq = float(m.get("liquidityNum") or 0)
        prices = m.get("outcomePrices")
        outcomes = m.get("outcomes")
        category = m.get("category", "")
        
        if isinstance(prices, str):
            try: prices = json.loads(prices)
            except: continue
        if isinstance(outcomes, str):
            try: outcomes = json.loads(outcomes)
            except: continue
            
        if not prices or not outcomes or len(prices) < 2:
            continue
            
        try:
            p1 = float(prices[0])
            p2 = float(prices[1])
        except:
            continue
            
        top_markets.append({
            "question": q,
            "vol": vol,
            "liq": liq,
            "outcomes": outcomes,
            "prices": prices,
            "p1": p1,
            "p2": p2,
            "slug": m.get("slug", ""),
            "category": category,
            "description": m.get("description", "")
        })

    top_markets.sort(key=lambda x: x["vol"], reverse=True)
    return top_markets

def get_whale_trades():
    r = requests.get("https://data-api.polymarket.com/trades?limit=500", timeout=15)
    trades = r.json()

    whales = []
    for t in trades:
        size = float(t.get("size", 0))
        price = float(t.get("price", 0))
        val = size * price
        if val >= 500:
            whales.append({
                "user": t.get("pseudonym") or t.get("name") or t.get("proxyWallet", "")[:10],
                "wallet": t.get("proxyWallet", ""),
                "title": t.get("title", ""),
                "side": t.get("side", ""),
                "outcome": t.get("outcome", ""),
                "val": val,
                "price": price,
                "timestamp": t.get("timestamp", "")
            })

    whales.sort(key=lambda x: x["val"], reverse=True)
    return whales

def scan_arbitrage():
    try:
        from negrisk_arbitrage import scan_negrisk_arbitrage
        opps = scan_negrisk_arbitrage(50)
        return opps
    except Exception as e:
        print("NegRisk scan exception:", e)
        return []

def main():
    print("=== TOP MARKETS ===")
    top = get_top_markets()
    for i, m in enumerate(top[:8]):
        q = m["question"]
        v = m["vol"]
        l = m["liq"]
        o1, o2 = m["outcomes"][0], m["outcomes"][1]
        p1, p2 = m["p1"] * 100, m["p2"] * 100
        print(f"{i+1}. {q}")
        print(f"   24h Vol: ${v:,.2f} | Liq: ${l:,.2f} | {o1}: {p1:.1f}% vs {o2}: {p2:.1f}%")
        print(f"   Slug: {m['slug']}")

    print("\n=== WHALE TRADES ===")
    whales = get_whale_trades()
    for w in whales[:10]:
        print(f"- Trader: {w['user']} ({w['wallet'][:8]}...) | Side: {w['side']} {w['outcome']} | Market: \"{w['title']}\" | Amount: ${w['val']:,.2f} @ Price: {w['price']:.3f}")

    print("\n=== ARBITRAGE OPPS ===")
    opps = scan_arbitrage()
    print(f"Total Opps Found: {len(opps)}")
    for o in opps:
        print(o)

if __name__ == "__main__":
    main()
