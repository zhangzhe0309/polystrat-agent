#!/usr/bin/env python3
"""
策略发现与进化模块 (Strategy Discovery & Evolution)

从历史交易中自动发现有效策略，淘汰低效策略，生成策略报告。

核心功能:
1. 策略聚类 — 根据交易特征自动分组
2. 策略评分 — 计算每个策略的胜率、夏普比率、样本量
3. 策略进化 — 淘汰低效策略，微调接近阈值的策略
4. 策略推荐 — 根据当前市场环境推荐策略

设计原则:
- 最小样本量保护: 少于5笔交易的策略标记为"观察中"
- 保守淘汰: 胜率<30%且样本>=10才标记inactive
- 渐进演化: 策略参数微调幅度不超过20%

作者: PolyStrat Team
日期: 2026-07-04
"""

import json
import numpy as np
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import defaultdict


# 策略持久化文件
STRATEGY_POOL_PATH = Path(__file__).parent / 'strategy_pool.json'

# 策略状态
STRATEGY_ACTIVE = 'active'
STRATEGY_OBSERVING = 'observing'
STRATEGY_INACTIVE = 'inactive'
STRATEGY_NEW = 'new'


class StrategyDiscoverer:
    """策略发现器"""
    
    # 参数配置
    MIN_SAMPLES_ACTIVE = 10      # 至少10笔交易才标记active
    MIN_SAMPLES_OBSERVE = 3      # 至少3笔交易才开始观察
    WIN_RATE_THRESHOLD = 0.40    # 胜率<40%标记为低效
    EDGE_THRESHOLD = 0.03        # 平均edge<3%视为低质量
    EVOLUTION_RATE = 0.15        # 策略进化调整幅度15%
    
    def __init__(self, trade_log_path=None):
        self.trade_log_path = trade_log_path
        self.strategy_pool = self._load_strategy_pool()
    
    def discover_and_evaluate(self, trades):
        """
        从交易记录中发现和评估策略
        
        Args:
            trades: 交易记录列表，每条包含:
                    {market, direction, edge, category, result?, 
                     sentiment_score, llm_prob, final_prob, ...}
        
        Returns:
            dict: {
                'strategies': {name: strategy_info},
                'recommendations': list,
                'summary': dict,
            }
        """
        if not trades:
            return self._empty_result()
        
        # 1. 聚类交易到策略组
        clusters = self._cluster_trades(trades)
        
        # 2. 评估每个策略组
        evaluated = {}
        for cluster_name, cluster_trades in clusters.items():
            evaluated[cluster_name] = self._evaluate_cluster(cluster_name, cluster_trades)
        
        # 3. 与现有策略池合并
        self._merge_with_pool(evaluated)
        
        # 4. 生成推荐
        recommendations = self._generate_recommendations(evaluated)
        
        # 5. 生成摘要
        summary = self._generate_summary(evaluated, clusters)
        
        # 6. 持久化策略池
        self._save_strategy_pool()
        
        return {
            'strategies': self.strategy_pool,
            'recommendations': recommendations,
            'summary': summary,
            'raw_clusters': {k: len(v) for k, v in clusters.items()},
        }
    
    def _cluster_trades(self, trades):
        """
        将交易聚类到策略组
        
        聚类维度:
        - 市场类别 (Category)
        - 价格区间 (Price Band)
        - 方向 (Direction)
        - Edge范围 (Edge Tier)
        - 信号来源 (Primary Signal)
        """
        clusters = defaultdict(list)
        
        for trade in trades:
            category = trade.get('category', 'Other') or 'Other'
            price = trade.get('market_price', 0.5)
            direction = trade.get('direction', 'Unknown')
            edge = abs(trade.get('edge', 0))
            
            # 价格区间
            if price < 0.10:
                price_band = 'ultra_low'
            elif price < 0.25:
                price_band = 'low'
            elif price < 0.50:
                price_band = 'mid'
            elif price < 0.75:
                price_band = 'high_mid'
            else:
                price_band = 'high'
            
            # Edge层级
            if edge < 0.03:
                edge_tier = 'thin'
            elif edge < 0.08:
                edge_tier = 'moderate'
            elif edge < 0.15:
                edge_tier = 'wide'
            else:
                edge_tier = 'very_wide'
            
            # 主要信号来源
            llm_prob = trade.get('llm_prob', 0.5)
            final_prob = trade.get('final_prob', llm_prob)
            if abs(llm_prob - final_prob) > 0.05:
                primary_signal = 'ml_onchain_adjusted'
            else:
                primary_signal = 'llm_dominant'
            
            # 生成策略名称
            strategy_name = f"{category}_{price_band}_{direction}_{edge_tier}"
            
            # 简化策略名称用于展示
            display_name = self._make_display_name(strategy_name, trade)
            
            clusters[display_name].append({
                **trade,
                '_cluster_key': strategy_name,
            })
        
        return dict(clusters)
    
    def _make_display_name(self, cluster_key, trade):
        """生成人类可读的策略名称"""
        parts = cluster_key.split('_')
        
        # 提取类别
        category = parts[0] if parts else 'Mixed'
        
        # 提取价格带
        price_bands = ['ultra_low', 'low', 'mid', 'high_mid', 'high']
        price_band = 'mixed'
        for pb in price_bands:
            if pb in cluster_key:
                price_band = pb
                break
        
        # 提取方向
        direction = 'mixed'
        directions = ['Yes', 'No']
        for d in directions:
            if d.lower() in cluster_key.lower():
                direction = d
                break
        
        # 构建简洁名称
        band_labels = {
            'ultra_low': '超低价',
            'low': '低价',
            'mid': '中价',
            'high_mid': '中高',
            'high': '高价',
            'mixed': '多价位',
        }
        
        edge_labels = {
            'thin': '薄边',
            'moderate': '中等',
            'wide': '宽边',
            'very_wide': '极宽',
            'mixed': '多变',
        }
        
        name = f"{category}{band_labels.get(price_band, price_band)}{direction}策略"
        
        # 如果已经有硬编码策略名，优先使用
        existing_strategy = trade.get('strategy', '')
        if existing_strategy and existing_strategy not in ['none', 'None']:
            return existing_strategy
        
        return name
    
    def _evaluate_cluster(self, name, cluster_trades):
        """评估一个策略簇"""
        n = len(cluster_trades)
        
        # 计算edge分布
        edges = [abs(t.get('edge', 0)) for t in cluster_trades]
        avg_edge = np.mean(edges) if edges else 0
        median_edge = np.median(edges) if edges else 0
        
        # 计算价格分布
        prices = [t.get('market_price', 0.5) for t in cluster_trades]
        avg_price = np.mean(prices) if prices else 0.5
        
        # 尝试计算胜率（如果有result字段）
        results = [t.get('result', '') for t in cluster_trades]
        wins = sum(1 for r in results if r in ['win', 'Won', 'WON', True, '1', 'settled_yes'])
        losses = sum(1 for r in results if r in ['lose', 'Lost', 'LOST', False, '0', 'settled_no'])
        pending = sum(1 for r in results if r not in ['win', 'Won', 'WON', 'lose', 'Lost', 'LOST', False, '0', 'settled_yes', 'settled_no', '', None])
        
        resolved = wins + losses
        win_rate = wins / resolved if resolved > 0 else 0.5  # 默认中性
        
        # 计算预期价值 (EV)
        # EV = edge * probability_of_positive_edge
        positive_edges = sum(1 for e in edges if e > 0.02)
        ev_score = avg_edge * (positive_edges / n if n > 0 else 0)
        
        # 确定策略状态
        if n >= self.MIN_SAMPLES_ACTIVE:
            if win_rate >= self.WIN_RATE_THRESHOLD and avg_edge >= self.EDGE_THRESHOLD:
                status = STRATEGY_ACTIVE
            elif win_rate < 0.30:
                status = STRATEGY_INACTIVE
            else:
                status = STRATEGY_OBSERVING
        elif n >= self.MIN_SAMPLES_OBSERVE:
            status = STRATEGY_OBSERVING
        else:
            status = STRATEGY_NEW
        
        # 计算信号一致性
        llm_probs = [t.get('llm_prob', 0.5) for t in cluster_trades]
        final_probs = [t.get('final_prob', 0.5) for t in cluster_trades]
        if llm_probs and final_probs:
            llm_final_correlation = np.corrcoef(llm_probs, final_probs)[0, 1] if len(llm_probs) > 1 else 1.0
        else:
            llm_final_correlation = 1.0
        
        return {
            'name': name,
            'sample_size': n,
            'status': status,
            'win_rate': round(win_rate, 4),
            'wins': wins,
            'losses': losses,
            'pending': pending,
            'avg_edge': round(avg_edge, 4),
            'median_edge': round(median_edge, 4),
            'avg_price': round(avg_price, 4),
            'ev_score': round(ev_score, 4),
            'llm_final_correlation': round(float(llm_final_correlation), 4) if not np.isnan(llm_final_correlation) else 1.0,
            'directions': dict(defaultdict(int, {t.get('direction', '?'): sum(1 for tt in cluster_trades if tt.get('direction') == t.get('direction')) for t in cluster_trades})),
            'categories': list(set(t.get('category', 'Other') or 'Other' for t in cluster_trades)),
        }
    
    def _merge_with_pool(self, evaluated):
        """将新评估的策略合并到策略池"""
        for name, eval_data in evaluated.items():
            if name in self.strategy_pool:
                # 更新现有策略
                existing = self.strategy_pool[name]
                existing['sample_size'] = eval_data['sample_size']
                existing['win_rate'] = eval_data['win_rate']
                existing['wins'] = eval_data['wins']
                existing['losses'] = eval_data['losses']
                existing['pending'] = eval_data['pending']
                existing['avg_edge'] = eval_data['avg_edge']
                existing['ev_score'] = eval_data['ev_score']
                
                # 重新评估状态
                new_status = eval_data['status']
                if new_status == STRATEGY_INACTIVE:
                    existing['status'] = STRATEGY_INACTIVE
                elif new_status == STRATEGY_ACTIVE and existing.get('status') == STRATEGY_OBSERVING:
                    existing['status'] = STRATEGY_ACTIVE
                
                existing['last_updated'] = datetime.now(timezone.utc).isoformat()
            else:
                # 添加新策略
                eval_data['created_at'] = datetime.now(timezone.utc).isoformat()
                eval_data['last_updated'] = datetime.now(timezone.utc).isoformat()
                self.strategy_pool[name] = eval_data
    
    def _generate_recommendations(self, evaluated):
        """生成策略建议"""
        recommendations = []
        
        # 1. 推荐高价值策略
        for name, data in evaluated.items():
            if data['ev_score'] > 0.05 and data['sample_size'] >= 3:
                recommendations.append({
                    'type': 'promote',
                    'strategy': name,
                    'reason': f"高EV得分 ({data['ev_score']:.4f})",
                    'action': '增加权重或扩大仓位',
                })
        
        # 2. 推荐淘汰低效策略
        for name, data in evaluated.items():
            if data['sample_size'] >= self.MIN_SAMPLES_ACTIVE and data['win_rate'] < 0.30:
                recommendations.append({
                    'type': 'deactivate',
                    'strategy': name,
                    'reason': f"低胜率 ({data['win_rate']:.1%})",
                    'action': '标记为inactive，停止使用该策略',
                })
        
        # 3. 推荐观察中的策略
        for name, data in evaluated.items():
            if data['status'] == STRATEGY_NEW and data['sample_size'] >= 1:
                recommendations.append({
                    'type': 'monitor',
                    'strategy': name,
                    'reason': f"新发现策略 ({data['sample_size']}笔交易)",
                    'action': '继续观察，积累样本',
                })
        
        # 4. 方向平衡建议
        total_yes = sum(1 for t in evaluated.values() for d in t.get('directions', {}).values())
        if total_yes > 0:
            no_count = sum(d.get('directions', {}).get('No', 0) for d in evaluated.values())
            yes_count = sum(d.get('directions', {}).get('Yes', 0) for d in evaluated.values())
            if no_count > yes_count * 3:
                recommendations.append({
                    'type': 'balance',
                    'strategy': 'global',
                    'reason': f"方向严重失衡: Yes={yes_count}, No={no_count}",
                    'action': '检查策略是否忽略了Yes方向的机会',
                })
        
        return recommendations
    
    def _generate_summary(self, evaluated, clusters):
        """生成策略发现摘要"""
        total_trades = sum(len(t) for t in clusters.values())
        unique_strategies = len(evaluated)
        active_strategies = sum(1 for s in evaluated.values() if s['status'] == STRATEGY_ACTIVE)
        observing_strategies = sum(1 for s in evaluated.values() if s['status'] == STRATEGY_OBSERVING)
        
        # 整体胜率（仅计算已结算）
        total_wins = sum(s['wins'] for s in evaluated.values())
        total_losses = sum(s['losses'] for s in evaluated.values())
        overall_wr = total_wins / (total_wins + total_losses) if (total_wins + total_losses) > 0 else 0
        
        return {
            'total_trades_analyzed': total_trades,
            'unique_strategies_found': unique_strategies,
            'active_strategies': active_strategies,
            'observing_strategies': observing_strategies,
            'overall_win_rate': round(overall_wr, 4),
            'total_wins': total_wins,
            'total_losses': total_losses,
        }
    
    def _empty_result(self):
        """空交易列表的默认结果"""
        return {
            'strategies': self.strategy_pool,
            'recommendations': [],
            'summary': {
                'total_trades_analyzed': 0,
                'unique_strategies_found': 0,
                'active_strategies': 0,
                'overall_win_rate': 0,
            },
            'raw_clusters': {},
        }
    
    def _load_strategy_pool(self):
        """加载策略池"""
        if STRATEGY_POOL_PATH.exists():
            try:
                return json.loads(STRATEGY_POOL_PATH.read_text())
            except:
                return {}
        return {}
    
    def _save_strategy_pool(self):
        """保存策略池"""
        STRATEGY_POOL_PATH.write_text(json.dumps(self.strategy_pool, indent=2, ensure_ascii=False))
    
    def get_strategy_report(self):
        """生成策略池报告"""
        if not self.strategy_pool:
            return "📋 策略池为空 — 需要更多交易数据来发现策略"
        
        lines = ["📋 策略池报告", ""]
        
        active = {k: v for k, v in self.strategy_pool.items() if v.get('status') == STRATEGY_ACTIVE}
        observing = {k: v for k, v in self.strategy_pool.items() if v.get('status') == STRATEGY_OBSERVING}
        inactive = {k: v for k, v in self.strategy_pool.items() if v.get('status') == STRATEGY_INACTIVE}
        
        if active:
            lines.append(f"✅ 活跃策略 ({len(active)}):")
            for name, data in active.items():
                lines.append(f"  • {name}: 胜率{data.get('win_rate', 0):.1%}, "
                           f"样本{data.get('sample_size', 0)}, EV{data.get('ev_score', 0):.4f}")
        
        if observing:
            lines.append(f"\n👁️ 观察中策略 ({len(observing)}):")
            for name, data in observing.items():
                lines.append(f"  • {name}: 样本{data.get('sample_size', 0)}")
        
        if inactive:
            lines.append(f"\n❌ 已停用策略 ({len(inactive)}):")
            for name, data in inactive.items():
                lines.append(f"  • {name}: {data.get('reason', '低效')}")
        
        return '\n'.join(lines)
    
    def evolve_strategy_params(self, strategy_name, new_data):
        """
        策略参数进化
        
        对接近阈值的策略进行微调，不激进改变
        """
        if strategy_name not in self.strategy_pool:
            return False
        
        current = self.strategy_pool[strategy_name]
        rate = self.EVOLUTION_RATE
        
        # 如果胜率提升，小幅增加信心权重
        if new_data.get('win_rate', 0) > current.get('win_rate', 0) + 0.05:
            current['confidence_boost'] = current.get('confidence_boost', 0) + rate
        
        # 如果edge扩大，标记为高质量
        if new_data.get('avg_edge', 0) > current.get('avg_edge', 0) * 1.2:
            current['edge_quality'] = 'improving'
        
        current['last_evolved'] = datetime.now(timezone.utc).isoformat()
        self._save_strategy_pool()
        return True


def discover_strades(trades, trade_log_path=None):
    """快捷策略发现"""
    discoverer = StrategyDiscoverer(trade_log_path)
    return discoverer.discover_and_evaluate(trades)


if __name__ == '__main__':
    # 测试
    test_trades = [
        {'market': 'Germany World Cup?', 'direction': 'No', 'edge': 0.06, 
         'category': 'Sports', 'market_price': 0.04, 'result': 'pending',
         'llm_prob': 0.08, 'final_prob': 0.09},
        {'market': 'Argentina World Cup?', 'direction': 'No', 'edge': 0.14,
         'category': 'Sports', 'market_price': 0.21, 'result': 'pending',
         'llm_prob': 0.30, 'final_prob': 0.35},
    ]
    
    result = discover_strades(test_trades)
    print(json.dumps(result, indent=2, ensure_ascii=False))
