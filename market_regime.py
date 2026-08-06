"""
Market Regime Manager - 市场状态机与突发事件防御引擎
参考借鉴 Polymarket 开源做市商 poly-maker 状态机架构：
将市场划分为 QUIET / TRENDING / EVENT / REDUCE_ONLY 四种动态工作模式
"""

import enum
import logging
import time
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)


class MarketRegime(str, enum.Enum):
    QUIET = "QUIET"          # 平静做市/套利模式：正常风控与 100% 下单额度
    TRENDING = "TRENDING"    # 动量单边模式：仓位自动降额 50%，扩阔安全边界
    EVENT = "EVENT"          # 突发事件爆破：触发熔断，拦截新订单并启动冷却机制
    REDUCE_ONLY = "REDUCE_ONLY"  # 仅平仓模式：禁止新建仓，仅允许止盈止损


class MarketRegimeManager:
    """
    市场动态状态机控制器
    """

    def __init__(self, cool_off_duration_sec: int = 900):
        self.cool_off_duration_sec = cool_off_duration_sec
        self.event_halt_until: float = 0.0
        self.last_prices: Dict[str, float] = {}
        self.last_update_ts: Dict[str, float] = {}

    def evaluate_regime(
        self,
        market: Any,
        llm_disagreement: float = 0.0,
        current_exposure_pct: float = 0.0,
        hours_to_end: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        评估指定市场的动态 State Regime
        """
        if isinstance(market, list):
            market_obj: Dict[str, Any] = market[0] if len(market) > 0 and isinstance(market[0], dict) else {}
        elif isinstance(market, dict):
            market_obj = market
        else:
            market_obj = {}

        now = time.time()
        market_id = str(market_obj.get("condition_id") or market_obj.get("slug") or "default")
        yes_price = float(market_obj.get("yes_price") or 0.5)

        # 1. 检查全局 EVENT 熔断冷却状态
        if now < self.event_halt_until:
            remaining = int(self.event_halt_until - now)
            log.warning(f"🚨 [Regime EVENT] 全局突发事件熔断保护中，剩余冷却 {remaining} 秒")
            return {
                "regime": MarketRegime.EVENT,
                "allow_new_trade": False,
                "size_multiplier": 0.0,
                "reason": f"Global EVENT cool-off active ({remaining}s left)"
            }

        # 2. 检查 REDUCE_ONLY (临近结算 < 24h 或 资金占用 > 90%)
        if (hours_to_end is not None and hours_to_end < 24.0) or current_exposure_pct >= 0.90:
            reason = f"Near settlement ({hours_to_end:.1f}h)" if (hours_to_end and hours_to_end < 24.0) else f"Exposure high ({current_exposure_pct*100:.0f}%)"
            return {
                "regime": MarketRegime.REDUCE_ONLY,
                "allow_new_trade": False,
                "size_multiplier": 0.0,
                "reason": f"[REDUCE_ONLY] {reason}"
            }

        # 3. 价格剧烈动量变化率检测 (TRENDING / EVENT)
        last_p = self.last_prices.get(market_id)
        last_ts = self.last_update_ts.get(market_id)
        self.last_prices[market_id] = yes_price
        self.last_update_ts[market_id] = now

        if last_p is not None and last_ts is not None:
            time_delta = now - last_ts
            price_change = abs(yes_price - last_p)
            liquidity = float(market_obj.get("liquidityNum") or market_obj.get("liquidity") or 0.0)

            # 5 分钟内价格突变 > 15% 或 LLM 分歧 > 45% -> 触发 EVENT 爆破熔断
            # 补丁：必须伴随流动性抽干或高分歧，避免低流动性市场的恶意“画门”插针
            if (time_delta < 300 and price_change > 0.15 and liquidity < 50000) or llm_disagreement > 0.45:
                self.event_halt_until = now + self.cool_off_duration_sec
                log.warning(f"💥 [Regime EVENT Triggered] 触发突发事件熔断: ΔP={price_change:.2f}, LLM分歧={llm_disagreement*100:.1f}%, Liq=${liquidity:,.0f}")
                return {
                    "regime": MarketRegime.EVENT,
                    "allow_new_trade": False,
                    "size_multiplier": 0.0,
                    "reason": f"[EVENT] Sudden volatility spike ΔP={price_change:.2f} with low liq"
                }

            # 5 分钟内价格单边动量 > 6% -> 触发 TRENDING 趋势模式 (仓位降额 50%)
            if (time_delta < 300 and price_change > 0.06) or llm_disagreement > 0.30:
                return {
                    "regime": MarketRegime.TRENDING,
                    "allow_new_trade": True,
                    "size_multiplier": 0.5,
                    "reason": f"[TRENDING] Strong momentum detected (ΔP={price_change:.2f}, 50% position scale)"
                }

        # 4. 常规 QUIET 模式
        return {
            "regime": MarketRegime.QUIET,
            "allow_new_trade": True,
            "size_multiplier": 1.0,
            "reason": "[QUIET] Market calm and normal trading active"
        }


# 全局单例与快捷工具函数
_default_manager = MarketRegimeManager()


def detect_market_regime(market: Dict[str, Any], llm_disagreement: float = 0.0, current_exposure_pct: float = 0.0, hours_to_end: Optional[float] = None) -> Dict[str, Any]:
    """快捷调用市场状态机判定"""
    return _default_manager.evaluate_regime(
        market=market,
        llm_disagreement=llm_disagreement,
        current_exposure_pct=current_exposure_pct,
        hours_to_end=hours_to_end
    )


def format_regime_report(regime_info: Dict[str, Any]) -> str:
    """格式化 Regime 状态机报告"""
    regime = regime_info.get("regime", MarketRegime.QUIET)
    reason = regime_info.get("reason", "")
    multiplier = regime_info.get("size_multiplier", 1.0)
    emoji_map = {
        MarketRegime.QUIET: "🟢",
        MarketRegime.TRENDING: "🟡",
        MarketRegime.EVENT: "🔴",
        MarketRegime.REDUCE_ONLY: "⏸️"
    }
    emoji = emoji_map.get(regime, "📌")
    return f"{emoji} [Regime: {regime}] 下单乘数: {multiplier:.0%} ({reason})"

