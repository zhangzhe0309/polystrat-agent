# PolyStrat - AI 自主交易 Agent v3.3

🤖 **PolyStrat** 是一个基于 AI 的 Polymarket 预测市场自主交易机器人，采用多信号融合策略进行自动化交易决策。

---

## ✨ 核心特性

- **多源新闻聚合** — 5个新闻源并行搜索（GNews、Currents、NewsData、NYTimes、RSS；SerpAPI 每天1次手动触发）
- **LLM 集成分析** — 4模型投票（DeepSeek V4 Flash、Nemotron 3 Super、MiniMax M2.7、GLM-5.1）
- **智能情感分析** — 关键词 + LLM 双重分析
- **机器学习优化** — 4模型集成（LR、RF、GBDT、KNN）
- **自适应权重** — 4信号（LLM/情感/链上/ML）根据历史胜率动态调整权重
- **自适应信号映射** — 情感斜率和链上乘数基于历史准确率自动调参
- **风险管理** — 仓位控制、止损、分散投资
- **多平台套利** — 跨平台价格比较
- **新闻源质量评分** — 基于历史表现动态评估新闻源可信度
- **高级投票系统** — 动态阈值、异常值过滤、置信度评估
- **Fractional Kelly 仓位** — 25% Kelly × 置信度 × 流动性因子
- **时间序列交叉验证** — 防 ML 数据泄露

---

## 📁 项目结构

```
polystrat-agent/
├── polystrat_agent.py      # 主程序
├── news_search.py          # 新闻搜索模块（并行+缓存）
├── sentiment_analysis.py   # 情感分析模块
├── risk_management.py      # 风险管理模块
├── ml_optimizer.py         # 机器学习优化模块
├── adaptive_weights.py     # 自适应权重模块
├── dynamic_optimizer.py    # 动态优化模块
├── onchain_monitor.py      # 链上数据监控
├── multi_platform.py       # 多平台支持
├── smart_keywords.py       # 智能关键词提取
├── polystrat_logger.py     # 统一日志系统
├── quick_review.py         # 快速评审脚本
├── circuit_breaker.py      # 断路器
├── trade_limits.py         # 交易限额
├── OPTIMIZATION.md         # 策略优化记录
└── README.md               # 本文件
```

---

## 🚀 快速开始

### 1. 环境配置

```bash
# 安装依赖
pip install requests python-dotenv scikit-learn numpy

# 配置环境变量（.env 文件）
cp .env.example .env
# 编辑 .env 填入你的 API Key
```

### 2. 环境变量

在 `.env` 文件中配置以下变量：

```env
# Polymarket
POLYMARKET_FUNDER_ADDRESS=your_funder_address
POLYMARKET_PRIVATE_KEY=your_private_key
SIGNATURE_TYPE=1

# LLM API (NVIDIA)
NVIDIA_API_KEY_2=your_nvidia_api_key

# 新闻 API
GNEWS_API_KEY=your_gnews_key
CURRENTS_API_KEY=your_currents_key
NEWSDATA_API_KEY=your_newsdata_key
NYTIMES_API_KEY=your_nytimes_key
SERPAPI_KEY=your_serpapi_key
```

### 3. 运行

```bash
# 测试模式（DRY_RUN=True）
python3 polystrat_agent.py

# 快速评审
python3 quick_review.py
```

---

## 🔧 技术架构

### 信号融合流程

```
市场数据 ──┬── 新闻搜索 ── 情感分析 ──────┐
           ├── LLM 分析（4模型投票）──────┤
           ├── 链上数据（连续映射+置信度）──┼── 自适应加权融合 ── 风险检查 ── Fractional Kelly 仓位 ── 下单
           ├── ML 集成预测（时间序列CV）───┤
           └── 多平台套利信号 ────────────┘
```

### 权重配置

| 信号源 | 默认权重 | 动态调整依据 |
|--------|----------|-------------|
| LLM 分析 | 25% | 4模型准确率加权 + 动态投票系统 |
| ML 集成 | 30% | 4算法（LR/RF/GBDT/KNN）验证集准确率 |
| 链上数据 | 30% | 连续映射 × 置信度 × 自适应乘数 |
| 新闻情感 | 15% | 自适应斜率（准确率高→扩大影响力） |
| 套利信号 | 5% | 跨平台价差机会数 |

---

## 📊 评审机制

### 快速评审

```bash
python3 quick_review.py
```

输出示例：
```
============================================================
PolyStrat 快速评审
============================================================
📁 文件检查:
  ✅ polystrat_agent.py: 750 行
  ✅ news_search.py: 494 行
  ...

📊 总结:
  文件: 11/11
  总行数: 3,730 行
  裸except: 17 个
  硬编码密钥: 0

🎯 快速评分: 95/100
```

### 深度评审

详见 [OPTIMIZATION.md](OPTIMIZATION.md)，包含完整的策略优化历史、修复记录和评审视角。

---

## 🔒 安全特性

