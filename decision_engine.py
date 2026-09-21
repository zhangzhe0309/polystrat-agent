#!/usr/bin/env python3
"""
自主决策引擎 (Autonomous Decision Engine) — PolyStrat v4.2+P1-1
=============================================================
职责边界（方案A 重构）:
- regime 感知风控门禁: 流动性硬下限、高风险环境提示
- 不重复主循环的 edge/阈值/Kelly 决策（由 legacy 路径统一负责）
- 输出 urgency/slippage/方向平衡等可解释性元数据

🔧 P1-1 方案A 变更（消除双决策路径冲突）:
- 移除 phase3 信号重融合（fused_prob 无消费方，与 legacy final_prob 冗余）
- 移除 phase4 独立阈值（与 legacy edge_threshold 冲突，可能矛盾决策）
- 移除方向平衡 boost（direction_choice 无消费方，主循环自定方向）
- 保留 phase1 regime 风控、urgency/slippage、方向计数（可解释性）

主循环接口契约（不可变）:
- make_decision(market, signals, regime_data, strategy_pool) → {final_decision, reason, ...}
- record_direction(direction) / get_balance_status()

作者: PolyStrat Team
日期: 2026-07-10
"""

import json
import time
from datetime import datetime, timezone
from collections import defaultdict

# Jev 传输/key/熔断统一由 jev_client 负责
from jev_client import jev_ask, JevUnavailableError


