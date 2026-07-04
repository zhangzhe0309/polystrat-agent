#!/usr/bin/env python3
"""
市场环境检测模块 (Market Regime Detection)

判断当前 Polymarket 市场处于什么状态，为决策引擎提供上下文。

市场状态分类:
- volatile: 价格波动大，适合动量策略
- liquid: 流动性充裕，适合大仓位
- event_driven: 新市场/事件密集，适合新闻催化策略
- stable: 稳定震荡，适合均值回归

作者: PolyStrat Team
日期: 2026-07-04
"""

import json
import numpy as np
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import defaultdict


class MarketRegimeDetector:
    """市场环境检测器"""
    
    # 阈值配置
    THRESHOLDS = {
        'high_volatility': 0.08,       # 24h价格波动>8%算高波动
        'high_liquidity': 50000,       # 平均流动性>$50k算高流动
        'event_driven_ratio': 0.3,     # 新市场占比>30%算事件驱动
        'low_liquidity': 10000,        # 平均流动性<$10k算低流动
        'concentrated_category': 0.5,  # 单一类别占比>50%算集中
    }
    
    def __init__(self, trade_log_path=None):
        self.trade_log_path = trade_log_path
        self.regime_history = []
    
    def detect_regime(self, markets, recent_trades=None):
        """
        检测当前市场环境
        
        Args:
            markets: 市场列表，每个市场包含 {title, yes_price, liquidity, 
                     category, end_date, slug, volume_24h?}
            recent_trades: 最近交易记录（可选）
            
        Returns:
            dict: {
                'regime': str,  # 主要市场状态
                'sub_regimes': list,  # 次要状态
                'metrics': dict,  # 各项指标
                'suitable_strategies': list,  # 适合的策略
                'risk_level': str,  # 风险等级
                'timestamp': str,
            }
        """
        if not markets:
            return self._empty_regime()
        
        # 计算各项指标
        metrics = self._compute_metrics(markets, recent_trades)
        
        # 检测子状态
        sub_regimes = self._detect_sub_regimes(metrics)
        
        # 确定主要状态
        regime = self._determine_primary_regime(metrics, sub_regimes)
        
        # 确定适合的策略
        strategies = self._get_suitable_strategies(regime, sub_regimes, metrics)
        
        # 评估风险等级
        risk_level = self._assess_risk(metrics, regime)
        
        result = {
            'regime': regime,
            'sub_regimes': sub_regimes,
            'metrics': metrics,
            'suitable_strategies': strategies,
            'risk_level': risk_level,
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }
        
        self.regime_history.append(result)
        # 保留最近100条
        if len(self.regime_history) > 100:
            self.regime_history = self.regime_history[-100:]
        
        return result
    
    def _compute_metrics(self, markets, recent_trades=None):
        """计算市场指标"""
        prices = [m.get('yes_price', 0.5) for m in markets if m.get('yes_price')]
        liquidiies = [m.get('liquidity', 0) for m in markets if m.get('liquidity')]
        categories = [m.get('category', 'Other') for m in markets]
        
        # 价格分布
        price_mean = np.mean(prices) if prices else 0.5
        price_std = np.std(prices) if prices else 0
        price_median = np.median(prices) if prices else 0.5
        
        # 流动性分布
        liq_mean = np.mean(liquidiies) if liquidiies else 0
        liq_median = np.median(liquidiies) if liquidiies else 0
        
        # 类别集中度
        cat_counts = defaultdict(int)
        for c in categories:
            cat_counts[c] += 1
        cat_total = len(categories)
        cat_concentration = max(cat_counts.values()) / cat_total if cat_total > 0 else 0
        top_category = max(cat_counts, key=cat_counts.get) if cat_counts else 'Unknown'
        
        # 甜蜜点市场占比 (0.10-0.30)
        sweet_spot_count = sum(1 for p in prices if 0.10 <= p <= 0.30)
        sweet_spot_ratio = sweet_spot_count / len(prices) if prices else 0
        
        # 边缘分布 (abs(price - 0.5))
        edges = [abs(p - 0.5) for p in prices]
        avg_edge = np.mean(edges) if edges else 0
        
        # 新市场比例（通过slug判断，新的slug通常包含日期或事件名）
        new_market_ratio = self._estimate_new_market_ratio(markets)
        
        # 短期到期市场占比
        soon_expiring = 0
        for m in markets:
            end_date = m.get('end_date', '')
            if end_date:
                try:
                    dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                    days_left = (dt - datetime.now(timezone.utc)).days
                    if 0 < days_left <= 3:
                        soon_expiring += 1
                except:
                    pass
        soon_expiring_ratio = soon_expiring / len(markets) if markets else 0
        
        return {
            'market_count': len(markets),
            'price_mean': round(price_mean, 4),
            'price_std': round(price_std, 4),
            'price_median': round(price_median, 4),
            'liq_mean': round(liq_mean, 0),
            'liq_median': round(liq_median, 0),
            'cat_concentration': round(cat_concentration, 4),
            'top_category': top_category,
            'sweet_spot_ratio': round(sweet_spot_ratio, 4),
            'avg_edge': round(avg_edge, 4),
            'new_market_ratio': round(new_market_ratio, 4),
            'soon_expiring_ratio': round(soon_expiring_ratio, 4),
            'price_range': [round(min(prices), 4), round(max(prices), 4)] if prices else [0, 0],
        }
    
    def _estimate_new_market_ratio(self, markets):
        """估算新市场比例（启发式）"""
        new_count = 0
        for m in markets:
            slug = m.get('slug', '')
            title = m.get('title', '').lower() if isinstance(m, dict) else ''
            # 新市场特征: slug包含日期, 或标题包含最新事件
            if any(word in slug for word in ['2026', 'july', 'june']):
                new_count += 1
            elif any(word in title for word in ['breaks', 'surges', 'announces', 'declares', 'wins']):
                new_count += 1
        return new_count / len(markets) if markets else 0
    
    def _detect_sub_regimes(self, metrics):
        """检测子状态"""
        sub_regimes = []
        
        if metrics['price_std'] > self.THRESHOLDS['high_volatility']:
            sub_regimes.append('high_volatility')
        
        if metrics['liq_mean'] > self.THRESHOLDS['high_liquidity']:
            sub_regimes.append('high_liquidity')
        
        if metrics['liq_mean'] < self.THRESHOLDS['low_liquidity']:
            sub_regimes.append('low_liquidity')
        
        if metrics['new_market_ratio'] > self.THRESHOLDS['event_driven_ratio']:
            sub_regimes.append('event_driven')
        
        if metrics['cat_concentration'] > self.THRESHOLDS['concentrated_category']:
            sub_regimes.append('category_concentrated')
        
        if metrics['sweet_spot_ratio'] > 0.4:
            sub_regimes.append('sweet_spot_rich')
        
        if metrics['soon_expiring_ratio'] > 0.2:
            sub_regimes.append('expiry_clustering')
        
        return sub_regimes
    
    def _determine_primary_regime(self, metrics, sub_regimes):
        """确定主要市场状态"""
        # 优先级: 低流动 > 事件驱动 > 高波动 > 高流动 > 稳定
        
        if 'low_liquidity' in sub_regimes:
            return 'illiquid'
        
        if 'event_driven' in sub_regimes:
            return 'event_driven'
        
        if 'high_volatility' in sub_regimes:
            return 'volatile'
        
        if 'high_liquidity' in sub_regimes and metrics['sweet_spot_ratio'] > 0.3:
            return 'liquid_sweet_spot'
        
        return 'stable'
    
    def _get_suitable_strategies(self, regime, sub_regimes, metrics):
        """根据不同市场状态推荐适合的交易策略"""
        strategy_map = {
            'volatile': ['momentum', 'news_break', 'catalyst'],
            'liquid_sweet_spot': ['sweet_spot', 'mean_reversion', 'arbitrage'],
            'event_driven': ['catalyst', 'sentiment', 'news_break'],
            'illiquid': ['avoid', 'wait_for_liquidity'],
            'stable': ['mean_reversion', 'sweet_spot', 'contrarian'],
        }
        
        strategies = strategy_map.get(regime, ['sweet_spot'])
        
        # 根据子状态补充策略
        if 'expiry_clustering' in sub_regimes:
            strategies.append('expiry_play')
        if 'category_concentrated' in sub_regimes:
            strategies.append('category_focus')
        
        return list(set(strategies))  # 去重
    
    def _assess_risk(self, metrics, regime):
        """评估市场风险等级"""
        risk_score = 0
        
        # 低流动性 = 高风险
        if metrics['liq_mean'] < self.THRESHOLDS['low_liquidity']:
            risk_score += 3
        elif metrics['liq_mean'] < 25000:
            risk_score += 1
        
        # 高波动 = 高风险
        if metrics['price_std'] > self.THRESHOLDS['high_volatility']:
            risk_score += 2
        
        # 新市场多 = 中等风险
        if metrics['new_market_ratio'] > 0.3:
            risk_score += 1
        
        # 快到期的市场多 = 高风险
        if metrics['soon_expiring_ratio'] > 0.2:
            risk_score += 2
        
        if risk_score >= 5:
            return 'high'
        elif risk_score >= 2:
            return 'medium'
        else:
            return 'low'
    
    def _empty_regime(self):
        """空市场时的默认状态"""
        return {
            'regime': 'empty',
            'sub_regimes': [],
            'metrics': {},
            'suitable_strategies': ['wait'],
            'risk_level': 'unknown',
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }
    
    def get_regime_summary(self, regime_data):
        """生成可读的市场环境摘要"""
        regime = regime_data.get('regime', 'unknown')
        risk = regime_data.get('risk_level', 'unknown')
        strategies = regime_data.get('suitable_strategies', [])
        metrics = regime_data.get('metrics', {})
        
        regime_labels = {
            'volatile': '🔥 高波动市场',
            'liquid_sweet_spot': '💧 高流动性甜蜜点市场',
            'event_driven': '⚡ 事件驱动市场',
            'illiquid': '🏜️ 低流动性市场',
            'stable': '😌 稳定市场',
            'empty': '⏸️ 无活跃市场',
        }
        
        risk_labels = {
            'high': '🔴 高风险',
            'medium': '🟡 中等风险',
            'low': '🟢 低风险',
            'unknown': '⚪ 未知',
        }
        
        lines = [
            f"📊 市场环境: {regime_labels.get(regime, regime)}",
            f"⚠️ 风险等级: {risk_labels.get(risk, risk)}",
            f"🎯 适合策略: {', '.join(strategies)}",
        ]
        
        if metrics:
            lines.append(f"📈 市场数量: {metrics.get('market_count', 0)}")
            lines.append(f"💰 平均流动性: ${metrics.get('liq_mean', 0):,.0f}")
            lines.append(f"📊 价格标准差: {metrics.get('price_std', 0):.4f}")
            if metrics.get('sweet_spot_ratio'):
                lines.append(f"🎯 甜蜜点占比: {metrics.get('sweet_spot_ratio'):.1%}")
        
        return '\n'.join(lines)


# 便捷函数
def detect_market_regime(markets, trade_log_path=None):
    """快捷检测市场环境"""
    detector = MarketRegimeDetector(trade_log_path)
    return detector.detect_regime(markets)


def format_regime_report(regime_data):
    """格式化市场环境报告"""
    return MarketRegimeDetector().get_regime_summary(regime_data)


if __name__ == '__main__':
    # 测试
    test_markets = [
        {'yes_price': 0.15, 'liquidity': 100000, 'category': 'Sports', 'slug': 'world-cup-final-2026'},
        {'yes_price': 0.25, 'liquidity': 50000, 'category': 'Politics', 'slug': 'election-2026-july'},
        {'yes_price': 0.80, 'liquidity': 5000, 'category': 'Crypto', 'slug': 'btc-100k-2026'},
        {'yes_price': 0.45, 'liquidity': 200000, 'category': 'Economics', 'slug': 'fed-rate-july'},
    ]
    
    regime = detect_market_regime(test_markets)
    print(format_regime_report(regime))
    print(f"\n详细数据: {json.dumps(regime, indent=2, ensure_ascii=False)}")
