#!/usr/bin/env python3
"""
实时信息流模块
- WebSocket 连接管理
- Polymarket 市场数据流
- 新闻 RSS 实时推送
- 价格变动告警
"""
import os
import json
import asyncio
import websockets
from datetime import datetime, timezone
from pathlib import Path
from polystrat_logger import log, log_error

# WebSocket 配置
WS_ENDPOINTS = {
    "polymarket": "wss://ws-subscriptions-clob.polymarket.com/ws/market",
    "binance": "wss://stream.binance.com:9443/ws/btcusdt@trade",
}

# 价格缓存
PRICE_CACHE = {}
ALERT_THRESHOLDS = {
    "price_change_pct": 5.0,  # 价格变动超过5%触发告警
    "volume_spike": 3.0,      # 交易量突增3倍触发告警
}

class WebSocketManager:
    """WebSocket 连接管理器"""
    
    def __init__(self):
        self.connections = {}
        self.callbacks = {}
        self.running = False
    
    async def connect(self, name, url, callback=None):
        """连接 WebSocket"""
        try:
            ws = await websockets.connect(url)
            self.connections[name] = ws
            if callback:
                self.callbacks[name] = callback
            log.info(f"WebSocket 连接成功: {name}")
            return True
        except Exception as e:
            log_error("websocket", e, f"连接失败: {name}")
            return False
    
    async def subscribe_polymarket(self, market_ids):
        """订阅 Polymarket 市场数据"""
        if "polymarket" not in self.connections:
            await self.connect("polymarket", WS_ENDPOINTS["polymarket"])
        
        ws = self.connections.get("polymarket")
        if ws:
            # 订阅消息
            subscribe_msg = {
                "type": "subscribe",
                "channel": "market",
                "assets_ids": market_ids
            }
            await ws.send(json.dumps(subscribe_msg))
            log.info(f"已订阅 {len(market_ids)} 个市场")
    
    async def listen(self, name):
        """监听 WebSocket 消息"""
        ws = self.connections.get(name)
        if not ws:
            return
        
        try:
            async for message in ws:
                data = json.loads(message)
                
                # 调用回调
                if name in self.callbacks:
                    await self.callbacks[name](data)
                
                # 更新价格缓存
                self._update_price_cache(name, data)
                
        except websockets.exceptions.ConnectionClosed:
            log.warning(f"WebSocket 连接断开: {name}")
        except Exception as e:
            log_error("websocket", e, f"监听失败: {name}")
    
    def _update_price_cache(self, source, data):
        """更新价格缓存"""
        if source == "polymarket":
            asset_id = data.get("asset_id", "")
            if asset_id:
                PRICE_CACHE[asset_id] = {
                    "price": float(data.get("price", 0)),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source": "polymarket"
                }
        elif source == "binance":
            symbol = data.get("s", "")
            if symbol:
                PRICE_CACHE[symbol] = {
                    "price": float(data.get("p", 0)),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source": "binance"
                }
    
    async def start(self):
        """启动所有连接"""
        self.running = True
        tasks = [self.listen(name) for name in self.connections]
        await asyncio.gather(*tasks)
    
    async def stop(self):
        """停止所有连接"""
        self.running = False
        for name, ws in self.connections.items():
            await ws.close()
        self.connections.clear()

# 全局管理器
ws_manager = WebSocketManager()

async def price_alert_callback(data):
    """价格变动回调"""
    asset_id = data.get("asset_id", "")
    new_price = float(data.get("price", 0))
    
    # 检查价格变动
    if asset_id in PRICE_CACHE:
        old_price = PRICE_CACHE[asset_id]["price"]
        if old_price > 0:
            change_pct = abs(new_price - old_price) / old_price * 100
            if change_pct > ALERT_THRESHOLDS["price_change_pct"]:
                log.warning(f"价格大幅变动: {asset_id} {old_price:.2f} -> {new_price:.2f} ({change_pct:.1f}%)")

def get_price(asset_id):
    """获取缓存价格"""
    return PRICE_CACHE.get(asset_id)

def get_all_prices():
    """获取所有缓存价格"""
    return PRICE_CACHE.copy()

# RSS 实时推送
import feedparser

RSS_FEEDS = {
    "cointelegraph": "https://cointelegraph.com/rss",
    "coindesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "decrypt": "https://decrypt.co/feed",
}

def fetch_rss_news(feed_url, max_items=10):
    """获取 RSS 新闻"""
    try:
        feed = feedparser.parse(feed_url)
        items = []
        for entry in feed.entries[:max_items]:
            items.append({
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "published": entry.get("published", ""),
                "summary": entry.get("summary", "")[:200],
            })
        return items
    except Exception as e:
        log_error("rss", e, f"RSS 获取失败: {feed_url}")
        return []

def get_realtime_news():
    """获取实时新闻（所有 RSS 源）"""
    all_news = []
    for name, url in RSS_FEEDS.items():
        news = fetch_rss_news(url, 5)
        for n in news:
            n["source"] = name
        all_news.extend(news)
    
    # 按时间排序
    all_news.sort(key=lambda x: x.get("published", ""), reverse=True)
    return all_news[:20]

if __name__ == "__main__":
    print("=" * 50)
    print("实时信息流测试")
    print("=" * 50)
    
    # 测试 RSS
    print("\n1. RSS 新闻:")
    news = get_realtime_news()
    print(f"   获取到 {len(news)} 条新闻")
    for n in news[:3]:
        print(f"   - [{n['source']}] {n['title'][:50]}...")
    
    # 测试价格缓存
    print("\n2. 价格缓存:")
    print(f"   缓存数量: {len(PRICE_CACHE)}")
    
    print("\n✅ 实时信息流测试完成")
    print("\n注意: WebSocket 需要异步环境运行")
    print("使用: asyncio.run(ws_manager.start())")
