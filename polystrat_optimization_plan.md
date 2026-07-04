# PolyStrat 自主交易决策优化方案 v1.0

> 日期: 2026-07-04
> 目标: 从"被动信号加权"升级为"自主决策Agent"

---

## 一、现状诊断

### 当前架构（1398行，10+模块）

```
信号采集 → 加权平均 → 阈值比较 → Kelly仓位 → 下单
```

**核心问题：**

1. **信号只是加权平均，没有真正的"决策"** — 6个信号简单加权得出final_prob，然后和阈值比较。这不是Agent，这是计算器。
2. **所有交易都是"No"方向** — 7笔DryRun全部No，说明策略存在系统性偏差（只追低估的No，忽略高估的Yes）
3. **没有自我反思/反馈闭环** — 虽然ML模块在训练，但ML的输出只是又一个加权信号，不会反过来优化策略
4. **缺少"何时不交易"的判断** — 当前只有edge>threshold就交易的逻辑，没有市场环境判断
5. **策略固化** — "低价体育回归"和"中价国家队溢价回归"是硬编码策略名，不是动态发现的
6. **没有多时间尺度分析** — 只看当前价格，不看价格趋势、成交量变化

### 数据现状
- 仅7笔DryRun交易，样本太少
- 没有真实结算结果（全是pending）
- 无法验证ML模型是否真的提高了胜率

---

## 二、优化目标

将PolyStrat从**信号计算器**升级为**自主交易Agent**，具备：

1. **自主决策** — 不只是加权平均，而是理解市场情境，选择最优策略
2. **策略进化** — 从历史交易中自动发现有效策略，淘汰无效策略
3. **环境感知** — 判断当前市场是否适合交易（流动性、波动率、事件密集度）
4. **方向平衡** — 不再只交易No，Yes/No双向捕捉机会
5. **风险自适应** — 根据市场状态动态调整风险参数

---

## 三、核心优化方案

### 3.1 引入"决策引擎"层（Decision Engine）

**当前:** `final_prob = Σ(signal_i × weight_i)` → 简单加权
**优化后:** 多层决策管道

```
┌─────────────────────────────────────────────┐
│  Phase 1: 市场环境评估 (Market Regime)       │
│  - 当前是趋势市/震荡市/事件驱动市？            │
│  - 流动性是否充足？                           │
│  - 是否有重大事件即将发生？                     │
│  → 输出: regime_score, suitable_for_trading  │
├─────────────────────────────────────────────┤
│  Phase 2: 策略选择 (Strategy Selection)       │
│  - 根据regime选择最优策略组合                  │
│  - 例: 趋势市→动量策略, 震荡市→均值回归        │
│  - 策略库动态评分                              │
│  → 输出: selected_strategies, strategy_probs │
├─────────────────────────────────────────────┤
│  Phase 3: 信号融合 (Signal Fusion)            │
│  - 不是简单加权，而是策略感知的融合             │
│  - 不同策略使用不同信号组合                    │
│  - 考虑信号间的协同/冲突                       │
│  → 输出: strategy_adjusted_prob, confidence  │
├─────────────────────────────────────────────┤
│  Phase 4: 执行决策 (Execution Decision)       │
│  - 是否交易？交易方向？仓位大小？               │
│  - 考虑滑点、流动性、市场深度                  │
│  - 多目标优化: EV最大化 + 风险约束             │
│  → 输出: direction, position_size, urgency   │
└─────────────────────────────────────────────┘
```

### 3.2 策略发现与进化系统

**新增模块: `strategy_discovery.py`**

核心思路：从历史交易中自动发现"什么策略在什么条件下有效"

