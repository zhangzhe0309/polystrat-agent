# KongTradeBot + negRisk 套利 → PolyStrat 集成分析

## 概要

基于对 `KongTradeBot` (onur-tech) 仓库的深度分析及 negRisk 多结果套利策略的最新研究，本文档梳理了可集成到 PolyStrat 的核心组件、策略逻辑和代码片段。

---

## 一、KongTradeBot 核心架构分析

### 1.1 四步流水线

```
WalletMonitor → CopyTradingStrategy → RiskManager → ExecutionEngine
```

| 组件 | 文件 | 职责 |
|------|------|------|
| WalletMonitor | `core/wallet_monitor.py` | 轮询 data-api.polymarket.com/activity，去重(tx_hash)，生成 TradeSignal |
| CopyTradingStrategy | `strategies/copy_trading.py` | 信号聚合、Wallet Multiplier、Win Rate Decay Detection |
| RiskManager | `core/risk_manager.py` | Kill-Switch、日损限额、价格区间过滤(15%-85%)、市场预算(3% per market) |
| ExecutionEngine | `core/execution_engine.py` | Dry-Run/Live 模式、create_and_post_order 单次调用、On-Chain 验证 |

### 1.2 与 PolyStrat 现有模块对比

| 功能 | KongTradeBot | PolyStrat 现有 | 差距 |
|------|-------------|---------------|------|
| 钱包监控 | WalletMonitor (async, aiohttp) | whale_monitor.py (同步, requests) | 🔴 需要异步化 |
| KongScore 评分 | 10 维度专业评分 (SC-1~SC-10) | whale_copy.py 简易4维 | 🔴 严重不足 |
| 钱包加权 | WALLET_MULTIPLIERS (0.2x~3.0x) | 无 | 🔴 缺失 |
| 信号聚合 | AGGREGATION_WINDOW + MULTI_SIGNAL | 无 | 🔴 缺失 |
| Win Rate Decay | is_decaying + is_trend_declining | 无 | 🔴 缺失 |
| 止盈逻辑 | 40/40/15/5 阶梯 (TP1/TP2/TP3) | 简单百分比 | 🟡 需增强 |
| 风险管理 | 多层(日损/市场预算/价格区间/时间) | 基础 | 🟡 需增强 |
| 执行引擎 | create_and_post_order + FillTracker | 无 | 🔴 缺失 |

---

## 二、KongScore 评分系统详解

### 2.1 评分维度（Small-Pool 版本，5 维度，100 分满分）

| ID | 维度 | 权重 | 评分标准 |
|----|------|------|----------|
| SC-1 | Sample-Size | 25 | 200+ trades=25p, 100-199=15p, 50-99=10p, <50=0p |
| SC-2 | 类别专注度 | 25 | 70%+=25p, 50-70%=15p, <50%=0p |
| SC-3 | Entry 价格区 | 20 | 20-40¢=20p, 40-60¢=8p, >60¢=0p |
| SC-4 | ROI:MDD 比率 | 20 | >2.0=20p, 1.5-2.0=10p, <1.0=0p |
| SC-7 | Exit 证据 | 10 | 主动退出=10p, 偶尔=5p, 从不=0p |

### 2.2 Hard Filter (KO 条件)

| Filter | 条件 | 说明 |
|--------|------|------|
| HF-0 | 总盈利 > $10K 或 ROI > 10% | 绝对 KO 条件 |
| HF-1 | ≥50 resolved markets | 统计显著性 |
| HF-2 | 账户年龄 ≥ 60 天 | 防止 Sybil |
| HF-3 | Max-Drawdown < 30% | 生存性 |
| HF-5 | 14 天内有 ≥3 新仓位 | 活跃度 |
| HF-7 | 累计 ROI > 0 | 不亏钱 |
| HF-9 | <20% 交易在 Resolution 前 10 分钟 | 防 Insider |

### 2.3 评级映射

| KongScore | Tier | Multiplier | 说明 |
|-----------|------|-----------|------|
| ≥70 | A | 1.0x (全仓) | 核心池，最多 5 钱包 |
| 50-69 | B | 0.3-0.5x | 实验池，最多 10 钱包 |
| <50 | C | 0.0x (仅观察) | 影子池，不跟单 |

---

## 三、Multiplier 加权跟单逻辑