- ✅ API Key 存储在环境变量，不硬编码
- ✅ 文件锁保护并发写入
- ✅ 动态去重防止重复下单
- ✅ 仓位硬上限控制风险
- ✅ 断路器机制（连续亏损自动暂停）
- ✅ 交易限额（日交易笔数/总量限制）
- ✅ Fractional Kelly 仓位管理
- ✅ DRY_RUN 模式默认开启

---

## 📈 性能优化

- ✅ 新闻搜索并行化（5源同时请求，SerpAPI 手动触发）
- ✅ 文件缓存（1小时TTL，5550x 加速）
- ✅ 动态权重调整（4信号自适应）
- ✅ 自适应信号映射参数（基于准确率闭环）
- ✅ 新闻源质量评分（基于历史表现动态调权）
- ✅ 时间序列 CV 防数据泄露
- ✅ 市场过滤优化

---

## 🛠️ 依赖

- Python 3.11+
- requests
- python-dotenv
- scikit-learn
- numpy

---

## 📝 更新日志

### v3.8 (2026-06-26)

**链上信号优化 — 置信度提升：**

**核心优化:**
- [P0] 优化 `get_market_momentum` 函数（更多因子，更准确的信号）
- [P0] 优化 `get_onchain_signal` 函数（多因子置信度计算）
- [P1] 提升市场匹配度（从 60% 提升到 70% 单词匹配）
- [P1] 增加更多动量因子（价格变化、流动性变化、交易量趋势）
- [P1] 增加 sell/strong_sell 信号支持
- [P1] 提升置信度计算（多因子：匹配度 + 动量 + 因子数量）

**新增动量因子（5个）：**
- 成交量/流动性比率（权重 0.25）
- 成交量变化（权重 0.25）
- 绝对成交量（权重 0.2）
- 流动性（权重 0.15）
- 价格极端性（权重 0.15）

**预期效果:**
- 链上信号置信度提升（从 0.3-0.7 提升到 0.3-0.95）
- 信号准确性提升（更多因子）
- 信号类型扩展（增加 sell/strong_sell）

### v3.7 (2026-06-26)

**新闻源优化 — RSS 质量提升：**

**核心优化:**
- [P0] RSS 源从 5 个扩展到 9 个（3个搜索源 + 4个固定源 + 2个Polymarket相关源）
- [P0] 新增支持搜索的 RSS 源（Bing News、Yahoo News）
- [P0] 新增 Polymarket 相关 RSS 源（Polymarket Blog、Prediction Market News）
- [P1] 优化 RSS 解析函数（内容质量过滤、发布时间过滤、来源标识）
- [P1] 优化 search_rss 函数（动态配额分配，搜索源优先）

**新增 RSS 源（4个）：**
- Bing News RSS（支持搜索）
- Yahoo News RSS（支持搜索）
- Polymarket Blog（Polymarket官方）
- Prediction Market News（预测市场新闻）

**预期效果:**
- RSS 质量评分提升（从 0.60 提升到 0.75+）
- 新闻相关性提升（支持搜索的源）
- Polymarket 信息覆盖提升（专用源）

### v3.6 (2026-06-26)

**机器学习优化 — 特征工程扩展：**

**核心优化:**
- [P0] 特征从 5 个扩展到 15 个（核心信号 + 链上信号 + 市场特征 + 新闻特征 + 投票特征 + 微观结构特征）
- [P0] 更新 `get_ml_signal` 函数，支持新特征参数
- [P0] 更新 `polystrat_agent.py` 调用，传入完整特征数据
- [P1] 更新特征重要性分析（15个特征名称）

**新增特征（10个）：**
- 链上信号特征（3个）：置信度、买入推荐、卖出推荐
- 市场特征（2个）：到期时间、市场分类
- 新闻特征（1个）：新闻源数量
- 投票特征（2个）：置信度、分歧度
- 微观结构特征（2个）：置信度、买入推荐

**预期效果:**
- 胜率提升 +5-10%（更多特征维度）
- 模型泛化能力提升（避免过拟合）
- 信号质量提升（多源数据融合）

### v3.5 (2026-06-26)

**信号增强 — 市场微观结构信号：**

**核心优化:**
- [P0] 新增 `market_microstructure.py` 模块（订单簿深度、买卖价差、成交量动量）
- [P0] 新增 `MICROSTRUCTURE_CONFIG` 配置（权重、置信度阈值）
- [P0] 集成到信号融合流程（6信号：LLM + 情感 + 链上 + ML + 微观结构 + 套利）
- [P1] 权重重新分配（LLM 20% + 情感 15% + 链上 25% + ML 25% + 微观结构 10% + 套利 5%）

**预期效果:**
- 胜率提升 +8-12%（市场微观结构信号更独立）
- 信号质量提升（订单簿深度、价差分析）
- 风险控制优化（流动性监控）

**配置说明:**
```python
MICROSTRUCTURE_CONFIG = {
    "enabled": True,           # 启用微观结构信号
    "weight": 0.10,            # 权重 10%
    "min_confidence": 0.3,     # 最低置信度
    "prefer_tight_spread": True,  # 优先选择价差小的市场
}
```