class AutonomousDecisionEngine:
    """自主交易决策引擎 — regime 感知风控门禁"""

    # 方向平衡追踪参数（仅用于 get_balance_status 可解释性统计）
    MIN_YES_TRADES_RATIO = 0.3  # Yes交易最小比例（相对于总交易）

    def __init__(self, regime_detector=None, strategy_discoverer=None):
        # 保留参数兼容现有调用（当前未使用，留给未来扩展）
        self.regime_detector = regime_detector
        self.strategy_discoverer = strategy_discoverer
        # 方向平衡追踪（仅统计，不反向影响决策）
        self.direction_counters = defaultdict(int)
        self.total_decisions = 0
        self.yes_decisions = 0
        self.no_decisions = 0

    def fast_triage_market(self, market: dict) -> dict:
        """
        ⚡ JEV System 1 盘口初筛门禁
        在前置扫描循环中剥离长尾死盘、无催化剂市场，避免无效调用重量级大模型。
        传输/key/熔断统一由 jev_client 负责；任何不可用一律 fail-open 放行
        （初筛是优化过滤器，过滤器宕机不应变成全面停盘）。

        Returns:
            dict: {
                'pass': bool,
                'category': str ('high_potential' / 'speculative_acceptable' / 'untradable_junk' / 'unknown'),
                'is_catalyst_driven': float,
                'confidence': float,
                'reason': str
            }
        """
        title = market.get('title', '')
        desc = market.get('description', '')[:300]
        price = market.get('price', 0.5)
        liquidity = market.get('liquidity', 0)

        # 基础静态初筛
        if liquidity < 3000:
            return {
                'pass': False,
                'category': 'untradable_junk',
                'is_catalyst_driven': 0.0,
                'confidence': 1.0,
                'reason': f'流动性极低 (${liquidity:,.0f} < $3k)'
            }

        state = (
            f"Title: {title}\n"
            f"Description: {desc}\n"
            f"Current Price: {price:.2f}\n"
            f"Liquidity: ${liquidity:,.0f}"
        )

        questions = {
            "tradability": {
                "type": "choice",
                "instructions": "Evaluate the tradability quality of this prediction market for an algorithmic trading bot",
                "criteria": {
                    "high_potential": "High-interest active market, clear upcoming event date, substantial real-world public discussion or catalyst",
                    "speculative_acceptable": "Niche or secondary market with moderate activity and plausible trading opportunity",
                    "untradable_junk": "Vague or arbitrary resolution rules, zero ongoing catalysts, ultra-long-horizon dormant market, or meme garbage"
                }
            },
            "is_catalyst_driven": {
                "type": "noul",
                "instructions": "Is there an ongoing news cycle, impending deadline, or public event actively driving this market odds?"
            }
        }

        try:
            answers = jev_ask(state, questions, timeout=3.0)
        except JevUnavailableError as e:
            return {'pass': True, 'category': 'unknown', 'is_catalyst_driven': 0.5, 'confidence': 0.0, 'reason': f'JEV不可用({e.reason})，降级放行'}
        except Exception as e:
            return {'pass': True, 'category': 'unknown', 'is_catalyst_driven': 0.5, 'confidence': 0.0, 'reason': f'JEV异常: {str(e)[:40]}，降级放行'}

        tradability_ans = answers.get('tradability', {})
        catalyst_ans = answers.get('is_catalyst_driven', {})
        try:
            category = tradability_ans.get('choice', 'speculative_acceptable')
            conf = float(tradability_ans.get('confidence', 0.5))
            catalyst_prob = float(catalyst_ans.get('noul', 0.5))
        except (ValueError, TypeError):
            return {'pass': True, 'category': 'unknown', 'is_catalyst_driven': 0.5, 'confidence': 0.0, 'reason': 'JEV返回非数值，降级放行'}

        # 硬阻断门禁：判定为 junk 或 (催化剂极低 且 置信度高)
        if category == "untradable_junk" and conf >= 0.60:
            return {
                'pass': False,
                'category': category,
                'is_catalyst_driven': catalyst_prob,
                'confidence': conf,
                'reason': f'JEV判定为无价值长尾死盘 (置信度: {conf:.2f})'
            }
        if catalyst_prob < 0.15 and conf >= 0.70:
            return {
                'pass': False,
                'category': category,
                'is_catalyst_driven': catalyst_prob,
                'confidence': conf,
                'reason': f'JEV判定缺乏新闻催化剂与波动性 (催化概率: {catalyst_prob:.2f})'
            }

        return {
            'pass': True,
            'category': category,
            'is_catalyst_driven': catalyst_prob,
            'confidence': conf,
            'reason': f'JEV初筛放行: {category} (催化度: {catalyst_prob:.2f}, 置信度: {conf:.2f})'
        }

    def make_decision(self, market, signals, regime_data, strategy_pool):
        """
        自主决策入口 — regime 感知风控门禁

        🔧 P1-1 方案A: engine 不再做信号融合/独立阈值决策
        （这些由主循环 legacy 路径统一负责，避免双路径冲突）

        Args:
            market: 市场信息 dict
            signals: 信号字典（legacy 已融合，engine 不再使用，保留兼容）
            regime_data: 市场环境数据 (from MarketRegimeDetector)
            strategy_pool: 策略池（保留兼容，engine 不再使用）

        Returns:
            dict: 决策结果
                - final_decision: 'skip'/'execute'
                - reason: str
                - regime/risk_level/urgency/slippage_estimate: 可解释性元数据
        """
        decision = {
            'market': market.get('title', ''),
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'final_decision': 'execute',
            'reason': '',
            'regime': regime_data.get('regime', 'unknown'),
            'risk_level': regime_data.get('risk_level', 'unknown'),
            'urgency': 0.0,
            'slippage_estimate': 0.0,
            'phase_results': {},
        }

        # Phase 1: regime 风控门禁（流动性/高风险环境硬过滤）
        regime_check = self._phase1_regime_check(market, regime_data, decision)
        decision['phase_results']['regime_check'] = regime_check

        if not regime_check.get('suitable', True):
            decision['final_decision'] = 'skip'
            decision['reason'] = f"市场环境不适合交易: {regime_check.get('reason', '低流动性')}"
            return decision

        # 可解释性元数据（不参与 skip/execute 决策，仅记录与展示）
        decision['urgency'] = self._calculate_urgency(market, regime_data)
        decision['slippage_estimate'] = self._estimate_slippage(market.get('liquidity', 0))
        decision['reason'] = (
            f"风控通过 (regime={decision['regime']}, "
            f"urgency={decision['urgency']:.1f}, 滑点≈{decision['slippage_estimate']:.1%})"
        )

        return decision

    def _phase1_regime_check(self, market, regime_data, decision):
        """Phase 1: 市场环境风控检查"""
        result = {
            'regime': regime_data.get('regime', 'unknown'),
            'risk_level': regime_data.get('risk_level', 'unknown'),
            'suitable': True,
            'reason': '',
        }

        # 低流动性市场直接跳过（硬下限）
        liquidity = market.get('liquidity', 0)
        if liquidity < 5000:
            result['suitable'] = False
            result['reason'] = f'流动性过低 (${liquidity:,.0f})'
            return result

        # 高风险+低流动性环境记录提示（不强制跳过，由 legacy should_trade 综合判断）
        risk = regime_data.get('risk_level', 'low')
        if risk == 'high' and liquidity < 20000:
            result['reason'] = '高风险+低流动性环境'

        return result

    def _calculate_urgency(self, market, regime_data):
        """计算执行紧急度 (0-1)"""
        urgency = 0.0

        # 快到结算日
        end_date = market.get('end_date', '')
        if end_date:
            try:
                dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                days_left = max(0, (dt - datetime.now(timezone.utc)).days)
                if days_left <= 1:
                    urgency += 0.5
                elif days_left <= 3:
                    urgency += 0.3
                elif days_left <= 7:
                    urgency += 0.1
            except Exception:
                pass

        # 高波动环境
        if regime_data.get('regime') == 'volatile':
            urgency += 0.2

        # 事件驱动
        if regime_data.get('regime') == 'event_driven':
            urgency += 0.15

        return min(1.0, urgency)

    def _estimate_slippage(self, liquidity):
        """估算滑点成本"""
        if liquidity > 100000:
            return 0.001  # 0.1%
        elif liquidity > 50000:
            return 0.003  # 0.3%
        elif liquidity > 10000:
            return 0.008  # 0.8%
        else:
            return 0.02     # 2%

    def record_direction(self, direction):
        """记录方向决策，用于平衡追踪（仅统计，不反向影响决策）"""
        self.total_decisions += 1
        if direction == 'Yes':
            self.yes_decisions += 1
        else:
            self.no_decisions += 1

    def get_balance_status(self):
        """获取方向平衡状态（可解释性输出）"""
        if self.total_decisions == 0:
            return {
                'total': 0,
                'yes_count': 0,
                'no_count': 0,
                'yes_ratio': 0.5,
                'balanced': True,
                'message': '暂无交易数据'
            }
        yes_ratio = self.yes_decisions / self.total_decisions
        return {
            'total': self.total_decisions,
            'yes_count': self.yes_decisions,
            'no_count': self.no_decisions,
            'yes_ratio': round(yes_ratio, 3),
            'balanced': yes_ratio >= self.MIN_YES_TRADES_RATIO,
            'message': f"Yes={self.yes_decisions}({yes_ratio:.0%}) No={self.no_decisions}"
        }

    def get_decision_explanation(self, decision):
        """生成决策的可解释性报告"""
        if decision.get('final_decision') == 'skip':
            return f"⏭️ 跳过: {decision.get('reason', '原因未知')}"

        lines = [
            f"🛡️ 风控通过: regime={decision.get('regime', '?')}, risk={decision.get('risk_level', '?')}",
            f"🔥 紧急度: {decision.get('urgency', 0):.1f}",
            f"💸 预估滑点: {decision.get('slippage_estimate', 0):.1%}",
            f"📝 理由: {decision.get('reason', '')}",
        ]
        return '\n'.join(lines)


