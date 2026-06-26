# PolyStrat v3.14 完整评审 Prompt

请作为**量化交易系统架构师 + AI策略专家 + 安全工程师**，对 PolyStrat v3.14 进行全面深度评审。

---

## 项目概述

**PolyStrat** 是一个 Polymarket 预测市场 AI 交易机器人，核心功能：
- 多信号融合 (LLM + 情感 + 链上 + ML)
- 高级投票系统 (加权+异常值过滤+动态阈值)
- 跨平台套利 (Polymarket + Kalshi + Manifold)
- 鲸鱼跟单 (KongScore + Multiplier)
- 断路器 + 交易限额 + 统一异常处理

**代码规模**: 3,764 行，14 个模块，21 个单元测试

---

## 评审维度 (每项 0-100 分)

### 1. 整体方案评审
- 架构设计是否合理？
- 模块划分是否清晰？
- 扩展性如何？
- 是否有设计缺陷？

### 2. 策略合理性评审
- 信号融合权重 (LLM 25%, 情感 15%, 链上 30%, ML 30%) 是否科学？
- 投票机制是否有效？
- 风险管理是否充分？
- 套利策略是否可行？

### 3. 核心算法评审
- 加权投票算法是否正确？
- 异常值过滤 (MAD) 是否合理？
- 动态阈值机制是否有效？
- Fractional Kelly 仓位管理是否恰当？

### 4. 代码质量评审
- 模块化程度
- 错误处理完整性
- 测试覆盖率
- 可维护性

### 5. 安全性评审
- 密钥管理
- 资金安全
- 并发安全
- 日志脱敏

### 6. 生产就绪度评审
- 监控告警
- 回测系统
- 配置管理
- 灾难恢复

---

## 核心代码

### 1. 主程序 (polystrat_agent.py) - 信号融合
```python
# 权重配置（优化后：降低LLM共线性风险，提高ML/链上权重）
SIGNAL_WEIGHTS = {
    "llm": 0.25,        # LLM 分析权重（降低，避免与情感信号共线性）
    "sentiment": 0.15,  # 新闻情感权重（降低，与LLM有重叠）
    "onchain": 0.30,    # 链上信号权重（提高，更独立的数据源）
    "ml": 0.30,         # ML 信号权重（提高，数据驱动）
}

# 信号转换
llm_signal_prob = llm_prob
sentiment_signal_prob = 0.5 + sentiment_score * 0.2  # 映射到 0.3-0.7
onchain_signal_prob = 0.5 + onchain_adjustment  # 根据推荐调整
ml_signal_prob = ml_prob

# 加权平均
final_prob = (
    llm_signal_prob * SIGNAL_WEIGHTS["llm"] +
    sentiment_signal_prob * SIGNAL_WEIGHTS["sentiment"] +
    onchain_signal_prob * SIGNAL_WEIGHTS["onchain"] +
    ml_signal_prob * SIGNAL_WEIGHTS["ml"]
)
```

### 2. 高级投票系统 (advanced_voting.py)
```python
class AdvancedVotingSystem:
    def __init__(self, model_names, historical_accuracy=None):
        self.disagreement_threshold = 20  # 默认阈值
    
    def get_dynamic_threshold(self, predictions):
        """根据市场波动动态调整分歧阈值"""
        std = np.std(predictions)
        if std < 10:    return 15  # 低波动
        elif std > 30:  return 30  # 高波动
        else:           return 20  # 正常
    
    def detect_outliers(self, predictions):
        """MAD 异常值检测"""
        median = np.median(predictions)
        mad = np.median(np.abs(predictions - median))
        modified_z_scores = 0.6745 * (predictions - median) / mad
        return np.abs(modified_z_scores) > 3.5
    
    def vote(self, predictions_dict):
        """加权投票（含异常值过滤）"""
        # 检测异常值 → 降权
        # 计算加权平均
        # 计算置信度
        # 动态阈值判断
```

### 3. 断路器 (circuit_breaker.py)
```python
BREAKER_CONFIG = {
    "max_consecutive_losses": 10,     # 连续亏损10次
    "max_daily_loss_pct": -0.20,      # 每日亏损20%
    "max_drawdown_pct": -0.30,        # 总回撤30%
    "cooldown_minutes": 60,           # 冷却60分钟
}

def record_trade(self, pnl):
    """记录交易结果，检查是否触发断路器"""
    if self.state["consecutive_losses"] >= BREAKER_CONFIG["max_consecutive_losses"]:
        self._trip(f"连续亏损 {self.state['consecutive_losses']} 次")
    
    daily_loss_pct = self.state["daily_pnl"] / initial_balance
    if daily_loss_pct <= BREAKER_CONFIG["max_daily_loss_pct"]:
        self._trip(f"每日亏损 {daily_loss_pct:.1%}")
```

### 4. 交易限额 (trade_limits.py)
```python
LIMITS_CONFIG = {
    "max_single_trade": 10.0,       # 单笔最大 $10
    "max_daily_trades": 10,         # 每日最大 10 次
    "max_daily_volume": 100.0,      # 每日最大 $100
    "max_total_exposure": 200.0,    # 总仓位 $200
}

def can_trade(self, amount, balance=None):
    """检查是否允许交易"""
    if amount > LIMITS_CONFIG["max_single_trade"]:
        return False, f"超过单笔限额"
    if self.state["daily_trades"] >= LIMITS_CONFIG["max_daily_trades"]:
        return False, f"超过每日交易次数"
    # ...
```

### 5. 套利执行 (arbitrage_enhanced.py)
```python
# 滑点保护（预留 2% 滑点）
slippage = 0.02
net_profit = gross_profit - slippage

# 单腿风险保护（价差必须大于滑点的2倍）
min_spread_for_arb = slippage * 2 + fee1 + fee2

if net_profit > 0 and spread > min_spread_for_arb:
    # 执行套利
```

---

## 技术栈

| 组件 | 技术 |
|------|------|
| 语言 | Python 3.11 |
| 交易 | Polymarket CLOB V2 SDK |
| LLM | NVIDIA API (Qwen/Kimi/Llama) + 智谱 GLM-5.1 |
| ML | scikit-learn (LR/RF/GBDT/KNN) |
| 数据 | DeFiLlama, Etherscan, RSS |
| 调度 | Hermes Cron |
| 存储 | JSON + 文件锁 |

---

## 已知问题 (待修复)

1. **LLM 单点故障**: 所有模型通过同一 API 平台
2. **信号共线性**: LLM 和情感信号有重叠
3. **缺少回测**: 没有历史数据验证策略
4. **并发安全**: JSON 文件锁在高并发下可能有问题

---

## 评审输出要求

请给出：
1. **各维度评分** (0-100)
2. **总分**
3. **关键发现** (P0/P1/P2)
4. **改进建议** (具体可执行)
5. **是否可以实盘运行的结论**
6. **与之前版本对比** (v3.13: 代码68, 策略47.5)