```python
# 伪代码示例
class StrategyDiscoverer:
    def discover_strategies(self, trade_history):
        """从交易记录中发现有效策略"""
        strategies = {}
        
        # 1. 按类别聚类交易
        for trade in trade_history:
            cluster = self.cluster_trade(trade)
            if cluster not in strategies:
                strategies[cluster] = []
            strategies[cluster].append(trade)
        
        # 2. 计算每个策略的统计特征
        for name, trades in strategies.items():
            win_rate = sum(1 for t in trades if t.result == 'win') / len(trades)
            avg_edge = mean(abs(t.edge) for t in trades)
            avg_return = mean(t.pnl for t in trades)
            sharpe = avg_return / std(trades) if len(trades) > 5 else 0
            
            strategies[name] = {
                'win_rate': win_rate,
                'avg_edge': avg_edge,
                'sharpe': sharpe,
                'sample_size': len(trades),
                'is_profitable': win_rate > 0.5 and sharpe > 0,
                'is_reliable': len(trades) >= MIN_SAMPLES,
            }
        
        # 3. 淘汰低效策略，强化高效策略
        self.evolve_strategy_pool(strategies)
        
        return strategies
    
    def evolve_strategy_pool(self, strategies):
        """策略进化：淘汰+变异+创新"""
        # 淘汰: win_rate < 40% 且样本>5的策略标记为inactive
        # 变异: 对接近阈值的策略微调参数
        # 创新: 基于新出现的交易模式生成候选策略
        pass
```

**策略库示例（从当前交易中发现）：**
| 策略名 | 条件 | 当前胜率 | 样本量 | 状态 |
|--------|------|---------|--------|------|
| 低价体育回归 | price<0.10 + Sports + edge>0.03 | ? | 4 | 观察中 |
| 中价国家队溢价回归 | 0.10<price<0.30 + edge>0.10 | ? | 3 | 观察中 |
| ~~高价均值回归~~ | price>0.70 + edge<0.05 | 0% | 0 | 未激活 |

### 3.3 市场环境评估（Market Regime Detection）

**新增模块: `market_regime.py`**

```python
class MarketRegimeDetector:
    """判断当前Polymarket市场处于什么状态"""
    
    def detect_regime(self, markets, recent_trades):
        metrics = {
            'avg_liquidity': mean(m.liquidity for m in markets),
            'price_volatility': std(m.price_changes_last_24h),
            'edge_distribution': histogram(abs(m.edge) for m in markets),
            'category_diversity': len(set(m.category for m in markets)),
            'new_market_ratio': count(m.is_new()) / len(markets),
        }
        
        # 分类
        if metrics['price_volatility'] > THRESHOLD_HIGH:
            regime = 'volatile'  # 波动市 - 适合动量策略
        elif metrics['avg_liquidity'] > THRESHOLD_LIQUID:
            regime = 'liquid'    # 流动市 - 适合大仓位
        elif metrics['new_market_ratio'] > 0.3:
            regime = 'event_driven'  # 事件驱动 - 适合新闻策略
        else:
            regime = 'stable'    # 稳定市 - 适合均值回归
        
        return {
            'regime': regime,
            'metrics': metrics,
            'suitable_strategies': self.get_suitable_strategies(regime),
        }
    
    def get_suitable_strategies(self, regime):
        """不同市场状态适合不同策略"""
        mapping = {
            'volatile': ['momentum', 'news_break'],
            'liquid': ['mean_reversion', 'arbitrage'],
            'event_driven': ['catalyst', 'sentiment'],
            'stable': ['mean_reversion', 'sweet_spot'],
        }
        return mapping.get(regime, ['sweet_spot'])
```

### 3.4 方向平衡机制

**问题:** 当前7笔交易全部No，说明策略对Yes方向不敏感

**解决方案:**

1. **对称Edge检测** — 不仅看`final_prob - price > threshold`，也看`price - final_prob > threshold`
2. **方向配额** — 每轮最多N笔No，强制检查Yes机会
3. **分类别分析** — 按市场类别分别计算Yes/No的期望收益

