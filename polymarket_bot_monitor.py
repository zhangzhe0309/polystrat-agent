#!/usr/bin/env python3
"""
Polymarket Copy Trading Monitor - no_agent mode for Hermes Cron
Outputs trades only when NEW unique trades found in last 1 hour.
Silent when nothing new. Persists seen keys to avoid re-notification.
"""
import os
import json
import requests
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv("/root/.hermes/profiles/life/home/.hermes/polymarket_bot/.env")

# === CONFIG ===
WALLET_ADDRESSES = [
    "0x9f2fe025f84839ca81dd8e0338892605702d2ca8",  # surfandturf
    "0x2c335066fe58fe9237c3d3dc7b275c2a034a0563",  # 高频交易员 ($116M)
]
MONITOR_WINDOW_HOURS = 1
FUNDER_ADDRESS = os.getenv("POLYMARKET_FUNDER_ADDRESS")
PRIVATE_KEY = os.getenv("POLYMARKET_PRIVATE_KEY")
SIGNATURE_TYPE = int(os.getenv("SIGNATURE_TYPE", "1"))
BET_AMOUNT = float(os.getenv("BET_AMOUNT", "2.00"))
AUTO_TRADE_ENABLED = os.getenv("AUTO_TRADE_ENABLED", "false").lower() == "true"
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"

DATA_API = "https://data-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"
SEEN_FILE = "/root/.hermes/profiles/life/home/.hermes/polymarket_bot/logs/seen_keys.json"
TRADE_HISTORY_FILE = "/root/.hermes/profiles/life/home/.hermes/polymarket_bot/logs/trade_history.json"


def load_seen_keys():
    """Load previously notified trade keys, pruning entries older than 2 hours"""
    if not os.path.exists(SEEN_FILE):
        return {}
    try:
        with open(SEEN_FILE) as f:
            data = json.load(f)
        # Prune entries older than 2 hours to prevent unbounded growth
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        return {k: v for k, v in data.items() if v.get("ts", "") > cutoff}
    except:
        return {}


def save_seen_keys(data):
    os.makedirs(os.path.dirname(SEEN_FILE), exist_ok=True)
    with open(SEEN_FILE, 'w') as f:
        json.dump(data, f)


def get_recent_buys(address, cutoff_time):
    params = {
        "limit": 50, "offset": 0,
        "sortBy": "TIMESTAMP", "sortOrder": "DESC",
        "user": address,
        "startDateMin": cutoff_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    try:
        resp = requests.get(f"{DATA_API}/activity", params=params, timeout=30)
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
                    'conditionId': a.get('conditionId', ''),
                })
        return results
    except Exception:
        return []


def place_bet(token_id, amount):
    if DRY_RUN:
        return {"status": "DRY_RUN"}
    try:
        from py_clob_client import ClobClient, OrderArgs, OrderType
        client = ClobClient(CLOB_API, key=PRIVATE_KEY, chain_id=137,
                            signature_type=SIGNATURE_TYPE, funder=FUNDER_ADDRESS)
        creds = client.derive_api_key()
        client.set_api_creds(creds)
        order = OrderArgs(price=0.50, size=amount, side="BUY", token_id=token_id)
        signed = client.create_order(order)
        resp = client.post_order(signed, OrderType.GTC)
        return {"status": "SUCCESS", "response": resp}
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}


def save_trade_record(info):
    os.makedirs(os.path.dirname(TRADE_HISTORY_FILE), exist_ok=True)
    trades = []
    if os.path.exists(TRADE_HISTORY_FILE):
        try:
            trades = json.load(open(TRADE_HISTORY_FILE))
        except:
            pass
    trades.append(info)
    with open(TRADE_HISTORY_FILE, 'w') as f:
        json.dump(trades, f, indent=2)


def main():
    cutoff = datetime.now(timezone.utc) - timedelta(hours=MONITOR_WINDOW_HOURS)
    seen = load_seen_keys()
    new_bets = []

    for address in WALLET_ADDRESSES:
        trades = get_recent_buys(address, cutoff)
        for bet in trades:
            key = f"{bet['title']}|{bet['outcomeIndex']}|{bet['asset'][:20]}"
            if key in seen:
                continue
            # Mark as seen immediately
            seen[key] = {"ts": datetime.now(timezone.utc).isoformat(), "addr": address[:10]}
            new_bets.append((address, bet))

    # Save seen keys (with pruning)
    save_seen_keys(seen)

    if not new_bets:
        return  # Silent

    lines = ["🔔 Polymarket 新交易检测！\n"]
    for address, bet in new_bets:
        slug = bet.get('slug', '')
        link = f"https://polymarket.com/event/{slug}?tab=Position&be={address}" if slug else "N/A"
        lines.append(f"🎯 {bet['title']}")
        lines.append(f"   方向: {'Yes' if bet['outcomeIndex'] == 0 else 'No'} @ {bet['price']*100:.0f}¢")
        lines.append(f"   下注: ${bet['size']:,.2f}")
        lines.append(f"   时间: {bet['timestamp'].strftime('%H:%M')} UTC")
        lines.append(f"   🔗 {link}")
        lines.append("")

    if AUTO_TRADE_ENABLED:
        lines.append("=" * 40)
        lines.append("🤖 自动跟单：\n")
        for address, bet in new_bets:
            result = place_bet(bet['asset'], BET_AMOUNT)
            status = result.get('status')
            if status == 'DRY_RUN':
                lines.append(f"   ✅ 模拟: {bet['title']}")
            elif status == 'SUCCESS':
                lines.append(f"   ✅ 实盘: {bet['title']}")
            else:
                lines.append(f"   ❌ 失败: {result.get('message', '')}")
            save_trade_record({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "mode": "DRY_RUN" if DRY_RUN else "LIVE",
                "market": bet['title'],
                "outcome": "Yes" if bet['outcomeIndex'] == 0 else "No",
                "price": bet['price'],
                "amount": BET_AMOUNT,
                "status": status,
            })

    print("\n".join(lines))


if __name__ == "__main__":
    main()
