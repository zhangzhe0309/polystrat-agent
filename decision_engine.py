#!/usr/bin/env python3
"""
自主决策引擎 (Autonomous Decision Engine)

替代原有的简单加权平均逻辑，实现4阶段自主决策管道:
1. 市场环境评估
2. 策略选择
3. 信号融合
4. 执行决策

核心改进:
- 方向平衡: 不再只交易No
- 情境感知: 根据市场状态调整策略
- 可解释性: 每笔交易附带决策理由
- 风险自适应: 根据环境动态调整风险参数

作者: PolyStrat Team
日期: 2026-07-04
"""

import json
import numpy as np
from datetime import datetime, timezone
from collections import defaultdict


class AutonomousDecisionEngine:
    """自主交易决策引擎"""
    
    # 决策参数
    EDGE_THRESHOLD_BASE = 0.04       # 基础edge阈值
    EDGE_THRESHOLD_DYNAMIC = True    # 是否动态调整阈值
    BALANCE_COOLDOWN = 3             # 同一方向冷却次数
    BALANCE_ENABLED = True           # 是否启用方向平衡
    MIN_YES_TRADES_RATIO = 0.3       # Yes交易最小比例（相对于总交易）
    
    def __init__(self, regime_detector=None, strategy_discoverer=None):
        self.regime_detector = regime_detector
        self.strategy_discoverer = strategy_discoverer
        self.direction_counters = defaultdict(int)  # 跟踪各方向使用次数
        self.total_decisions = 0                 # 总决策数
        self.yes_decisions = 0                   # Yes方向决策数
        self.no_decisions = 0                    # No方向决策数
    
    def make_decision(self, market, signals, regime_data, strategy_pool):
        """
        自主决策入口函数
        
        Args:
            market: 市场信息 dict
            signals: 信号字典 {llm_prob, sentiment_score, onchain_signal, 
                     ml_prob, microstructure_prob, final_prob, edge, ...}
            regime_data: 市场环境数据 (from MarketRegimeDetector)
            strategy_pool: 策略池 (from StrategyDiscoverer)
        
        Returns:
            dict: 决策结果
        """
        decision = {
            'market': market.get('title', ''),
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'phase_results': {},
            'final_decision': 'skip',
            'reason': '',
            'direction': None,
            'confidence': 0,
            'edge': 0,
            'urgency': 0,
            'slippage_estimate': 0,
        }
        
        # ===== Phase 1: 市场环境评估 =====
        phase1 = self._phase1_regime_check(market, regime_data, decision)
        decision['phase_results']['regime_check'] = phase1
        
        if not phase1.get('suitable', True):
            decision['final_decision'] = 'skip'
            decision['reason'] = f"市场环境不适合交易: {phase1.get('reason', '低流动性')}"
            return decision
        
        # ===== Phase 2: 策略选择 =====
        phase2 = self._phase2_strategy_selection(signals, regime_data, strategy_pool, decision)
        decision['phase_results']['strategy_selection'] = phase2
        
        # ===== Phase 3: 信号融合 =====
        phase3 = self._phase3_signal_fusion(market, signals, phase2, decision)
        decision['phase_results']['signal_fusion'] = phase3
        
        # ===== Phase 4: 执行决策 =====
        phase4 = self._phase4_execution_decision(market, signals, phase3, regime_data, decision)
        decision['phase_results']['execution_decision'] = phase4
        
        # 综合决策
        decision.update(phase4)
        
        return decision
    
    def _phase1_regime_check(self, market, regime_data, decision):
        """Phase 1: 市场环境检查"""
        result = {
            'regime': regime_data.get('regime', 'unknown'),
            'risk_level': regime_data.get('risk_level', 'unknown'),
            'suitable': True,
            'reason': '',
        }
        
        # 低流动性市场直接跳过
        liquidity = market.get('liquidity', 0)
        if liquidity < 5000:
            result['suitable'] = False
            result['reason'] = f'流动性过低 (${liquidity:,.0f})'
            return result
        
        # 高风险环境降低阈值或跳过
        risk = regime_data.get('risk_level', 'low')
        if risk == 'high' and liquidity < 20000:
            result['reason'] = '高风险+低流动性环境'
            result['risk_penalty'] = 0.02  # 降低edge阈值
        
        return result
    
    def _phase2_strategy_selection(self, signals, regime_data, strategy_pool, decision):
        """Phase 2: 策略选择"""
        regime = regime_data.get('regime', 'stable')
        recommended_strategies = regime_data.get('suitable_strategies', ['sweet_spot'])
        
        # 根据regime选择策略
        strategy_map = {
            'volatile': 'momentum',
            'liquid_sweet_spot': 'sweet_spot',
            'event_driven': 'catalyst',
            'stable': 'mean_reversion',
            'illiquid': 'avoid',
        }
        
        selected_strategy = strategy_map.get(regime, 'sweet_spot')
        
        # 如果有策略池，优先使用活跃策略
        if strategy_pool:
            active_strategies = {k: v for k, v in strategy_pool.items() 
                               if v.get('status') == 'active'}
            if active_strategies:
                # 选择EV最高的活跃策略
                best = max(active_strategies.items(), 
                          key=lambda x: x[1].get('ev_score', 0))
                selected_strategy = best[0]
        
        return {
            'selected_strategy': selected_strategy,
            'recommended_strategies': recommended_strategies,
            'regime_based': True,
        }
    
    def _phase3_signal_fusion(self, market, signals, strategy_info, decision):
        """Phase 3: 信号融合"""
        llm_prob = signals.get('llm_prob', 0.5)
        final_prob = signals.get('final_prob', llm_prob)
        sentiment = signals.get('sentiment_score', 0)
        onchain = signals.get('onchain_signal', {})
        ml_prob = signals.get('ml_prob', 0.5)
        
        yes_price = market.get('yes_price', 0.5)
        edge = signals.get('edge', final_prob - yes_price)
        
        # 策略感知的信号融合
        strategy = strategy_info.get('selected_strategy', 'sweet_spot')
        
        if strategy == 'momentum':
            # 动量策略: 更重视ML和微观结构
            fused_prob = (
                llm_prob * 0.25 +
                ml_prob * 0.30 +
                signals.get('microstructure_prob', 0.5) * 0.25 +
                self._sentiment_to_prob(sentiment) * 0.20
            )
        elif strategy == 'mean_reversion':
            # 均值回归: 更重视LLM和情绪
            fused_prob = (
                llm_prob * 0.35 +
                self._sentiment_to_prob(sentiment) * 0.25 +
                ml_prob * 0.25 +
                0.5 * 0.15  # 回归均值
            )
        elif strategy == 'catalyst':
            # 催化策略: 最重视情绪和新闻
            fused_prob = (
                self._sentiment_to_prob(sentiment) * 0.35 +
                llm_prob * 0.30 +
                ml_prob * 0.20 +
                self._onchain_to_prob(onchain) * 0.15
            )
        else:
            # 默认: 使用现有加权逻辑
            fused_prob = final_prob
        
        # 计算融合后的edge
        fused_edge = fused_prob - yes_price
        
        return {
            'fused_prob': round(fused_prob, 4),
            'fused_edge': round(fused_edge, 4),
            'strategy': strategy,
            'signal_weights': self._get_signal_weights(strategy),
        }
    
    def _phase4_execution_decision(self, market, signals, fusion_result, regime_data, decision):
        """Phase 4: 执行决策"""
        fused_prob = fusion_result['fused_prob']
        fused_edge = fusion_result['fused_edge']
        yes_price = market.get('yes_price', 0.5)
        liquidity = market.get('liquidity', 0)
        
        # 计算紧急度
        urgency = self._calculate_urgency(market, regime_data)
        
        # 估算滑点
        slippage = self._estimate_slippage(liquidity)
        
        # 方向平衡检查
        direction_choice, adjusted_edge = self._balanced_direction_check(
            fused_prob, yes_price, fused_edge
        )
        
        # 动态阈值
        threshold = self._get_dynamic_threshold(regime_data, urgency)
        
        # 风险调整
        risk_level = regime_data.get('risk_level', 'low')
        if risk_level == 'high':
            threshold *= 1.5  # 高风险需要更大edge
        elif risk_level == 'medium':
            threshold *= 1.2
        
        # 最终决策
        result = {
            'direction': direction_choice,
            'edge': abs(adjusted_edge),
            'urgency': urgency,
            'slippage_estimate': slippage,
            'threshold_used': round(threshold, 4),
        }
        
        if abs(adjusted_edge) >= threshold and liquidity > 10000:
            result['final_decision'] = 'execute'
            result['reason'] = (
                f"Edge {abs(adjusted_edge):.1%} > 阈值 {threshold:.1%}, "
                f"策略={fusion_result['strategy']}, "
                f"紧急度={urgency:.1f}"
            )
        else:
            result['final_decision'] = 'skip'
            result['reason'] = (
                f"Edge {abs(adjusted_edge):.1%} < 阈值 {threshold:.1%} "
                f"(调整后)" if abs(adjusted_edge) < threshold else "流动性不足"
            )
        
        return result
    
    # ---- 辅助方法 ----
    
    def _sentiment_to_prob(self, sentiment_score):
        """将情感分数转换为概率"""
        # sentiment_score范围通常在-1到1之间
        prob = 0.5 + sentiment_score * 0.3
        return max(0.1, min(0.9, prob))
    
    def _onchain_to_prob(self, onchain_signal):
        """将链上信号转换为概率"""
        if not onchain_signal or not isinstance(onchain_signal, dict):
            return 0.5
        
        rec = onchain_signal.get('recommendation', 'hold')
        conf = onchain_signal.get('confidence', 0.3)
        
        if rec == 'strong_buy':
            return 0.5 + 0.35 * conf
        elif rec == 'buy':
            return 0.5 + 0.15 * conf
        elif rec == 'strong_sell':
            return 0.5 - 0.35 * conf
        elif rec == 'sell':
            return 0.5 - 0.15 * conf
        return 0.5
    
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
            except:
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
    
    def _balanced_direction_check(self, fused_prob, yes_price, edge):
        """
        方向平衡检查 — 防止长期只交易一个方向
        
        核心逻辑:
        1. 如果Yes方向连续冷却次数用完，强制检查Yes机会
        2. 如果Yes交易比例低于阈值，降低Yes方向的edge门槛
        3. 否则正常判断
        """
        if not self.BALANCE_ENABLED:
            if edge >= 0:
                return 'Yes', edge
            else:
                return 'No', abs(edge)
        
        # 计算当前Yes/No比例
        if self.total_decisions > 0:
            yes_ratio = self.yes_decisions / self.total_decisions
        else:
            yes_ratio = 0.5
        
        # 如果Yes比例太低，降低Yes的edge门槛
        yes_boost = 0.0
        if yes_ratio < self.MIN_YES_TRADES_RATIO and self.total_decisions >= 3:
            deficit = self.MIN_YES_TRADES_RATIO - yes_ratio
            yes_boost = deficit * 0.5  # 补偿一半的缺口
        
        # 检查连续冷却
        current_streak = 0
        if self.no_decisions > 0 and self.yes_decisions == 0:
            current_streak = self.no_decisions
        elif self.yes_decisions > 0 and self.no_decisions == 0:
            current_streak = self.yes_decisions
        
        # 如果连续No太多，强制boost Yes方向
        if current_streak >= self.BALANCE_COOLDOWN and self.yes_decisions == 0:
            yes_boost += 0.05
        
        # 正常判断
        if edge >= 0:
            # Yes方向有机会 — boost 降低门槛，让 edge 更容易通过阈值
            boosted_edge = edge + yes_boost
            if boosted_edge > 0:
                return 'Yes', boosted_edge
            # 如果boost后edge还是负的，说明Yes机会不够好，但还是标记为Yes方向
            # 只是edge较低
            return 'Yes', edge
        else:
            return 'No', abs(edge)
    
    def record_direction(self, direction):
        """记录方向决策，用于平衡追踪"""
        self.total_decisions += 1
        if direction == 'Yes':
            self.yes_decisions += 1
        else:
            self.no_decisions += 1
    
    def get_balance_status(self):
        """获取方向平衡状态"""
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
    
    def _get_dynamic_threshold(self, regime_data, urgency):
        """根据市场环境和紧急度动态调整阈值"""
        base = self.EDGE_THRESHOLD_BASE
        
        regime = regime_data.get('regime', 'stable')
        
        # 不同regime的阈值调整
        regime_multipliers = {
            'volatile': 0.8,      # 高波动时降低阈值（机会多）
            'event_driven': 0.7,  # 事件驱动时大幅降低（信息优势大）
            'stable': 1.2,        # 稳定时提高阈值（机会少）
            'illiquid': 2.0,      # 低流动性大幅提高（风险高）
            'liquid_sweet_spot': 0.9,
        }
        
        multiplier = regime_multipliers.get(regime, 1.0)
        
        # 紧急度加成
        threshold = base * multiplier * (1 - urgency * 0.3)
        
        return max(0.02, min(0.10, threshold))  # 限制在2%-10%
    
    def _get_signal_weights(self, strategy):
        """返回不同策略的信号权重"""
        weights = {
            'momentum': {'llm': 0.25, 'ml': 0.30, 'microstructure': 0.25, 'sentiment': 0.20},
            'mean_reversion': {'llm': 0.35, 'sentiment': 0.25, 'ml': 0.25, 'regression': 0.15},
            'catalyst': {'sentiment': 0.35, 'llm': 0.30, 'ml': 0.20, 'onchain': 0.15},
            'sweet_spot': {'llm': 0.20, 'sentiment': 0.15, 'onchain': 0.25, 'ml': 0.25, 'microstructure': 0.15},
        }
        return weights.get(strategy, weights['sweet_spot'])
    
    def get_decision_explanation(self, decision):
        """生成决策的可解释性报告"""
        if decision.get('final_decision') == 'skip':
            return f"⏭️ 跳过: {decision.get('reason', '原因未知')}"
        
        lines = [
            f"🎯 决策: {decision.get('direction', '?')} @ edge={decision.get('edge', 0):.1%}",
            f"📊 策略: {decision.get('phase_results', {}).get('signal_fusion', {}).get('strategy', 'unknown')}",
            f"🔥 紧急度: {decision.get('urgency', 0):.1f}",
            f"💸 预估滑点: {decision.get('slippage_estimate', 0):.1%}",
            f"📝 理由: {decision.get('reason', '')}",
        ]
        
        # 添加信号融合详情
        fusion = decision.get('phase_results', {}).get('signal_fusion', {})
        if fusion:
            lines.append(f"🧮 融合概率: {fusion.get('fused_prob', 0):.1%}")
            lines.append(f"⚖️ 信号权重: {json.dumps(fusion.get('signal_weights', {}), ensure_ascii=False)}")
        
        return '\n'.join(lines)


