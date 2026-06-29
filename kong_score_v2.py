#!/usr/bin/env python3
"""
KongScore V2 — 增强版钱包评分系统
集成自 KongTradeBot WALLET_SCOUT_BRIEFING.md v2.0

相比 PolyStrat 现有 whale_copy.py 的简易4维评分：
- 新增 Hard Filter (KO 条件) 预筛
- 10 维度 Soft Scoring (Large-Pool) / 5 维度 (Small-Pool)
- Decay Detection (胜率衰减检测)
- Tier 分级 → Multiplier 映射

使用方式:
    scorer = KongScoreV2(pool_size="small")  # 或 "large"
    result = scorer.evaluate(wallet_address, activity_data)
    if result["passed_hard_filters"]:
        print(f"KongScore: {result['score']}, Tier: {result['tier']}, Multiplier: {result['multiplier']}")
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
from collections import deque
from pathlib import Path

# ── Hard Filter 配置 ──────────────────────────────────────────────

HARD_FILTERS = {
    "HF-0": {"name": "总盈利", "min_profit_usd": 10_000, "min_roi_pct": 10.0},
    "HF-1": {"name": "Sample-Size", "min_resolved": 50},
    "HF-2": {"name": "账户年龄", "min_days": 60},
    "HF-3": {"name": "Max-Drawdown", "max_dd_pct": 30.0},
    "HF-5": {"name": "活跃度", "min_trades_14d": 3},
    "HF-7": {"name": "ROI", "min_roi": 0.0},
    "HF-9": {"name": "防Insider", "max_pct_last_10min": 20.0},
}

# ── Soft Scoring 维度 ─────────────────────────────────────────────

# Small-Pool: 5 维度, 100 分满分
SMALL_POOL_SCORING = {
    "SC-1": {"name": "Sample-Size",    "max_points": 25, "thresholds": [(200, 25), (100, 15), (50, 10), (0, 0)]},
    "SC-2": {"name": "类别专注度",      "max_points": 25, "thresholds": [(0.70, 25), (0.50, 15), (0, 0)]},
    "SC-3": {"name": "Entry价格区",     "max_points": 20, "thresholds": [(0.20, 20), (0.40, 8), (0.60, 0)]},  # 20-40¢ 最佳
    "SC-4": {"name": "ROI:MDD比率",    "max_points": 20, "thresholds": [(2.0, 20), (1.5, 10), (0, 0)]},
    "SC-7": {"name": "Exit证据",       "max_points": 10, "thresholds": [("active", 10), ("sometimes", 5), ("never", 0)]},
}

# Large-Pool: 10 维度, 125 分满分
LARGE_POOL_SCORING = {
    **SMALL_POOL_SCORING,
    "SC-5": {"name": "盈亏比",          "max_points": 10, "thresholds": [(2.5, 10), (2.0, 7), (1.5, 0)]},
    "SC-6": {"name": "仓位纪律",        "max_points": 10, "thresholds": [(0.10, 10), (0.15, 5), (1.0, 0)]},
    "SC-8": {"name": "拥挤度",          "max_points": 10, "thresholds": [("not_top10", 10), ("medium", 5), ("top10", 0)]},
    "SC-9": {"name": "压力测试",        "max_points": 10, "thresholds": [("profitable_in_shock", 10), ("survived", 5), ("not_tested", 0)]},
    "SC-10": {"name": "分批建仓",       "max_points": 5,  "thresholds": [("scaled", 5), ("mixed", 2), ("all_in", 0)]},
}

# ── Tier 映射 ─────────────────────────────────────────────────────

TIER_CONFIG = {
    "A": {"min_score": 70, "multiplier_range": (0.8, 1.0), "max_wallets": 5,  "description": "核心池"},
    "B": {"min_score": 50, "multiplier_range": (0.3, 0.5), "max_wallets": 10, "description": "实验池"},
    "C": {"min_score": 0,  "multiplier_range": (0.0, 0.0), "max_wallets": -1, "description": "影子池(仅观察)"},
}


@dataclass
class WalletMetrics:
    """从钱包活动数据提取的量化指标"""
    wallet_address: str = ""
    
    # 基础指标
    total_profit_usd: float = 0.0
    roi_on_deposits: float = 0.0
    resolved_trades: int = 0
    account_age_days: int = 0
    max_drawdown_pct: float = 0.0
    trades_last_14d: int = 0
    
    # 胜率
    win_rate: float = 0.0
    recent_win_rate: float = 0.0  # 最近 20 笔
    
    # 盈亏比
    avg_win_usd: float = 0.0
    avg_loss_usd: float = 0.0
    gain_loss_ratio: float = 0.0
    
    # 类别专注度
    category_focus_pct: float = 0.0  # 最主要类别的占比
    primary_category: str = ""
    
    # Entry 价格分布
    entry_price_avg: float = 0.0
    entry_price_in_alpha_zone: bool = False  # 20-40¢
    
    # ROI:MDD 比率
    roi_mdd_ratio: float = 0.0
    
    # 仓位纪律
    max_position_pct: float = 0.0  # 最大单仓占比
    
    # Exit 行为
    active_exit_pct: float = 0.0  # 主动退出比例
    
    # Insider 检测
    pct_trades_last_10min: float = 0.0  # Resolution 前 10 分钟交易占比
    
    # 压力测试
    survived_shock: bool = False
    profitable_in_shock: bool = False
    
    # Decay 检测
    is_decaying: bool = False       # 最近 20 笔胜率 < 45%
    is_trend_declining: bool = False # 最近胜率低于总胜率 > 10%


@dataclass
class KongScoreResult:
    """KongScore 评分结果"""
    wallet_address: str = ""
    passed_hard_filters: bool = False
    hard_filter_results: Dict[str, bool] = field(default_factory=dict)
    score: float = 0.0
    max_score: float = 100.0
    tier: str = "C"
    multiplier: float = 0.0
    score_breakdown: Dict[str, float] = field(default_factory=dict)
    recommendation: str = ""
    decay_status: str = "healthy"  # healthy, declining, decaying


class KongScoreV2:
    """
    增强版 KongScore 评分系统
    
    流程:
    1. Hard Filter 预筛 (KO 条件)
    2. Soft Scoring 量化评分
    3. Tier 分级 + Multiplier 映射
    4. Decay Detection 降权
    """
    
    def __init__(self, pool_size: str = "small", data_dir: str = None):
        """
        Args:
            pool_size: "small" (<20 候选) 或 "large" (≥20 候选)
            data_dir: 持久化目录
        """
        self.pool_size = pool_size
        self.scoring_config = SMALL_POOL_SCORING if pool_size == "small" else LARGE_POOL_SCORING
        self.max_score = sum(s["max_points"] for s in self.scoring_config.values())
        
        # Decay 追踪
        self._decay_history: Dict[str, List[dict]] = {}
        
        # 持久化
        from config_center import KONG_SCORE_DIR; self.data_dir = Path(data_dir) if data_dir else KONG_SCORE_DIR
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._load_state()
    
    def evaluate(self, wallet_address: str, metrics: WalletMetrics) -> KongScoreResult:
        """
        完整评分流程
        
        Args:
            wallet_address: 钱包地址
            metrics: 量化指标
        
        Returns:
            KongScoreResult
        """
        result = KongScoreResult(wallet_address=wallet_address.lower())
        
        # Step 1: Hard Filter
        result.hard_filter_results = self._check_hard_filters(metrics)
        result.passed_hard_filters = all(result.hard_filter_results.values())
        
        if not result.passed_hard_filters:
            failed = [k for k, v in result.hard_filter_results.items() if not v]
            result.recommendation = f"Hard Filter 未通过: {', '.join(failed)}"
            result.tier = "C"
            result.multiplier = 0.0
            return result
        
        # Step 2: Soft Scoring
        result.score_breakdown = self._calculate_soft_score(metrics)
        result.score = sum(result.score_breakdown.values())
        result.max_score = self.max_score
        
        # Step 3: Tier 分级
        result.tier = self._assign_tier(result.score)
        result.multiplier = self._calculate_multiplier(result.tier, result.score, metrics)
        
        # Step 4: Decay Detection
        result.decay_status = self._check_decay(wallet_address, metrics)
        if result.decay_status == "decaying":
            result.multiplier = 0.0
            result.recommendation = "🛑 Win Rate Decay — 停止跟单"
        elif result.decay_status == "declining":
            result.multiplier = round(result.multiplier / 2, 2)
            result.recommendation = f"📉 Trend-Decline — Multiplier 减半至 {result.multiplier}x"
        else:
            result.recommendation = self._generate_recommendation(result.tier, metrics)
        
        # 持久化
        self._save_snapshot(wallet_address, result)
        
        return result
    
    def _check_hard_filters(self, m: WalletMetrics) -> Dict[str, bool]:
        """检查 Hard Filter"""
        results = {}
        
        # HF-0: 总盈利 > $10K 或 ROI > 10%
        results["HF-0"] = m.total_profit_usd >= HARD_FILTERS["HF-0"]["min_profit_usd"] or \
                          m.roi_on_deposits >= HARD_FILTERS["HF-0"]["min_roi_pct"] / 100
        
        # HF-1: ≥50 resolved markets
        results["HF-1"] = m.resolved_trades >= HARD_FILTERS["HF-1"]["min_resolved"]
        
        # HF-2: 账户年龄 ≥ 60 天
        results["HF-2"] = m.account_age_days >= HARD_FILTERS["HF-2"]["min_days"]
        
        # HF-3: Max-Drawdown < 30%
        results["HF-3"] = m.max_drawdown_pct < HARD_FILTERS["HF-3"]["max_dd_pct"]
        
        # HF-5: 14 天内有 ≥3 新仓位
        results["HF-5"] = m.trades_last_14d >= HARD_FILTERS["HF-5"]["min_trades_14d"]
        
        # HF-7: 累计 ROI > 0
        results["HF-7"] = m.roi_on_deposits > HARD_FILTERS["HF-7"]["min_roi"]
        
        # HF-9: <20% 交易在 Resolution 前 10 分钟
        results["HF-9"] = m.pct_trades_last_10min < HARD_FILTERS["HF-9"]["max_pct_last_10min"]
        
        return results
    
    def _calculate_soft_score(self, m: WalletMetrics) -> Dict[str, float]:
        """计算 Soft Score"""
        scores = {}
        
        # SC-1: Sample-Size
        for threshold, points in self.scoring_config["SC-1"]["thresholds"]:
            if m.resolved_trades >= threshold:
                scores["SC-1"] = points
                break
        else:
            scores["SC-1"] = 0
        
        # SC-2: 类别专注度
        for threshold, points in self.scoring_config["SC-2"]["thresholds"]:
            if m.category_focus_pct >= threshold:
                scores["SC-2"] = points
                break
        else:
            scores["SC-2"] = 0
        
        # SC-3: Entry 价格区 (20-40¢ = alpha zone)
        if 0.20 <= m.entry_price_avg <= 0.40:
            scores["SC-3"] = self.scoring_config["SC-3"]["thresholds"][0][1]  # 20p
        elif 0.40 < m.entry_price_avg <= 0.60:
            scores["SC-3"] = self.scoring_config["SC-3"]["thresholds"][1][1]  # 8p
        else:
            scores["SC-3"] = 0
        
        # SC-4: ROI:MDD 比率
        for threshold, points in self.scoring_config["SC-4"]["thresholds"]:
            if m.roi_mdd_ratio >= threshold:
                scores["SC-4"] = points
                break
        else:
            scores["SC-4"] = 0
        
        # SC-7: Exit 证据
        if m.active_exit_pct >= 0.5:
            scores["SC-7"] = 10
        elif m.active_exit_pct >= 0.2:
            scores["SC-7"] = 5
        else:
            scores["SC-7"] = 0
        
        # Large-Pool 额外维度
        if self.pool_size == "large":
            # SC-5: 盈亏比
            for threshold, points in LARGE_POOL_SCORING["SC-5"]["thresholds"]:
                if m.gain_loss_ratio >= threshold:
                    scores["SC-5"] = points
                    break
            else:
                scores["SC-5"] = 0
            
            # SC-6: 仓位纪律
            if m.max_position_pct <= 0.10:
                scores["SC-6"] = 10
            elif m.max_position_pct <= 0.15:
                scores["SC-6"] = 5
            else:
                scores["SC-6"] = 0
            
            # SC-8: 拥挤度 (需要外部数据，默认给中等分)
            scores["SC-8"] = 5  # placeholder
            
            # SC-9: 压力测试
            if m.profitable_in_shock:
                scores["SC-9"] = 10
            elif m.survived_shock:
                scores["SC-9"] = 5
            else:
                scores["SC-9"] = 0
            
            # SC-10: 分批建仓 (需要更细粒度数据)
            scores["SC-10"] = 2  # placeholder
        
        return scores
    
    def _assign_tier(self, score: float) -> str:
        """根据分数分配 Tier"""
        if score >= TIER_CONFIG["A"]["min_score"]:
            return "A"
        elif score >= TIER_CONFIG["B"]["min_score"]:
            return "B"
        return "C"
    
    def _calculate_multiplier(self, tier: str, score: float, metrics: WalletMetrics) -> float:
        """计算跟单乘数"""
        config = TIER_CONFIG[tier]
        min_mult, max_mult = config["multiplier_range"]
        
        if tier == "C":
            return 0.0
        
        # 在 Tier 范围内根据分数线性插值
        min_score = config["min_score"]
        next_tier_min = TIER_CONFIG.get(
            "A" if tier == "B" else "B",
            {"min_score": 100}
        )["min_score"]
        
        if next_tier_min > min_score:
            ratio = (score - min_score) / (next_tier_min - min_score)
        else:
            ratio = 1.0
        
        return round(min_mult + (max_mult - min_mult) * min(ratio, 1.0), 2)
    
    def _check_decay(self, wallet_address: str, metrics: WalletMetrics) -> str:
        """
        Decay 检测
        
        Returns:
            "healthy" | "declining" | "decaying"
        """
        # 完全衰减: 最近 20 笔胜率 < 45% (需 >=10 笔)
        if len(getattr(metrics, '_recent_results', [])) >= 10 or metrics.recent_win_rate > 0:
            if metrics.is_decaying:
                return "decaying"
        
        # 趋势下降: 最近胜率低于总胜率 > 10%
        if metrics.is_trend_declining:
            return "declining"
        
        # 连续天数检测
        history = self._decay_history.get(wallet_address.lower(), [])
        if len(history) >= 3:
            if all(h.get("declining") for h in history[-3:]):
                return "declining"
        
        return "healthy"
    
    def _generate_recommendation(self, tier: str, metrics: WalletMetrics) -> str:
        """生成推荐"""
        if tier == "A":
            if metrics.win_rate >= 0.65 and metrics.roi_mdd_ratio >= 2.0:
                return "✅ 强烈推荐跟单 — 高胜率+高风险调整收益"
            return "✅ 推荐跟单 — 满足核心指标"
        elif tier == "B":
            if metrics.category_focus_pct >= 0.70:
                return "🔄 实验跟单 — 领域专家，观察 30 天后决定"
            return "🔄 实验跟单 — 降低仓位观察"
        return "👁️ 仅观察 — 不建议跟单"
    
    def record_decay_snapshot(self, wallet_address: str, total_wr: float, recent_wr: float):
        """记录 Decay 快照（每日调用）"""
        wallet = wallet_address.lower()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        declining = total_wr > 0 and (total_wr - recent_wr) > 0.10
        
        if wallet not in self._decay_history:
            self._decay_history[wallet] = []
        
        # 去重同一天
        history = [h for h in self._decay_history[wallet] if h["date"] != today]
        history.append({"date": today, "total_wr": total_wr, "recent_wr": recent_wr, "declining": declining})
        history = sorted(history, key=lambda x: x["date"])[-14:]
        self._decay_history[wallet] = history
        self._save_state()
    
    def get_wallet_trend(self, wallet_address: str) -> Dict:
        """获取钱包趋势数据"""
        history = self._decay_history.get(wallet_address.lower(), [])
        if not history:
            return {"status": "no_data"}
        
        consecutive_decline = 0
        for h in reversed(history):
            if h.get("declining"):
                consecutive_decline += 1
            else:
                break
        
        return {
            "status": "declining" if consecutive_decline >= 3 else "stable",
            "consecutive_decline_days": consecutive_decline,
            "history": history[-7:],
        }
    
    # ── 持久化 ──────────────────────────────────────────────
    
    def _save_snapshot(self, wallet_address: str, result: KongScoreResult):
        """保存评分快照"""
        filepath = self.data_dir / f"{wallet_address.lower()[:10]}_score.json"
        try:
            data = {
                "wallet": result.wallet_address,
                "score": result.score,
                "tier": result.tier,
                "multiplier": result.multiplier,
                "passed_hf": result.passed_hard_filters,
                "decay_status": result.decay_status,
                "breakdown": result.score_breakdown,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            with open(filepath, "w") as f:
                json.dump(data, f, indent=2)
        except (OSError, IOError) as e:
            print(f"⚠️ 分数历史保存失败: {e}")
    
    def _save_state(self):
        filepath = self.data_dir / "decay_history.json"
        try:
            with open(filepath, "w") as f:
                json.dump(self._decay_history, f, indent=2)
        except (OSError, IOError) as e:
            print(f"⚠️ 衰减历史保存失败: {e}")
    
    def _load_state(self):
        filepath = self.data_dir / "decay_history.json"
        if filepath.exists():
            try:
                with open(filepath) as f:
                    self._decay_history = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                print(f"⚠️ 衰减历史加载失败: {e}")
                self._decay_history = {}


def extract_wallet_metrics(wallet_address: str, activity: List[dict]) -> WalletMetrics:
    """
    从 Polymarket 活动 API 数据提取钱包量化指标
    
    Args:
        wallet_address: 钱包地址
        activity: data-api.polymarket.com/activity 返回的交易列表
    
    Returns:
        WalletMetrics
    """
    m = WalletMetrics(wallet_address=wallet_address.lower())
    
    if not activity:
        return m
    
    # 基础统计
    total = len(activity)
    wins = [a for a in activity if a.get("pnl", 0) > 0]
    losses = [a for a in activity if a.get("pnl", 0) < 0]
    resolved = [a for a in activity if a.get("resolved", False)]
    
    m.resolved_trades = len(resolved) if resolved else total
    m.win_rate = len(wins) / total if total > 0 else 0
    
    # 盈亏
    m.total_profit_usd = sum(a.get("pnl", 0) for a in activity)
    m.avg_win_usd = sum(a.get("pnl", 0) for a in wins) / len(wins) if wins else 0
    m.avg_loss_usd = abs(sum(a.get("pnl", 0) for a in losses)) / len(losses) if losses else 0
    m.gain_loss_ratio = m.avg_win_usd / m.avg_loss_usd if m.avg_loss_usd > 0 else 1.0
    
    # ROI on deposits
    total_deposits = sum(abs(a.get("size", 0)) for a in activity)
    m.roi_on_deposits = m.total_profit_usd / total_deposits if total_deposits > 0 else 0
    
    # 账户年龄
    timestamps = []
    for a in activity:
        ts = a.get("timestamp", "")
        if ts:
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                timestamps.append(dt)
            except (ValueError, TypeError):
                pass
    
    if timestamps:
        oldest = min(timestamps)
        m.account_age_days = (datetime.now(timezone.utc) - oldest).days
    
    # 最近 20 笔胜率
    recent = activity[:20]
    recent_wins = sum(1 for a in recent if a.get("pnl", 0) > 0)
    m.recent_win_rate = recent_wins / len(recent) if recent else 0
    
    # Decay 检测
    if len(recent) >= 10:
        m.is_decaying = m.recent_win_rate < 0.45
    if total >= 20 and len(recent) >= 10:
        m.is_trend_declining = m.recent_win_rate < (m.win_rate - 0.10)
    
    # 14 天内交易数
    two_weeks_ago = datetime.now(timezone.utc) - timedelta(days=14)
    m.trades_last_14d = sum(
        1 for a in activity
        if a.get("timestamp", "") and 
        datetime.fromisoformat(a["timestamp"].replace("Z", "+00:00")) > two_weeks_ago
    )
    
    # Entry 价格
    prices = [float(a.get("price", 0)) for a in activity if 0 < float(a.get("price", 0)) < 1]
    if prices:
        m.entry_price_avg = sum(prices) / len(prices)
        m.entry_price_in_alpha_zone = 0.20 <= m.entry_price_avg <= 0.40
    
    # ROI:MDD 比率 (简化估算)
    if m.max_drawdown_pct > 0:
        m.roi_mdd_ratio = abs(m.roi_on_deposits * 100) / m.max_drawdown_pct
    else:
        m.roi_mdd_ratio = 2.0 if m.roi_on_deposits > 0 else 0.0
    
    # 主动退出比例
    sells = sum(1 for a in activity if a.get("type", "").upper() in ("SELL", "EXIT"))
    m.active_exit_pct = sells / total if total > 0 else 0
    
    # 类别专注度 (需要 title 数据)
    categories = {}
    for a in activity:
        title = a.get("title", a.get("market", "")).lower()
        cat = _classify_market(title)
        categories[cat] = categories.get(cat, 0) + 1
    
    if categories:
        top_cat = max(categories, key=categories.get)
        m.primary_category = top_cat
        m.category_focus_pct = categories[top_cat] / total
    
    return m


def _classify_market(title: str) -> str:
    """简单市场分类"""
    if any(w in title for w in ["tennis", "nba", "nfl", "soccer", "football", "baseball", "golf", "cricket"]):
        return "Sport"
    elif any(w in title for w in ["iran", "israel", "ukraine", "trump", "nuclear", "war", "election", "president"]):
        return "Geopolitik"
    elif any(w in title for w in ["bitcoin", "btc", "eth", "crypto", "price", "solana"]):
        return "Crypto"
    elif any(w in title for w in ["fed", "interest rate", "inflation", "gdp", "recession"]):
        return "Makro"
    elif any(w in title for w in ["temperature", "rain", "snow", "weather", "wind"]):
        return "Weather"
    return "Other"


# ── 向后兼容 PolyStrat whale_copy.py ──────────────────────────────

def calculate_kongscore_v2(wallet_address: str, activity: list = None) -> dict:
    """
    向后兼容接口 — 替换 whale_copy.py 中的 calculate_kongscore()
    
    Args:
        wallet_address: 钱包地址
        activity: 活动 API 返回的数据 (可选，如不提供则自动获取)
    
    Returns:
        dict: 与原接口兼容的评分结果
    """
    if activity is None:
        # 尝试从 API 获取
        try:
            import requests
            resp = requests.get(
                "https://data-api.polymarket.com/activity",
                params={"user": wallet_address, "limit": 100},
                timeout=15
            )
            activity = resp.json() if resp.status_code == 200 else []
        except requests.RequestException as e:
            print(f"⚠️ 获取钱包活动失败: {e}")
            activity = []
    
    metrics = extract_wallet_metrics(wallet_address, activity)
    scorer = KongScoreV2(pool_size="small")
    result = scorer.evaluate(wallet_address, metrics)
    
    # 兼容原 whale_copy.py 返回格式
    return {
        "score": result.score,
        "tier": result.tier,
        "multiplier": result.multiplier,
        "win_rate": metrics.win_rate,
        "profit_ratio": metrics.gain_loss_ratio,
        "frequency": metrics.trades_last_14d / 2.0 if metrics.account_age_days > 0 else 0,  # approx daily
        "total_volume": sum(abs(a.get("size", 0)) for a in activity) if activity else 0,
        "passed_hard_filters": result.passed_hard_filters,
        "hard_filter_results": result.hard_filter_results,
        "decay_status": result.decay_status,
        "score_breakdown": result.score_breakdown,
        "recommendation": result.recommendation,
    }


if __name__ == "__main__":
    print("=" * 60)
    print("KongScore V2 测试")
    print("=" * 60)
    
    # 使用 KongTradeBot 的已知钱包测试
    test_wallets = {
        "0x019782cab5d844f02bafb71f512758be78579f3c": {"name": "majorexploiter", "expected_tier": "A"},
        "0xee613b3fc183ee44f9da9c05f53e2da107e3debf": {"name": "sovereign2013", "expected_tier": "B/C"},
    }
    
    for addr, info in test_wallets.items():
        print(f"\n📊 评分: {info['name']} ({addr[:10]}...)")
        result = calculate_kongscore_v2(addr)
        print(f"   Score: {result['score']:.0f}/{100}")
        print(f"   Tier: {result['tier']} (预期: {info['expected_tier']})")
        print(f"   Multiplier: {result['multiplier']}x")
        print(f"   Decay: {result['decay_status']}")
        print(f"   Hard Filters: {'✅' if result['passed_hard_filters'] else '❌'}")
        if result['score_breakdown']:
            for sc, pts in result['score_breakdown'].items():
                print(f"     {sc}: {pts}p")
    
    print("\n✅ KongScore V2 测试完成")
