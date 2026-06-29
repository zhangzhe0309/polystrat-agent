#!/usr/bin/env python3
"""
PolyStrat 集成胶水模块
将 KongTradeBot + negRisk 套利组件连接到 PolyStrat 主循环

集成架构:
┌─────────────────────────────────────────────────┐
│ PolyStrat 主循环                                   │
│                                                   │
│  ┌──────────────┐  ┌─────────────────────────┐   │
│  │ WalletMonitor │→│ SignalAggregator        │   │
│  │ (异步化)      │  │ (多钱包信号聚合)         │   │
│  └──────────────┘  └────────────┬────────────┘   │
│                                  │                │
│  ┌──────────────┐               │                │
│  │ KongScoreV2  │←──────────────┤                │
│  │ (钱包评分)    │               │                │
│  └──────┬───────┘               │                │
│         │ multiplier            │                │
│         ▼                       ▼                │
│  ┌──────────────────────────────────────┐        │
│  │ TakeProfitManager                     │        │
│  │ (阶梯止盈 + 鲸鱼退出跟随)              │        │
│  └──────────────────────────────────────┘        │
│                                                   │
│  ┌──────────────┐  ┌─────────────────────────┐   │
│  │ NegRisk      │  │ RiskManager             │   │
│  │ Arbitrage    │  │ (增强版风险管理)          │   │
│  │ Detector     │  │                         │   │
│  └──────────────┘  └─────────────────────────┘   │
└─────────────────────────────────────────────────┘

使用方式:
    from polystrat_integration import PolyStratIntegration
    
    psi = PolyStratIntegration()
    await psi.initialize()
    
    # 主循环
    while True:
        signals = await psi.scan_whale_signals()
        arb_opps = await psi.scan_arbitrage()
        await psi.process_signals(signals)
        await psi.run()
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional
from pathlib import Path

# PolyStrat 现有模块
try:
    from polystrat_logger import log, log_error
except ImportError:
    def log(module, msg): print(f"[{module}] {msg}")
    def log_error(module, e, ctx=""): print(f"[{module}] ERROR: {e} | {ctx}")

# 新集成模块
from kong_score_v2 import KongScoreV2, WalletMetrics, extract_wallet_metrics, calculate_kongscore_v2
from signal_aggregator import SignalAggregator, TradeSignal, AggregatedSignal
from take_profit_manager import TakeProfitManager, ExitSignal
from negrisk_arbitrage import NegRiskArbitrageDetector, scan_negrisk_arbitrage

# ── 常量 ──────────────────────────────────────────────────────────

DATA_API = "https://data-api.polymarket.com"
from config_center import GAMMA_API
POLL_INTERVAL_S = 10

# 跟单配置 (从 KongTradeBot 迁移)
COPY_CONFIG = {
    "multiplier": 0.05,            # 基础跟单比例 5%
    "max_position_usd": 100,       # 单笔最大仓位
    "min_whale_size_usd": 100,     # 最小鲸鱼下注
    "max_daily_copies": 10,        # 每日最大跟单数
    "min_kongscore": 50,           # 最低 KongScore
    "max_daily_loss_usd": 50,      # 日损限额
}

# 资本分配 (来自 IMDEA 研究建议)
CAPITAL_ALLOCATION = {
    "whale_copy": 0.10,            # 10% 鲸鱼跟单
    "negrisk_arb": 0.40,           # 40% NegRisk 套利
    "single_cond_arb": 0.30,       # 30% 单条件套利
    "endgame_arb": 0.20,           # 20% Endgame 套利
    "reserve": 0.00,               # 0% 储备 (可调整)
}


class PolyStratIntegration:
    """
    PolyStrat 集成主类
    
    整合:
    1. KongScoreV2 — 钱包评分 + 筛选
    2. SignalAggregator — 多钱包信号聚合
    3. TakeProfitManager — 阶梯止盈
    4. NegRiskArbitrageDetector — 套利检测
    """
    
    def __init__(self, config: dict = None):
        self.config = config or COPY_CONFIG
        from config_center import POLYSTRAT_DIR; self.data_dir = POLYSTRAT_DIR
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # 组件初始化
        self.kong_score = KongScoreV2(pool_size="small", data_dir=str(self.data_dir / "kong_score"))
        self.signal_aggregator = SignalAggregator(
            target_wallets=config.get("target_wallets", []) if config else [],
        )
        self.tp_manager = TakeProfitManager(data_dir=str(self.data_dir / "tp_manager"))
        self.arb_detector = NegRiskArbitrageDetector(top_markets=config.get("top_markets", 30) if config else 30)
        
        # 状态
        self._seen_tx_hashes: set = set()
        self._daily_copies = 0
        self._daily_loss_usd = 0.0
        self._kill_switch = False
        self._wallet_kongscores: Dict[str, dict] = {}
        
        # 统计
        self.stats = {
            "whale_signals": 0,
            "copy_trades": 0,
            "arb_opportunities": 0,
            "tp_exits": 0,
            "whale_exits": 0,
        }
    
    async def initialize(self):
        """初始化所有组件"""
        log("polystrat", "初始化 PolyStrat 集成模块...")
        
        # 加载已知钱包的 KongScore
        target_wallets = self.config.get("target_wallets", [])
        for wallet in target_wallets:
            score = calculate_kongscore_v2(wallet)
            self._wallet_kongscores[wallet.lower()] = score
            tier = score.get("tier", "C")
            mult = score.get("multiplier", 0)
            log("polystrat", f"  钱包 {wallet[:10]}... : Score={score['score']:.0f}, Tier={tier}, Mult={mult}x")
        
        log("polystrat", f"初始化完成 | {len(target_wallets)} 钱包 | Kill-Switch: {self._kill_switch}")
    
    async def scan_whale_signals(self, wallet_address: str = None) -> List[AggregatedSignal]:
        """
        扫描鲸鱼信号
        
        Args:
            wallet_address: 单个钱包 (可选, None=所有目标钱包)
        
        Returns:
            聚合信号列表
        """
        if self._kill_switch:
            return []
        
        wallets = [wallet_address] if wallet_address else self.config.get("target_wallets", [])
        all_signals = []
        
        for wallet in wallets:
            try:
                activity = self._fetch_wallet_activity(wallet, limit=5)
                for trade in activity:
                    signal = self._parse_trade_signal(trade, wallet)
                    if signal and signal.tx_hash not in self._seen_tx_hashes:
                        self._seen_tx_hashes.add(signal.tx_hash)
                        
                        # 缓冲信号
                        result = self.signal_aggregator.buffer_signal(signal)
                        if result:
                            all_signals.append(result)
            except Exception as e:
                log_error("polystrat", e, f"扫描钱包 {wallet[:10]}...")
        
        # 刷新过期窗口
        expired = self.signal_aggregator.flush_expired()
        all_signals.extend(expired)
        
        self.stats["whale_signals"] += len(all_signals)
        return all_signals
    
    async def scan_arbitrage(self) -> List[dict]:
        """
        扫描套利机会
        
        Returns:
            套利机会列表
        """
        try:
            opportunities = await self.arb_detector.scan()
            self.stats["arb_opportunities"] += len(opportunities)
            return [
                {
                    "type": o.opportunity_type,
                    "market": o.market_name[:60],
                    "profit_usd": o.expected_profit_usd,
                    "roi_pct": o.roi_pct,
                    "risk_score": o.risk_score,
                    "urgency": o.urgency,
                    "capital_required": o.capital_required,
                }
                for o in opportunities
            ]
        except Exception as e:
            log_error("polystrat", e, "套利扫描")
            return []
    
    async def process_signals(self, signals: List[AggregatedSignal]) -> List[dict]:
        """
        处理聚合信号 → 生成跟单决策
        
        流程:
        1. 检查 KongScore + Tier
        2. 计算跟单金额 (multiplier × signal_multiplier × early_entry)
        3. 风险检查 (日损限额, 最大仓位, Kill-Switch)
        4. 创建持仓 + TP 阶梯设置
        """
        if self._kill_switch:
            return []
        
        decisions = []
        
        for agg in signals:
            if not agg.best_signal:
                continue
            
            signal = agg.best_signal
            wallet = signal.source_wallet.lower()
            
            # Step 1: KongScore 检查
            kongscore = self._wallet_kongscores.get(wallet)
            if not kongscore:
                kongscore = calculate_kongscore_v2(wallet)
                self._wallet_kongscores[wallet] = kongscore
            
            if kongscore.get("score", 0) < self.config.get("min_kongscore", 50):
                continue
            
            if kongscore.get("decay_status") == "decaying":
                continue
            
            # Step 2: 计算跟单金额
            wallet_mult = kongscore.get("multiplier", 0.5)
            if kongscore.get("decay_status") == "declining":
                wallet_mult /= 2  # Trend-Decline → 减半
            
            base_size = signal.size_usdc * self.config.get("multiplier", 0.05)
            combined_mult = wallet_mult * agg.combined_multiplier
            final_size = min(base_size * combined_mult, self.config.get("max_position_usd", 100))
            
            # Step 3: 风险检查
            if self._daily_copies >= self.config.get("max_daily_copies", 10):
                break
            if self._daily_loss_usd >= self.config.get("max_daily_loss_usd", 50):
                self._kill_switch = True
                break
            if signal.size_usdc < self.config.get("min_whale_size_usd", 100):
                continue
            
            # Step 4: 创建决策
            decision = {
                "action": "COPY_BUY",
                "wallet": wallet[:10] + "...",
                "kongscore": kongscore["score"],
                "tier": kongscore["tier"],
                "wallet_mult": wallet_mult,
                "signal_mult": agg.combined_multiplier,
                "is_herd": agg.is_herd,
                "market": signal.market_question[:60],
                "outcome": signal.outcome,
                "whale_size_usd": signal.size_usdc,
                "copy_size_usd": round(final_size, 2),
                "price": signal.price,
                "is_early_entry": signal.is_early_entry,
            }
            decisions.append(decision)
            self._daily_copies += 1
            self.stats["copy_trades"] += 1
            
            # Step 5: 注册到 TP 管理器
            position_id = f"copy_{self._daily_copies}_{signal.tx_hash[:8]}"
            self.tp_manager.add_position(
                position_id=position_id,
                entry_price=signal.price,
                size_usdc=final_size,
                source_wallet=wallet,
                market_id=signal.market_id,
                token_id=signal.token_id,
                outcome=signal.outcome,
                market_question=signal.market_question,
                category=self._classify_market(signal.market_question),
                market_closes_at=signal.market_closes_at,
            )
        
        return decisions
    
    def check_take_profits(self, current_prices: Dict[str, float]) -> List[ExitSignal]:
        """检查止盈条件"""
        exits = self.tp_manager.check_take_profits(current_prices)
        
        for ex in exits:
            if ex.pnl_usd < 0:
                self._daily_loss_usd += abs(ex.pnl_usd)
            self.stats["tp_exits"] += 1
            if ex.stage == "WHALE_EXIT":
                self.stats["whale_exits"] += 1
        
        return exits
    
    def handle_whale_exit(self, source_wallet: str, token_id: str, current_price: float) -> List[ExitSignal]:
        """处理鲸鱼退出"""
        exits = self.tp_manager.handle_whale_exit(source_wallet, token_id, current_price)
        self.stats["whale_exits"] += len(exits)
        return exits
    
    def get_status(self) -> dict:
        """获取完整状态"""
        return {
            "kill_switch": self._kill_switch,
            "daily_copies": self._daily_copies,
            "daily_loss_usd": self._daily_loss_usd,
            "open_positions": len(self.tp_manager.positions),
            "wallets_scored": len(self._wallet_kongscores),
            "seen_tx_hashes": len(self._seen_tx_hashes),
            "stats": self.stats,
            "signal_aggregator": self.signal_aggregator.get_status(),
            "capital_allocation": CAPITAL_ALLOCATION,
        }
    
    def format_status(self) -> str:
        """格式化状态报告"""
        status = self.get_status()
        lines = [
            "📊 **PolyStrat 状态报告**",
            "=" * 50,
            f"Kill-Switch: {'🛑 ACTIVE' if status['kill_switch'] else '✅ OFF'}",
            f"今日跟单: {status['daily_copies']}/{COPY_CONFIG['max_daily_copies']}",
            f"今日亏损: ${status['daily_loss_usd']:.2f}/${COPY_CONFIG['max_daily_loss_usd']}",
            f"持仓数: {status['open_positions']}",
            f"已评分钱包: {status['wallets_scored']}",
            "",
            "📈 统计:",
            f"  鲸鱼信号: {status['stats']['whale_signals']}",
            f"  跟单交易: {status['stats']['copy_trades']}",
            f"  套利机会: {status['stats']['arb_opportunities']}",
            f"  TP 退出: {status['stats']['tp_exits']}",
            f"  鲸鱼退出跟随: {status['stats']['whale_exits']}",
            "",
            "💰 资本分配:",
            f"  鲸鱼跟单: {CAPITAL_ALLOCATION['whale_copy']:.0%}",
            f"  NegRisk 套利: {CAPITAL_ALLOCATION['negrisk_arb']:.0%}",
            f"  单条件套利: {CAPITAL_ALLOCATION['single_cond_arb']:.0%}",
            f"  Endgame: {CAPITAL_ALLOCATION['endgame_arb']:.0%}",
        ]
        return "\n".join(lines)
    
    # ── 内部方法 ──────────────────────────────────────────────
    
    def _fetch_wallet_activity(self, wallet_address: str, limit: int = 20) -> list:
        """获取钱包活动"""
        try:
            import requests
            resp = requests.get(
                f"{DATA_API}/activity",
                params={"user": wallet_address, "limit": limit},
                timeout=15
            )
            if resp.status_code == 200:
                data = resp.json()
                return data if isinstance(data, list) else data.get("data", [])
        except Exception as e:
            log_error("polystrat", e, f"获取钱包活动: {wallet_address[:10]}...")
        return []
    
    def _parse_trade_signal(self, activity: dict, source_wallet: str) -> Optional[TradeSignal]:
        """解析交易信号"""
        try:
            price = float(activity.get("price", 0))
            if not (0.15 <= price <= 0.85):
                return None
            
            size_usdc = float(activity.get("usdcSize", 0) or activity.get("size", 0))
            if size_usdc < self.config.get("min_whale_size_usd", 100):
                return None
            
            tx_hash = activity.get("transactionHash", activity.get("id", ""))
            if not tx_hash or tx_hash in self._seen_tx_hashes:
                return None
            
            activity_type = activity.get("type", "").upper()
            if activity_type not in ("BUY", "TRADE"):
                return None
            
            return TradeSignal(
                tx_hash=tx_hash,
                source_wallet=source_wallet,
                market_id=activity.get("conditionId", ""),
                token_id=activity.get("asset", activity.get("tokenId", "")),
                side="BUY",
                price=price,
                size_usdc=size_usdc,
                outcome=activity.get("outcome", "Unknown"),
                market_question=activity.get("title", activity.get("question", "")),
            )
        except (ValueError, TypeError) as e:
            return None
    
    def _classify_market(self, title: str) -> str:
        """市场分类"""
        from kong_score_v2 import _classify_market
        return _classify_market(title.lower())
    
    def _reset_daily(self):
        """重置每日计数"""
        self._daily_copies = 0
        self._daily_loss_usd = 0.0
        if self._kill_switch:
            self._kill_switch = False
            log("polystrat", "Kill-Switch 通过日切换重置")
        
        # 内存管理
        if len(self._seen_tx_hashes) > 10_000:
            oldest = list(self._seen_tx_hashes)[:1000]
            for h in oldest:
                self._seen_tx_hashes.discard(h)


# ── 向后兼容 whale_copy.py ──────────────────────────────────────────

def monitor_whales_v2(target_wallets: list = None) -> list:
    """
    增强版鲸鱼监控 — 替换 whale_copy.py 的 monitor_whales()
    
    新增功能:
    - KongScore V2 评分
    - 信号聚合
    - Decay 检测
    - 羊群效应防护
    """
    psi = PolyStratIntegration(config={"target_wallets": target_wallets or []})
    
    signals = []
    for wallet in (target_wallets or []):
        activity = psi._fetch_wallet_activity(wallet, 5)
        if not activity:
            continue
        
        # 计算 KongScore V2
        kongscore = calculate_kongscore_v2(wallet, activity)
        
        for trade in activity[:3]:
            signal = psi._parse_trade_signal(trade, wallet)
            if signal:
                wallet_mult = kongscore.get("multiplier", 0.5)
                copy_size = min(
                    abs(trade.get("size", 0)) * COPY_CONFIG["multiplier"] * wallet_mult,
                    COPY_CONFIG["max_position_usd"]
                )
                
                signals.append({
                    "whale": kongscore.get("name", wallet[:10] + "..."),
                    "kongscore": kongscore["score"],
                    "tier": kongscore["tier"],
                    "multiplier": wallet_mult,
                    "decay_status": kongscore.get("decay_status", "healthy"),
                    "market": trade.get("title", trade.get("market", "")),
                    "side": trade.get("side", ""),
                    "whale_size": abs(trade.get("size", 0)),
                    "copy_size": round(copy_size, 2),
                    "timestamp": trade.get("timestamp", ""),
                })
    
    return signals


def format_whale_signals_v2(signals: list) -> str:
    """格式化增强版跟单信号"""
    if not signals:
        return "无跟单信号"
    
    lines = ["🐋 鲸鱼跟单信号 (KongScore V2)", "=" * 60, f"发现 {len(signals)} 个跟单机会", ""]
    
    for s in signals[:10]:
        decay_icon = {"healthy": "✅", "declining": "📉", "decaying": "🛑"}.get(s.get("decay_status", ""), "❓")
        lines.append(f"  {decay_icon} {s['whale']} | Score: {s['kongscore']:.0f} | Tier: {s['tier']}")
        lines.append(f"    市场: {s['market'][:50]}...")
        lines.append(f"    方向: {s['side']} | 鲸鱼: ${s['whale_size']:.2f} | 跟单: ${s['copy_size']:.2f}")
        lines.append(f"    乘数: {s['multiplier']}x | 衰减: {s.get('decay_status', 'N/A')}")
        lines.append("")
    
    return "\n".join(lines)


if __name__ == "__main__":
    print("=" * 60)
    print("PolyStrat 集成模块测试")
    print("=" * 60)
    
    # 测试 1: 鲸鱼监控
    print("\n1️⃣ 鲸鱼监控 (增强版):")
    signals = monitor_whales_v2()
    print(format_whale_signals_v2(signals))
    
    # 测试 2: 套利扫描
    print("\n2️⃣ 套利扫描:")
    try:
        arb_opps = scan_negrisk_arbitrage(top_markets=10)
        if arb_opps:
            for opp in arb_opps[:3]:
                print(f"  {opp['type']}: {opp['market'][:50]} | ${opp['profit_usd']:.2f} | ROI: {opp['roi_pct']:.1%}")
        else:
            print("  (无套利机会 — 可能 API 受限)")
    except Exception as e:
        print(f"  扫描失败: {e}")
    
    # 测试 3: 状态报告
    print("\n3️⃣ 状态报告:")
    psi = PolyStratIntegration()
    print(psi.format_status())
    
    print("\n✅ PolyStrat 集成模块测试完成")
