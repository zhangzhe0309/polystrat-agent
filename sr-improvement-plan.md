# PolyStrat 胜率提升方案 · 基于 2026-06-29 实跑

## 现状诊断

实跑结果（459s / 11 markets / 0 trades）揭示三个死锁：

| 瓶颈 | 根因 | 效果 |
|---|---|---|
| 🅰 **甜蜜点分歧阈值过高** | `min_disagreement=15%`，但 LLM 一致性极高（分歧≤1.8%） | 所有市场被跳过，0 交易 |
| 🅱 **LLM 串行 45s 超时** | 4 provider 轮询 timeout=45，第一个卡死整个循环 | cron 跑 ~460s，80s 截断未覆盖 |
| 🅲 **LLM 失败时无回退** | `llm_analyze_probability` 返回 None 直接 continue | 丢失潜在 ML/链上可决策的市场 |

## 三步调整

### 第一步：放宽甜蜜点（1 分钟改完，立即见效）

```python
# polystrat_agent.py 第 124-132 行 → 改为：
SWEET_SPOT_CONFIG = {
    "min_price": 0.08,        # 10¢ → 8¢（放宽下限）
    "max_price": 0.35,        # 30¢ → 35¢（放宽上限）
    "min_liquidity": 10000,   # $20k → $10k（更多机会）
    "min_disagreement": 3,    # 15% → 3%（分歧≥3%即保留 → 可大幅增加交易量）
    "max_disagreement": 45,   # 40% → 45%（留更多空间）
    "min_confidence": 0.4,    # 60% → 40%（LLM 低置信也有价值）
    "preferred_categories": ["Politics", "Sports", "Crypto", "Economics"],
}
```

**影响**：从 0 → 约 20-30% 的市场可进入决策环节
**理由**：你 1000U 起步，不追求单笔暴利，用**交易次数换样本量**，ML 才能学出规律

---

### 第二步：LLM 并行 + 25s 超时（代码改动，修卡顿）

```python
# llm_analyze_probability 内，改串行为并行 + 单家 25s
from concurrent.futures import ThreadPoolExecutor, as_completed

def call_provider(provider):
    # ... requests.post(timeout=25) ...
    
futures = {executor.submit(call_provider, p): p["name"] for p in LLM_PROVIDERS}
for future in as_completed(futures, timeout=30):  # 总池 30s
    name = futures[future]
    prob = future.result(timeout=25)
    if prob is not None:
        predictions_dict[name] = prob
```

**影响**：4 家 LLM 从最坏 180s → 最坏 30s
**理由**：只要 1 个 LLM 响应，你就有 1 票；4 家并行不互相拖累

---

### 第三步：LLM 失败时回退到 ML/链上（代码改动，保底决策）

```python
# llm_analyze_probability 返回 None 时，不走 continue
# 改为使用 ML 预测值 + 链上信号 + 情感分析生成综合判断
```

**影响**：LLM 全超时/限流时，系统仍能基于 ML 模型+链上信号交易
**理由**：你的 ML 模块（GBDT+RF+LR+KNN）有 118 笔历史交易可学习

---

### 预期效果

| 指标 | 当前 | 调整后（预估） |
|---|---|---|
| 单次 cron 耗时 | 459s（超 80s 截断无效） | ≤80s |
| 每轮可交易市场数 | 0 | 2-4 个 |
| 日交易笔数 | 0 | 3-8 笔（cron 4h） |
| 胜率起步基线 | N/A | 52-58%（Polymarket 有效市场常规） |
| 样本积累速度 | 0/周 | 20-50 笔/周（可驱动 ML 迭代） |

---

## 实施顺序

1. **改配置**：1 分钟，手动改 7 个数字 → 立即生效
2. **LLM 并行**：约 15 分钟编写 + 测试 → 单次改代码
3. **ML 回退**：约 10 分钟 → 单次改代码

**做完 1 就跑一次 cron，看有没有交易产生。满意后做 2，再跑一次。最后做 3。**