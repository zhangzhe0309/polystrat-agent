#!/usr/bin/env python3
"""
negRisk 多结果套利检测器
基于 Polymarket NegRiskAdapter 合约 + IMDEA Networks 研究数据

核心策略:
1. NegRisk Rebalancing: Σ(prices) ≠ 1.00 → 买入所有 YES (underpriced) 或卖出所有 NO (overpriced)
2. 单条件套利: YES + NO ≠ $1.00 → 买入两端
3. 跨平台套利: Polymarket vs Kalshi/Binance 价格差异
4. Endgame 套利: 高概率 (>93%) 近 Resolution 市场的确定性利润

资本效率:
- NegRisk: 29× 效率优势, 占总套利利润 73% ($28.99M / $39.59M)
- 单条件: 高频但低效 ($10.58M / 7,051 次)

API:
- 100% 免费, 无需认证
- CLOB: https://clob.polymarket.com
- Gamma: https://gamma-api.polymarket.com

使用方式:
    detector = NegRiskArbitrageDetector()
    opportunities = await detector.scan()
    for opp in opportunities:
        print(f"{opp['type']}: {opp['profit_usd']:.2f} USD, ROI: {opp['roi_pct']:.1f}%")
"""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from collections import deque

try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False

# ── 常量 ──────────────────────────────────────────────────────────

from config_center import CLOB_BASE
GAMMA_BASE = "https://gamma-api.polymarket.com"

# 套利阈值
MIN_PROFIT_THRESHOLD = 0.02     # 最小利润 $0.02 (覆盖 Gas)
NEGRISK_MULTIPLIER = 29         # 资本效率倍数
HIGH_URGENCY_ROI = 0.10         # 10%+ ROI = 高优先级
MEDIUM_URGENCY_ROI = 0.05       # 5%+ ROI = 中优先级
FEE_PCT = 0.02                  # Polymarket 手续费 ~2%

# 风险阈值
MAX_RISK_SCORE = 0.6            # 最大可接受风险分数
SUBJECTIVE_KEYWORDS = ["best", "winner", "better", "more popular", "succeed"]

# ── 数据结构 ───────────────────────────────────────────────────────

@dataclass
class ArbitrageOpportunity:
    """套利机会"""
    market_id: str
    market_name: str
    opportunity_type: str        # "negrisk", "single_condition", "endgame", "cross_platform"
    expected_profit_usd: float
    roi_pct: float
    capital_required: float
    risk_score: float            # 0-1, 越低越好
    urgency: str                 # "high", "medium", "low"
    details: Dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    neg_risk: bool = False
    
    # NegRisk 特有字段
    outcome_prices: Dict[str, float] = field(default_factory=dict)  # outcome → price
    price_sum: float = 0.0
    deviation_pct: float = 0.0
    
    def __repr__(self):
        return (
            f"ArbOpp({self.opportunity_type} | {self.market_name[:40]} | "
            f"${self.expected_profit_usd:.2f} | ROI: {self.roi_pct:.1%} | "
            f"Risk: {self.risk_score:.2f} | {self.urgency})"
        )


