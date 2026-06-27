#!/usr/bin/env python3
"""
信号聚合器 (Signal Aggregator)
集成自 KongTradeBot CopyTradingStrategy 的信号聚合逻辑

核心功能:
1. 多钱包信号聚合 — 同市场多钱包信号 → 放大仓位
2. 羊群效应检测 — >50% 钱包同市场 → 不放大 + 告警
3. 信号新鲜度过滤 — 超时信号丢弃
4. Early Entry Bonus — 新市场低体积 → 1.5x 加成

KongTradeBot 参数:
- AGGREGATION_WINDOW_S = 60  (60 秒聚合窗口)
- MULTI_SIGNAL_MULTIPLIERS = {1: 1.0, 2: 1.5, 3: 2.0}
- HERD_FRACTION = 0.50  (50% 钱包 = 羊群效应)
- EARLY_ENTRY_MULTIPLIER = 1.5  (体积 < $10K = Early Entry)

使用方式:
    aggregator = SignalAggregator(target_wallets=["0x...", "0x..."])
    aggregator.on_signal = my_callback  # 设置回调
    
    # 收到新交易信号时调用
    aggregator.buffer_signal(signal)
    
    # 或手动 flush
    results = aggregator.flush_all()
"""

import time
import json
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Dict, List, Optional, Callable
from collections import defaultdict
from pathlib import Path

# ── 配置 ──────────────────────────────────────────────────────────

# 信号聚合窗口 (秒)
AGGREGATION_WINDOW_S = 60

# 多信号乘数
MULTI_SIGNAL_MULTIPLIERS = {
    1: 1.0,
    2: 1.5,
    3: 2.0,  # 3+ 钱包 → 2x
}

# 羊群效应阈值
HERD_FRACTION = 0.50

# Early Entry 配置
EARLY_ENTRY_MULTIPLIER = 1.5
EARLY_ENTRY_VOLUME_USD = 10_000

# 信号过期时间 (秒)
SIGNAL_MAX_AGE_S = 300  # 5 分钟

# 价格范围过滤
MIN_PRICE = 0.15
MAX_PRICE = 0.85


@dataclass
class TradeSignal:
    """交易信号 (与 KongTradeBot TradeSignal 兼容)"""
    # 身份
    tx_hash: str
    source_wallet: str
    
    # 交易详情
    market_id: str           # conditionId
    token_id: str            # YES/NO Token ID
    side: str                # "BUY" / "SELL"
    price: float             # 0.0-1.0
    size_usdc: float         # 交易金额
    outcome: str             # "Yes" / "No"
    
    # 上下文
    market_question: str = ""
    market_volume_usd: float = 0.0
    is_early_entry: bool = False
    
    # 时间
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    market_closes_at: Optional[datetime] = None
    
    @property
    def is_fresh(self) -> bool:
        age = (datetime.now(timezone.utc) - self.detected_at).total_seconds()
        return age <= SIGNAL_MAX_AGE_S
    
    @property
    def is_valid_price(self) -> bool:
        return MIN_PRICE <= self.price <= MAX_PRICE
    
    @property
    def aggregation_key(self) -> str:
        """聚合键: 同 token + 同 outcome = 同一信号"""
        return f"{self.token_id}:{self.outcome}"


@dataclass
class AggregatedSignal:
    """聚合后的信号"""
    signals: List[TradeSignal]
    wallet_count: int
    wallet_names: List[str]
    
    # 乘数
    multi_signal_multiplier: float = 1.0
    early_entry_multiplier: float = 1.0
    is_herd: bool = False
    
    # 最强信号 (最大金额)
    best_signal: Optional[TradeSignal] = None
    
    @property
    def combined_multiplier(self) -> float:
        return self.multi_signal_multiplier * self.early_entry_multiplier
    
    @property
    def total_size_usdc(self) -> float:
        return sum(s.size_usdc for s in self.signals)