def make_autonomous_decision(market, signals, regime_data, strategy_pool):
    """快捷决策函数"""
    engine = AutonomousDecisionEngine()
    return engine.make_decision(market, signals, regime_data, strategy_pool)


if __name__ == '__main__':
    # 测试
    test_market = {
        'title': 'Will Argentina win 2026 World Cup?',
        'yes_price': 0.21,
        'liquidity': 50000,
        'end_date': '2026-07-20T00:00:00Z',
        'category': 'Sports',
    }
    
    test_signals = {
        'llm_prob': 0.35,
        'sentiment_score': 0.2,
        'onchain_signal': {'recommendation': 'buy', 'confidence': 0.6},
        'ml_prob': 0.33,
        'microstructure_prob': 0.40,
        'final_prob': 0.34,
        'edge': 0.13,
    }
    
    test_regime = {
        'regime': 'liquid_sweet_spot',
        'risk_level': 'low',
        'suitable_strategies': ['sweet_spot', 'mean_reversion'],
        'metrics': {'market_count': 50, 'liq_mean': 80000},
    }
    
    decision = make_autonomous_decision(test_market, test_signals, test_regime, {})
    print("Decision:", json.dumps(decision, indent=2, ensure_ascii=False))
    print("\nExplanation:")
    engine = AutonomousDecisionEngine()
    print(engine.get_decision_explanation(decision))