```python
def balanced_decision(final_prob, yes_price, vote_details):
    """对称决策，避免方向偏见"""
    edge_yes = final_prob - yes_price      # Yes方向的edge
    edge_no = (1 - final_prob) - (1 - yes_price)  # No方向的edge
    
    if abs(edge_yes) > THRESHOLD and abs(edge_no) > THRESHOLD:
        # 两边都有机会，选edge更大的
        if edge_yes > edge_no:
            return "Yes", edge_yes
        else:
            return "No", edge_no
    elif edge_yes > THRESHOLD:
        return "Yes", edge_yes
    elif edge_no > THRESHOLD:
        return "No", edge_no
    else:
        return "skip", 0
```

### 3.5 执行决策增强

**当前:** `edge > threshold → BUY`
**优化:** 多维度决策

```python
def execution_decision(signal, market, regime, strategy_pool):
    """综合决策是否执行、何时执行、执行多少"""
    
    # 1. 紧急度评分 (urgency)
    urgency = 0
    if market.end_date_days_left < 3:
        urgency += 0.3  # 快到结算日，价格可能剧烈变动
    if market.volume_24h_change > 50:
        urgency += 0.2  # 成交量激增，可能有新信息
    
    # 2. 滑点估计
    slippage_estimate = estimate_slippage(market.liquidity, position_size)
    
    # 3. 调整后EV
    adjusted_ev = signal.edge - slippage_estimate - urgency_penalty
    
    # 4. 决策矩阵
    if adjusted_ev > HIGH_THRESHOLD and urgency > 0.3:
        return "execute_immediately", full_position
    elif adjusted_ev > MEDIUM_THRESHOLD:
        return "execute_normal", reduced_position
    elif adjusted_ev > LOW_THRESHOLD and urgency > 0:
        return "execute_small", tiny_position
    else:
        return "skip", 0
```

---

## 四、实施计划

### Phase 1: 核心决策引擎（1-2天）
- [ ] 新增 `decision_engine.py` — 4阶段决策管道
- [ ] 新增 `market_regime.py` — 市场环境检测
- [ ] 修改主流程，替换简单加权逻辑
- [ ] 保持DRY_RUN，不影响现有交易记录

### Phase 2: 策略发现系统（2-3天）
- [ ] 新增 `strategy_discovery.py` — 自动策略发现
- [ ] 新增 `strategy_pool.json` — 持久化策略库
- [ ] 集成到主流程，每次运行后更新策略库
- [ ] 添加策略有效性报告

### Phase 3: 方向平衡与执行优化（1-2天）
- [ ] 修复方向偏见（Yes/No对称）
- [ ] 增强执行决策（urgency + slippage）
- [ ] 添加执行日志（记录为什么交易/为什么不交易）

### Phase 4: 多模型评审与验证（1天）
- [ ] 用GLM-5.1/Kimi K2.6/Qwen3.5/DeepSeek v4-Flash评审
- [ ] DryRun验证新策略效果
- [ ] 对比优化前后的决策质量

---

## 五、预期效果

| 指标 | 当前 | 目标 |
|------|------|------|
| 方向分布 | 100% No | Yes/No ~50/50 |
| 策略多样性 | 2种硬编码 | 自动发现N种 |
| 决策维度 | 1维(edge) | 4维(regime+strategy+signal+execution) |
| 市场环境感知 | 无 | 4种regime分类 |
| 可解释性 | 黑盒加权 | 每笔交易附带决策理由 |

---

## 六、风险评估

1. **过度拟合** — 策略发现可能过拟合历史数据，需要交叉验证
2. **复杂度增加** — 从~1400行可能增加到~2500行，需要保持模块化
3. **性能影响** — 4阶段决策管道可能增加运行时间，需监控
4. **DRY_RUN安全** — 所有优化先在dry run验证，不触碰真实资金

---

## 七、与AgentFi趋势对齐

根据Cambrian Network Q1 2026报告，AgentFi的核心趋势是：
- **自主Agent管理资金** → PolyStrat的Kelly仓位+风险自适应符合这一趋势
- **x402支付协议** → 未来可以让Agent自主支付API费用
- **ERC-8004 Agent注册** → 可以为PolyStrat创建链上身份

优化后的PolyStrat更接近真正的"自主交易Agent"而非"交易脚本"，与AgentFi发展方向一致。