### v3.4 (2026-06-26)

**甜蜜点市场策略 — 聚焦高胜率区间：**

**核心优化:**
- [P0] 新增 `SWEET_SPOT_CONFIG` 配置（价格区间、流动性、分歧度阈值）
- [P0] 新增 `SWEET_SPOT_MODE` 开关（可切换回原始模式）
- [P0] 市场筛选逻辑优化：聚焦 10-30¢ 甜蜜点区间
- [P1] 投票质量检查：分歧度 15-40%，置信度 ≥60%
- [P1] 优选事件类型：Politics、Sports、Crypto、Economics

**预期效果:**
- 胜率提升 +5-8%（聚焦高概率区间）
- 减少噪声交易（投票质量检查过滤低质量信号）
- 提高资金效率（优选高流动性市场）

**配置说明:**
```python
SWEET_SPOT_CONFIG = {
    "min_price": 0.10,      # 最低 10¢
    "max_price": 0.30,      # 最高 30¢（甜蜜点上限）
    "min_liquidity": 20000, # 最低流动性 $20k
    "min_disagreement": 15, # 最低投票分歧 15%
    "max_disagreement": 40, # 最高投票分歧 40%
    "min_confidence": 0.6,  # 最低投票置信度 60%
    "preferred_categories": ["Politics", "Sports", "Crypto", "Economics"],
}
```

### v3.3 (2026-06-26)

**第4轮修复 — 数据流完整性（详见 [OPTIMIZATION.md](OPTIMIZATION.md)）:**

**数据流:**
- [P1] 新闻正文传递给 LLM（title + description，前4条）
- [P1] SerpAPI 移出自动流（每天1次配额，改为手动触发）
- [P1] 止损检查接入主循环（`check_stop_loss` 计算累计回撤，超-10%暂停新交易）
- [P2] LLM temperature 使用 per-provider 配置（0.3/0.4/0.5，提升投票多样性）
- [P2] 清理孤儿代码（`search_news_simple` 残留定义）

### v3.2 (2026-06-26)

**策略优化（详见 [OPTIMIZATION.md](OPTIMIZATION.md)）:**

**核心算法:**
- [P0] 自适应权重模块形同虚设修复（4信号动态权重替代硬编码）
- [P0] 动态优化器数据泄露修复（`result` 字段替代 `edge` 代理）
- [P0] ML 回测时间序列 CV 防数据泄露
- [P0] 链上信号 volume_change 硬编码修复（Gamma API + 快照缓存）
- [P0] 投票系统 model_names 硬编码修复（旧模型名永远匹配不到新模型）
- [P1] 情感/链上信号映射开环修复（自适应斜率+乘数闭环）
- [P1] Fractional Kelly 仓位管理（25% Kelly × 置信度 × 流动性）
- [P1] 动态集成模型权重（基于验证集准确率分配）

**信号融合:**
- [P1] LLM 模型阵容升级：Qwen 3.5/Kimi K2.6/Llama 3.3 70B → DeepSeek V4 Flash/Nemotron 3 Super/MiniMax M2.7
- [P1] 链上信号连续映射（4离散值→连续+置信度加权）
- [P1] 链上置信度连续映射（两档→`0.3+0.4×momentum_score`）
- [P1] 情感信号映射加宽（0.35 斜率，可自适应调参）
- [P1] 套利信号 5% 权重
- [P1] 风控传入正确置信度（投票置信度替代情感置信度）
- [P1] 高级投票系统动态阈值+置信度公式重构

**工程改进:**
- [P2] 新闻源质量评分真实现（基于交易结果统计）
- [P2] 新闻源动态配额接入（高质量源取更多条）
- [P2] 交易记录补齐信号数据（ml_prob/onchain_signal/news_sources）
- [P2] 自适应权重输出映射调参参数（闭环可控）
- [P2] 断路器初始资金从环境变量读取
- [P2] adaptive_weights hold 信号跳过不计入准确率
- [P2] 未使用导入清理

### v3.1 (2026-06-25)

**安全修复:**
- [P0] API Key 迁移到环境变量
- [P0] 重复下单 BUG 修复（condition_id 去重）
- [P0] 竞态条件修复（文件锁）

**逻辑修正:**
- [P1] 胜率计算逻辑修复（基于结算结果）
- [P1] ML 标签定义修正（预测盈利而非优势）
- [P1] 仓位计算逻辑统一

**性能优化:**
- [P1] 新闻搜索并行化
- [P1] 文件缓存机制

**工程改进:**
- [P2] 统一日志系统
- [P2] 快速评审脚本
- [P2] 评审机制文档

---

## 📄 许可证

MIT License

---

## 🔗 链接

- [Gitee 仓库](https://gitee.com/mynickname/polystrat-agent)
- [Polymarket](https://polymarket.com)

---

*最后更新: 2026-06-26*