class SignalAggregator:
    """
    信号聚合器
    
    流程:
    1. 接收 TradeSignal → 按 aggregation_key 缓冲
    2. 在 AGGREGATION_WINDOW_S 内收集同 key 的信号
    3. 窗口到期 → 计算多信号乘数 + Early Entry 加成
    4. 羊群效应检测
    5. 输出 AggregatedSignal
    """
    
    def __init__(
        self,
        target_wallets: List[str] = None,
        wallet_names: Dict[str, str] = None,
        wallet_multipliers: Dict[str, float] = None,
        aggregation_window_s: int = AGGREGATION_WINDOW_S,
    ):
        """
        Args:
            target_wallets: 目标钱包列表
            wallet_names: 钱包地址 → 名称映射
            wallet_multipliers: 钱包地址 → 乘数映射
            aggregation_window_s: 聚合窗口 (秒)
        """
        self.target_wallets = [w.lower() for w in (target_wallets or [])]
        self.wallet_names = wallet_names or {}
        self.wallet_multipliers = wallet_multipliers or {}
        self.aggregation_window_s = aggregation_window_s
        
        # 缓冲: key → [(signal, timestamp)]
        self._buffer: Dict[str, List[Tuple[TradeSignal, float]]] = defaultdict(list)
        
        # 回调
        self.on_aggregated_signal: Optional[Callable] = None
        self.on_herd_alert: Optional[Callable] = None
        
        # 统计
        self.stats = {
            "signals_received": 0,
            "signals_deduped": 0,
            "signals_expired": 0,
            "signals_invalid_price": 0,
            "aggregated_signals": 0,
            "multi_signals": 0,
            "herd_alerts": 0,
            "early_entries": 0,
        }
    
    def buffer_signal(self, signal: TradeSignal) -> Optional[AggregatedSignal]:
        """
        缓冲信号并检查是否应该立即处理
        
        如果是新的 key 的第一个信号，启动聚合窗口。
        如果窗口已有同钱包信号，去重。
        如果窗口已到期，返回聚合结果。
        
        Args:
            signal: 交易信号
        
        Returns:
            AggregatedSignal (如果窗口到期) 或 None
        """
        self.stats["signals_received"] += 1
        
        # 价格过滤
        if not signal.is_valid_price:
            self.stats["signals_invalid_price"] += 1
            return None
        
        # 新鲜度过滤
        if not signal.is_fresh:
            self.stats["signals_expired"] += 1
            return None
        
        key = signal.aggregation_key
        now = time.time()
        
        # 清理过期信号
        self._clean_expired(key, now)
        
        # 去重: 同一钱包不重复缓冲
        existing_wallets = [s.source_wallet.lower() for s, _ in self._buffer[key]]
        if signal.source_wallet.lower() in existing_wallets:
            self.stats["signals_deduped"] += 1
            return None
        
        # 添加到缓冲
        self._buffer[key].append((signal, now))
        
        # 检查是否已有聚合窗口
        first_time = self._buffer[key][0][1] if self._buffer[key] else now
        
        # 如果窗口已到期，立即返回
        if now - first_time >= self.aggregation_window_s:
            return self._flush_key(key)
        
        return None
    
    def flush_expired(self) -> List[AggregatedSignal]:
        """
        刷新所有过期的聚合窗口
        
        应由定时器定期调用
        
        Returns:
            聚合信号列表
        """
        results = []
        now = time.time()
        
        for key in list(self._buffer.keys()):
            if not self._buffer[key]:
                continue
            first_time = self._buffer[key][0][1]
            if now - first_time >= self.aggregation_window_s:
                result = self._flush_key(key)
                if result:
                    results.append(result)
        
        return results
    
    def flush_all(self) -> List[AggregatedSignal]:
        """强制刷新所有缓冲"""
        results = []
        for key in list(self._buffer.keys()):
            result = self._flush_key(key)
            if result:
                results.append(result)
        return results
    
    def _flush_key(self, key: str) -> Optional[AggregatedSignal]:
        """刷新指定 key 的聚合窗口"""
        signals_with_ts = self._buffer.pop(key, [])
        if not signals_with_ts:
            return None
        
        signals = [s for s, _ in signals_with_ts]
        wallet_count = len(signals)
        
        # 最强信号
        best_signal = max(signals, key=lambda s: s.size_usdc)
        
        # 钱包名称
        wallet_name_list = [
            self.wallet_names.get(s.source_wallet.lower(), s.source_wallet[:10] + "...")
            for s in signals
        ]
        
        # 多信号乘数
        multi_signal_mult = MULTI_SIGNAL_MULTIPLIERS.get(wallet_count, 2.0)
        
        # 羊群效应检测
        is_herd = False
        total_wallets = max(1, len(self.target_wallets))
        herd_threshold = max(3, int(total_wallets * HERD_FRACTION))
        
        if wallet_count > herd_threshold:
            is_herd = True
            multi_signal_mult = 1.0  # 羊群效应 → 不放大
            self.stats["herd_alerts"] += 1
        
        # Early Entry 加成
        early_entry_mult = 1.0
        if any(s.is_early_entry for s in signals):
            early_entry_mult = EARLY_ENTRY_MULTIPLIER
            self.stats["early_entries"] += 1
        
        # 更新统计
        self.stats["aggregated_signals"] += 1
        if wallet_count >= 2:
            self.stats["multi_signals"] += 1
        
        result = AggregatedSignal(
            signals=signals,
            wallet_count=wallet_count,
            wallet_names=wallet_name_list,
            multi_signal_multiplier=multi_signal_mult,
            early_entry_multiplier=early_entry_mult,
            is_herd=is_herd,
            best_signal=best_signal,
        )
        
        return result
    
    def _clean_expired(self, key: str, now: float):
        """清理过期信号"""
        if key not in self._buffer:
            return
        self._buffer[key] = [
            (s, ts) for s, ts in self._buffer[key]
            if now - ts <= SIGNAL_MAX_AGE_S
        ]
    
    def get_status(self) -> dict:
        """获取当前状态"""
        return {
            "buffer_keys": len(self._buffer),
            "buffered_signals": sum(len(v) for v in self._buffer.values()),
            "stats": self.stats,
            "target_wallets": len(self.target_wallets),
        }
    
    def format_signal(self, agg: AggregatedSignal) -> str:
        """格式化聚合信号"""
        names = " + ".join(agg.wallet_names)
        market_short = agg.best_signal.market_question[:60] if agg.best_signal else ""
        
        lines = []
        
        if agg.is_herd:
            pct = agg.wallet_count / max(1, len(self.target_wallets)) * 100
            lines.append(f"🐑 羊群效应 ({agg.wallet_count}/{len(self.target_wallets)} = {pct:.0f}%)")
            lines.append(f"   不放大 | {names}")
        elif agg.wallet_count >= 2:
            lines.append(f"🔥 多信号 ({agg.wallet_count}x): {names}")
            lines.append(f"   乘数: {agg.multi_signal_multiplier}x")
        
        if agg.early_entry_multiplier > 1.0:
            lines.append(f"   🌱 Early Entry: {agg.early_entry_multiplier}x")
        
        lines.append(f"   市场: {market_short}")
        if agg.best_signal:
            lines.append(f"   方向: {agg.best_signal.outcome} @ ${agg.best_signal.price:.3f}")
            lines.append(f"   金额: ${agg.total_size_usdc:.2f}")
            lines.append(f"   综合乘数: {agg.combined_multiplier:.1f}x")
        
        return "\n".join(lines)