class NegRiskArbitrageDetector:
    """
    negRisk 多结果套利检测器
    
    检测三种套利:
    1. NegRisk Rebalancing: Σ(prices) ≠ 1.00
    2. 单条件: YES + NO ≠ $1.00  
    3. Endgame: 高概率 + 近 Resolution
    """
    
    def __init__(self, top_markets: int = 50, min_profit: float = MIN_PROFIT_THRESHOLD):
        self.top_markets = top_markets
        self.min_profit = min_profit
        self._session: Optional[aiohttp.ClientSession] = None
        self._market_cache: Dict = {}
        self._book_cache: deque = deque(maxlen=200)
        self.stats = {"scans": 0, "opportunities_found": 0}
    
    async def scan(self) -> List[ArbitrageOpportunity]:
        """
        执行一次完整扫描
        
        Returns:
            按预期利润排序的套利机会列表
        """
        if not AIOHTTP_AVAILABLE:
            raise RuntimeError("aiohttp 未安装 — pip install aiohttp")
        
        opportunities = []
        self.stats["scans"] += 1
        
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15),
            headers={"User-Agent": "polystrat-arb/1.0"}
        ) as session:
            self._session = session
            
            # Step 1: 获取活跃市场
            markets = await self._fetch_active_markets()
            
            # Step 2: 分离 negRisk 和单条件市场
            neg_risk_events, single_markets = self._classify_markets(markets)
            
            # Step 3: 检测 NegRisk 套利
            for event_id, event_data in neg_risk_events.items():
                opp = await self._detect_negrisk_arbitrage(event_id, event_data)
                if opp and opp.expected_profit_usd >= self.min_profit:
                    opportunities.append(opp)
            
            # Step 4: 检测单条件套利
            for market in single_markets:
                opp = await self._detect_single_condition_arbitrage(market)
                if opp and opp.expected_profit_usd >= self.min_profit:
                    opportunities.append(opp)
            
            # Step 5: 检测 Endgame 套利
            for market in single_markets + [m for e in neg_risk_events.values() for m in e.get("markets", [])]:
                opp = await self._detect_endgame_arbitrage(market)
                if opp and opp.expected_profit_usd >= self.min_profit:
                    opportunities.append(opp)
        
        # 排序: 利润降序
        opportunities.sort(key=lambda o: o.expected_profit_usd, reverse=True)
        self.stats["opportunities_found"] += len(opportunities)
        
        return opportunities
    
    async def _fetch_active_markets(self) -> List[dict]:
        """获取活跃市场列表"""
        markets = []
        try:
            # 先获取事件列表 (negRisk 事件在这里)
            url = f"{GAMMA_BASE}/events"
            params = {"limit": self.top_markets, "active": "true"}
            async with self._session.get(url, params=params) as resp:
                if resp.status == 200:
                    events = await resp.json()
                    for event in events:
                        # negRisk 事件
                        if event.get("negRisk") or event.get("negRisk", False):
                            markets.append({
                                "type": "neg_risk_event",
                                "id": event.get("id", ""),
                                "title": event.get("title", ""),
                                "slug": event.get("slug", ""),
                                "neg_risk": True,
                                "markets": event.get("markets", []),
                            })
                        else:
                            for m in event.get("markets", []):
                                markets.append({"type": "single", **m})
            
            # 补充单条件市场
            url = f"{GAMMA_BASE}/markets"
            params = {"limit": self.top_markets, "active": "true", "closed": "false"}
            async with self._session.get(url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if isinstance(data, list):
                        for m in data:
                            if not any(existing.get("id") == m.get("id") for existing in markets):
                                markets.append({"type": "single", **m})
        except Exception as e:
            pass
        
        return markets
    
    def _classify_markets(self, markets: List[dict]) -> Tuple[Dict, List[dict]]:
        """分类市场为 negRisk 事件和单条件市场"""
        neg_risk_events = {}
        single_markets = []
        
        for m in markets:
            if m.get("type") == "neg_risk_event" or m.get("neg_risk"):
                event_id = m.get("id", "")
                if event_id not in neg_risk_events:
                    neg_risk_events[event_id] = {
                        "title": m.get("title", ""),
                        "markets": m.get("markets", []),
                    }
                # 合并 markets
                for sub in m.get("markets", []):
                    if sub not in neg_risk_events[event_id]["markets"]:
                        neg_risk_events[event_id]["markets"].append(sub)
            else:
                single_markets.append(m)
        
        return neg_risk_events, single_markets
    
    async def _detect_negrisk_arbitrage(self, event_id: str, event_data: dict) -> Optional[ArbitrageOpportunity]:
        """
        检测 NegRisk 套利
        
        逻辑: 对于互斥多结果事件，所有 YES 价格之和应等于 1.00
        - Σ < 1.00: 买入所有 YES → Resolution 后收回 $1.00
        - Σ > 1.00: 卖出所有 NO → NegRiskAdapter 转换获利
        
        资本效率 = NEGRISK_MULTIPLIER (29×) 因为只需要一次交易覆盖所有结果
        """
        sub_markets = event_data.get("markets", [])
        if len(sub_markets) < 3:
            return None
        
        # 获取每个子市场的最佳 Ask 价格
        outcome_prices = {}
        total_capital = 0.0
        
        for sub in sub_markets:
            token_id = sub.get("clobTokenIds", [""])[0] if sub.get("clobTokenIds") else sub.get("token_id", "")
            if not token_id:
                continue
            
            book = await self._fetch_orderbook(token_id)
            if not book:
                continue
            
            best_ask = self._get_best_ask(book)
            if best_ask and 0 < best_ask < 1:
                outcome = sub.get("outcome", sub.get("groupItemTitle", ""))
                outcome_prices[outcome] = best_ask
                total_capital += best_ask
        
        if not outcome_prices:
            return None
        
        price_sum = sum(outcome_prices.values())
        
        # 计算偏差
        if price_sum <= 0:
            return None
        
        deviation = 1.0 - price_sum  # 正值 = underpriced, 负值 = overpriced
        deviation_pct = abs(deviation) / price_sum
        
        # 利润计算 (扣除手续费)
        if deviation > 0:
            # Underpriced: 买所有 YES
            gross_profit_per_dollar = deviation
            net_profit_per_dollar = gross_profit_per_dollar - (price_sum * FEE_PCT)
        else:
            # Overpriced: 使用 NegRisk 转换
            gross_profit_per_dollar = abs(deviation)
            net_profit_per_dollar = gross_profit_per_dollar - (price_sum * FEE_PCT)
        
        if net_profit_per_dollar <= 0:
            return None
        
        # 资本需求: 投入金额 (受市场深度限制)
        capital_per_unit = price_sum  # 买 $1 面值需要的成本
        max_position_usd = min(1000, total_capital * 10)  # 限制最大仓位
        
        expected_profit = net_profit_per_dollar * max_position_usd
        roi_pct = net_profit_per_dollar / capital_per_unit if capital_per_unit > 0 else 0
        
        if expected_profit < self.min_profit:
            return None
        
        # 风险评分
        risk_score = self._calculate_risk_score(
            is_negrisk=True,
            num_outcomes=len(outcome_prices),
            market_title=event_data.get("title", ""),
        )
        
        if risk_score > MAX_RISK_SCORE:
            return None
        
        # 紧急度
        urgency = "high" if roi_pct >= HIGH_URGENCY_ROI else ("medium" if roi_pct >= MEDIUM_URGENCY_ROI else "low")
        
        return ArbitrageOpportunity(
            market_id=event_id,
            market_name=event_data.get("title", ""),
            opportunity_type="negrisk",
            expected_profit_usd=expected_profit,
            roi_pct=roi_pct,
            capital_required=max_position_usd,
            risk_score=risk_score,
            urgency=urgency,
            neg_risk=True,
            outcome_prices=outcome_prices,
            price_sum=price_sum,
            deviation_pct=deviation_pct,
            details={
                "action": "buy_all_yes" if deviation > 0 else "sell_all_no_via_negrisk",
                "num_outcomes": len(outcome_prices),
                "capital_efficiency_multiplier": NEGRISK_MULTIPLIER,
                "net_profit_per_dollar": net_profit_per_dollar,
            }
        )
    
    async def _detect_single_condition_arbitrage(self, market: dict) -> Optional[ArbitrageOpportunity]:
        """
        检测单条件套利
        
        逻辑: YES + NO 应等于 $1.00
        - Sum < $1.00: 买入 YES + NO → 确定收回 $1.00
        - Sum > $1.00: 卖出 YES + NO
        """
        condition_id = market.get("conditionId", market.get("id", ""))
        clob_token_ids = market.get("clobTokenIds", [])
        
        if len(clob_token_ids) < 2:
            return None
        
        # 获取 YES 和 NO 的最佳 Ask
        yes_book = await self._fetch_orderbook(clob_token_ids[0])
        no_book = await self._fetch_orderbook(clob_token_ids[1]) if len(clob_token_ids) > 1 else None
        
        if not yes_book or not no_book:
            return None
        
        yes_ask = self._get_best_ask(yes_book)
        no_ask = self._get_best_ask(no_book)
        
        if not yes_ask or not no_ask or yes_ask <= 0 or no_ask <= 0:
            return None
        
        price_sum = yes_ask + no_ask
        deviation = 1.0 - price_sum  # 正值 = 可套利
        
        if deviation <= FEE_PCT:  # 扣费后无利润
            return None
        
        net_profit_per_dollar = deviation - (price_sum * FEE_PCT)
        if net_profit_per_dollar <= 0:
            return None
        
        max_position = min(500, 100)  # 单条件仓位较小
        expected_profit = net_profit_per_dollar * max_position
        roi_pct = net_profit_per_dollar / price_sum if price_sum > 0 else 0
        
        risk_score = self._calculate_risk_score(
            is_negrisk=False,
            market_title=market.get("question", market.get("title", "")),
        )
        
        urgency = "high" if roi_pct >= HIGH_URGENCY_ROI else ("medium" if roi_pct >= MEDIUM_URGENCY_ROI else "low")
        
        return ArbitrageOpportunity(
            market_id=condition_id,
            market_name=market.get("question", market.get("title", "")),
            opportunity_type="single_condition",
            expected_profit_usd=expected_profit,
            roi_pct=roi_pct,
            capital_required=max_position,
            risk_score=risk_score,
            urgency=urgency,
            outcome_prices={"YES": yes_ask, "NO": no_ask},
            price_sum=price_sum,
            deviation_pct=abs(deviation) / price_sum if price_sum > 0 else 0,
            details={"action": "buy_both" if deviation > 0 else "sell_both"},
        )
    
    async def _detect_endgame_arbitrage(self, market: dict) -> Optional[ArbitrageOpportunity]:
        """
        检测 Endgame 套利
        
        逻辑: 当市场接近 Resolution 且某结果概率 >93%，
        买入该结果获得近确定性利润。
        
        风险: Oracle 攻击（March 2025 案例）
        → 必须在 Resolution 前 24-48h 退出
        """
        # 检查 End Date
        end_date_str = market.get("endDate", market.get("end_date_iso", ""))
        if not end_date_str:
            return None
        
        try:
            from dateutil import parser as dateparser
            end_date = dateparser.parse(end_date_str)
            if end_date.tzinfo is None:
                end_date = end_date.replace(tzinfo=timezone.utc)
            
            hours_to_resolution = (end_date - datetime.now(timezone.utc)).total_seconds() / 3600
        except Exception as e:
            print(f"⚠️ 日期解析失败: {e}")
            return None
        
        # 只关注 24h-168h 内 Resolution 的市场
        if not (24 <= hours_to_resolution <= 168):
            return None
        
        # 获取当前价格
        clob_token_ids = market.get("clobTokenIds", [])
        if not clob_token_ids:
            return None
        
        book = await self._fetch_orderbook(clob_token_ids[0])
        if not book:
            return None
        
        best_ask = self._get_best_ask(book)
        if not best_ask or best_ask < 0.93:
            return None
        
        # 利润计算
        profit_per_dollar = 1.0 - best_ask - (best_ask * FEE_PCT)
        if profit_per_dollar <= 0:
            return None
        
        # 年化收益
        annualized = profit_per_dollar * (365 * 24 / hours_to_resolution)
        if annualized < 0.10:  # 最低 10% 年化
            return None
        
        max_position = min(200, 50)
        expected_profit = profit_per_dollar * max_position
        
        risk_score = self._calculate_risk_score(
            is_negrisk=False,
            hours_to_resolution=hours_to_resolution,
            market_title=market.get("question", ""),
        )
        
        # Endgame 近 Resolution 风险更高
        if hours_to_resolution < 48:
            risk_score += 0.3
        
        if risk_score > MAX_RISK_SCORE:
            return None
        
        return ArbitrageOpportunity(
            market_id=market.get("conditionId", market.get("id", "")),
            market_name=market.get("question", market.get("title", "")),
            opportunity_type="endgame",
            expected_profit_usd=expected_profit,
            roi_pct=profit_per_dollar / best_ask if best_ask > 0 else 0,
            capital_required=max_position,
            risk_score=min(risk_score, 1.0),
            urgency="high" if hours_to_resolution < 48 else "medium",
            details={
                "best_ask": best_ask,
                "hours_to_resolution": hours_to_resolution,
                "annualized_return": annualized,
                "warning": "⚠️ Endgame 套利: 在 Resolution 前 24-48h 退出以防 Oracle 攻击",
            },
        )
    
    # ── 辅助方法 ──────────────────────────────────────────────
    
    async def _fetch_orderbook(self, token_id: str) -> Optional[dict]:
        """获取 Orderbook 数据"""
        if not token_id:
            return None
        
        # 缓存检查
        cache_key = f"book_{token_id}"
        for cached_key, cached_time, cached_data in self._book_cache:
            if cached_key == cache_key and (time.time() - cached_time) < 30:
                return cached_data
        
        try:
            url = f"{CLOB_BASE}/book"
            params = {"token_id": token_id}
            async with self._session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    self._book_cache.append((cache_key, time.time(), data))
                    return data
        except Exception as e:
            print(f"⚠️ 订单簿获取失败: {e}")
        
        return None
    
    def _get_best_ask(self, book: dict) -> Optional[float]:
        """获取最佳 Ask 价格"""
        asks = book.get("asks", [])
        if not asks:
            return None
        
        # 最便宜的 Ask
        try:
            prices = [float(a.get("price", 0)) for a in asks if float(a.get("price", 0)) > 0]
            return min(prices) if prices else None
        except (ValueError, TypeError):
            return None
    
    def _calculate_risk_score(
        self,
        is_negrisk: bool = False,
        num_outcomes: int = 0,
        hours_to_resolution: float = None,
        market_title: str = "",
    ) -> float:
        """
        计算风险评分 (0-1, 越低越好)
        
        基于 FlexiWay 研究的风险模型
        """
        risk = 0.0
        
        # Resolution 时间风险
        if hours_to_resolution is not None:
            if hours_to_resolution < 48:
                risk += 0.4
            elif hours_to_resolution < 168:
                risk += 0.2
        
        # NegRisk: 每个 token 增加复杂度
        if is_negrisk and num_outcomes > 0:
            risk += min(0.03 * num_outcomes, 0.2)
        
        # 主观 Oracle 检测
        title_lower = market_title.lower()
        for kw in SUBJECTIVE_KEYWORDS:
            if kw in title_lower:
                risk += 0.3
                break
        
        return min(risk, 1.0)
    
    def format_opportunities(self, opportunities: List[ArbitrageOpportunity]) -> str:
        """格式化套利机会报告"""
        if not opportunities:
            return "📊 未发现套利机会"
        
        lines = [
            "📊 **套利机会报告**",
            "=" * 50,
            f"发现 {len(opportunities)} 个机会",
            "",
        ]
        
        # 按类型统计
        by_type = {}
        for opp in opportunities:
            by_type.setdefault(opp.opportunity_type, []).append(opp)
        
        for opp_type, opps in by_type.items():
            total_profit = sum(o.expected_profit_usd for o in opps)
            total_capital = sum(o.capital_required for o in opps)
            type_names = {
                "negrisk": "🔄 NegRisk 再平衡",
                "single_condition": "⚡ 单条件套利",
                "endgame": "🎯 Endgame 套利",
                "cross_platform": "🌐 跨平台套利",
            }
            lines.append(f"{type_names.get(opp_type, opp_type)}: {len(opps)} 个, ${total_profit:.2f} 利润")
        
        lines.append("")
        lines.append(f"总资本需求: ${sum(o.capital_required for o in opportunities):.2f}")
        lines.append("")
        
        # 详细信息 (前 5 个)
        for opp in opportunities[:5]:
            urgency_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(opp.urgency, "⚪")
            lines.append(f"{urgency_emoji} {opp.opportunity_type}: {opp.market_name[:50]}")
            lines.append(f"   利润: ${opp.expected_profit_usd:.2f} | ROI: {opp.roi_pct:.1%} | 风险: {opp.risk_score:.2f}")
            
            if opp.outcome_prices:
                prices_str = " | ".join(f"{k}: ${v:.3f}" for k, v in opp.outcome_prices.items())
                lines.append(f"   价格: {prices_str}")
                lines.append(f"   价格和: ${opp.price_sum:.4f} (偏差: {opp.deviation_pct:.2%})")
            
            lines.append("")
        
        # 资本分配建议
        lines.append("📋 **资本分配建议**:")
        negrisk_total = sum(o.expected_profit_usd for o in by_type.get("negrisk", []))
        single_total = sum(o.expected_profit_usd for o in by_type.get("single_condition", []))
        endgame_total = sum(o.expected_profit_usd for o in by_type.get("endgame", []))
        
        total = negrisk_total + single_total + endgame_total
        if total > 0:
            lines.append(f"   NegRisk: 40% (${negrisk_total * 0.4:.2f})")
            lines.append(f"   单条件: 30% (${single_total * 0.3:.2f})")
            lines.append(f"   Endgame: 20% (${endgame_total * 0.2:.2f})")
            lines.append(f"   储备: 10%")
        
        return "\n".join(lines)


# ── 同步封装 (兼容 PolyStrat) ──────────────────────────────────────

def scan_negrisk_arbitrage(top_markets: int = 50) -> List[dict]:
    """
    同步接口 — 供 PolyStrat 主循环调用
    
    Returns:
        List[dict]: 套利机会列表
    """
    async def _run():
        detector = NegRiskArbitrageDetector(top_markets=top_markets)
        opportunities = await detector.scan()
        return [
            {
                "market_id": o.market_id,
                "market_name": o.market_name,
                "type": o.opportunity_type,
                "profit_usd": o.expected_profit_usd,
                "roi_pct": o.roi_pct,
                "capital_required": o.capital_required,
                "risk_score": o.risk_score,
                "urgency": o.urgency,
                "neg_risk": o.neg_risk,
                "price_sum": o.price_sum,
                "deviation_pct": o.deviation_pct,
                "outcome_prices": o.outcome_prices,
                "details": o.details,
            }
            for o in opportunities
        ]
    
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # 在已有事件循环中运行
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, _run())
                return future.result(timeout=30)
        else:
            return loop.run_until_complete(_run())
    except Exception as e:
        print(f"⚠️ 套利扫描执行失败: {e}")
        return asyncio.run(_run())


if __name__ == "__main__":
    print("=" * 60)
    print("negRisk 多结果套利检测器测试")
    print("=" * 60)
    
    async def test():
        detector = NegRiskArbitrageDetector(top_markets=20)
        opportunities = await detector.scan()
        print(detector.format_opportunities(opportunities))
    
    asyncio.run(test())