def make_autonomous_decision(market, signals, regime_data, strategy_pool):
    """快捷决策函数（保留兼容接口）"""
    engine = AutonomousDecisionEngine()
    return engine.make_decision(market, signals, regime_data, strategy_pool)


if __name__ == '__main__':
    # 自测：验证 regime 风控门禁行为
    test_market = {
        'title': 'Will Argentina win 2026 World Cup?',
        'yes_price': 0.21,
        'liquidity': 50000,
        'end_date': '2026-07-20T00:00:00Z',
        'category': 'Sports',
    }

    test_regime = {
        'regime': 'liquid_sweet_spot',
        'risk_level': 'low',
        'suitable_strategies': ['sweet_spot', 'mean_reversion'],
        'metrics': {'market_count': 50, 'liq_mean': 80000},
    }

    # 场景1: 正常市场 → 风控通过
    decision = make_autonomous_decision(test_market, {}, test_regime, {})
    print("=== 场景1: 正常市场 ===")
    engine = AutonomousDecisionEngine()
    print(engine.get_decision_explanation(decision))

    # 场景2: 低流动性 → 跳过
    low_liq_market = {**test_market, 'liquidity': 3000}
    decision2 = make_autonomous_decision(low_liq_market, {}, test_regime, {})
    print("\n=== 场景2: 低流动性 (3000) ===")
    print(engine.get_decision_explanation(decision2))

    # 场景3: 高风险+低流动性 → 记录提示（不跳过，交 legacy 综合判断）
    high_risk_market = {**test_market, 'liquidity': 10000}
    high_risk_regime = {**test_regime, 'risk_level': 'high'}
    decision3 = make_autonomous_decision(high_risk_market, {}, high_risk_regime, {})
    print("\n=== 场景3: 高风险+低流动性 ===")
    print(engine.get_decision_explanation(decision3))