if __name__ == "__main__":
    print("=" * 60)
    print("信号聚合器测试")
    print("=" * 60)
    
    # 模拟 KongTradeBot 钱包配置
    wallet_names = {
        "0x019782cab5d844f02bafb71f512758be78579f3c": "majorexploiter",
        "0xbddf61af533ff524d27154e589d2d7a81510c684": "Countryside",
        "0xdb27bf2ac5d428a9c63dbc914611036855a6c56e": "DrPufferfish",
    }
    
    aggregator = SignalAggregator(
        target_wallets=list(wallet_names.keys()),
        wallet_names=wallet_names,
    )
    
    # 模拟信号: 2 个钱包买入同市场
    signal1 = TradeSignal(
        tx_hash="0xabc1",
        source_wallet="0x019782cab5d844f02bafb71f512758be78579f3c",
        market_id="0xmarket1",
        token_id="0xtoken_yes",
        side="BUY",
        price=0.35,
        size_usdc=200.0,
        outcome="Yes",
        market_question="Will it rain in NYC tomorrow?",
    )
    
    signal2 = TradeSignal(
        tx_hash="0xabc2",
        source_wallet="0xbddf61af533ff524d27154e589d2d7a81510c684",
        market_id="0xmarket1",
        token_id="0xtoken_yes",
        side="BUY",
        price=0.36,
        size_usdc=150.0,
        outcome="Yes",
        market_question="Will it rain in NYC tomorrow?",
    )
    
    # 缓冲信号
    result = aggregator.buffer_signal(signal1)
    print(f"\n1️⃣ 信号1 (majorexploiter): {'已缓冲' if result is None else '已聚合'}")
    
    result = aggregator.buffer_signal(signal2)
    print(f"2️⃣ 信号2 (Countryside): {'已缓冲' if result is None else '已聚合'}")
    
    # 刷新所有
    results = aggregator.flush_all()
    for agg in results:
        print(f"\n{aggregator.format_signal(agg)}")
    
    # 测试羊群效应 (3/3 = 100%)
    signal3 = TradeSignal(
        tx_hash="0xabc3",
        source_wallet="0xdb27bf2ac5d428a9c63dbc914611036855a6c56e",
        market_id="0xmarket2",
        token_id="0xtoken2_yes",
        side="BUY",
        price=0.55,
        size_usdc=300.0,
        outcome="Yes",
        market_question="Will BTC hit $100K?",
    )
    
    # 添加更多信号来模拟羊群
    for i, wallet in enumerate(list(wallet_names.keys())):
        s = TradeSignal(
            tx_hash=f"0xherd{i}",
            source_wallet=wallet,
            market_id="0xmarket2",
            token_id="0xtoken2_yes",
            side="BUY",
            price=0.55 + i * 0.01,
            size_usdc=100.0,
            outcome="Yes",
            market_question="Will BTC hit $100K?",
        )
        aggregator.buffer_signal(s)
    
    results = aggregator.flush_all()
    for agg in results:
        print(f"\n{aggregator.format_signal(agg)}")
    
    print(f"\n📊 统计: {aggregator.get_status()['stats']}")
    print("\n✅ 信号聚合器测试完成")