### 3.1 三层乘数叠加

```python
combined_multiplier = wallet_multiplier × multi_signal_multiplier × early_entry_multiplier
```

| 乘数类型 | 逻辑 | 值域 |
|----------|------|------|
| Wallet Multiplier | 基于历史胜率手动配置 | 0.2x (差) ~ 3.0x (优) |
| Multi-Signal Multiplier | 多钱包同市场信号 | 1.0x / 1.5x / 2.0x |
| Early Entry Bonus | 市场体积 < $10K | 1.0x / 1.5x |

### 3.2 Decay 降权机制

| 条件 | 动作 |
|------|------|
| 最近 20 笔胜率 < 45% | 完全跳过 (is_decaying) |
| 最近胜率低于总胜率 > 10% | Multiplier 减半 (is_trend_declining) |
| 连续 3+ 天 Trend-Decline | Telegram 告警 + 持续减半 |

### 3.3 羊群效应防护

当 >50% 的目标钱包同时进入同一市场 → 不放大 + Telegram 告警

---

## 四、Take-Profit 触发机制

### 4.1 阶梯止盈（KongTradeBot 实际使用的 40/40/15/5 模型）

| Stage | 触发价 | 退出比例 | 说明 |
|-------|--------|----------|------|
| TP1 | Entry + 10% | 40% 仓位 | 快速回收成本 |
| TP2 | Entry + 25% | 40% 仓位 | 锁定主要利润 |
| TP3 | Entry + 50% | 15% 仓位 | 捕捉大波动 |
| Whale-Exit | 鲸鱼卖出时 | 剩余 5% | 尾随鲸鱼退出 |

### 4.2 核心洞察

> Bot 的 Edge 是 **Momentum-Capture**，不是 Prediction。
> TP-Exit 在 Resolution 之前退出，Weather/Geopolitik 类别预测率仅 22.7% 但产生 +$2632 PnL。

---

## 五、negRisk 多结果套利策略

### 5.1 核心原理

negRisk 市场将多个互斥二元市场（YES/NO）统一为单一多结果市场。关键约束：
- **有且仅有一个**结果为 YES
- 所有 YES 价格之和 **应等于 1.00**

### 5.2 套利逻辑

| 类型 | 条件 | 操作 | 利润来源 |
|------|------|------|----------|
| Underpriced | Σ(prices) < 1.00 | 买入所有 YES token | Resolution 后收回 $1.00 |
| Overpriced | Σ(prices) > 1.00 | 卖出所有 NO token (或 NegRisk 转换) | NO token 可兑换为 USDC |

### 5.3 资本效率优势

NegRisk 套利相比单条件套利有 **29× 资本效率优势**：
- 单条件: 7,051 次机会，$10.58M 提取
- NegRisk: 662 次机会，$28.99M 提取（占总额 73%）

### 5.4 NegRiskAdapter 合约机制

- **NO → YES 转换**: 持有 N 个 NO token 可转换为 1 USDC + 1 YES (剩余 outcome)
- **WrappedCollateral**: USDC 被 wrap 后作为底层市场的抵押品
- **交易时需设 `neg_risk: true`**: Python SDK `neg_risk: True`

### 5.5 风险评分算法

| 因素 | 风险增量 |
|------|----------|
| Resolution < 2 天 | +0.4 |
| Resolution < 7 天 | +0.2 |
| NegRisk: 每增加一个 token | +0.03 (max +0.2) |
| 主观 Oracle 关键词 | +0.3 |

### 5.6 推荐资本分配

| 策略 | 分配 | 原因 |
|------|------|------|
| NegRisk 再平衡 | 40% | 最高效率 |
| 单条件套利 | 30% | 高频 |
| 事件驱动 | 20% | 定时催化剂 |
| 鲸鱼跟随 | 10% | 信号增强 |

---

## 六、集成代码片段

### 6.1 增强版 KongScore 评分（替换 whale_copy.py 的简易版）

见 `kong_score_v2.py`

### 6.2 negRisk 套利检测器（新增模块）

见 `negrisk_arbitrage.py`

### 6.3 阶梯止盈模块（增强 whale_copy.py）

见 `take_profit_manager.py`

### 6.4 信号聚合器（新增模块）

见 `signal_aggregator.py`
