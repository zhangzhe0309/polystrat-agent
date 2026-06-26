# PolyStrat - AI 自主交易 Agent v3.2

🤖 **PolyStrat** 是一个基于 AI 的 Polymarket 预测市场自主交易机器人，采用多信号融合策略进行自动化交易决策。

---

## ✨ 核心特性

- **多源新闻聚合** — 6个新闻源并行搜索（GNews、Currents、NewsData、NYTimes、SerpAPI、RSS）
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
├── POLYSTRAT_REVIEW.md     # 评审机制文档
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

详见 [POLYSTRAT_REVIEW.md](POLYSTRAT_REVIEW.md)，包含：
- 6维度评分标准
- 评审 Prompt 模板
- 历史评审记录

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

- ✅ 新闻搜索并行化（6源同时请求）
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

### v3.2 (2026-06-26)

**策略优化（详见 [OPTIMIZATION.md](OPTIMIZATION.md)）:**

**核心算法:**
- [P0] 自适应权重模块形同虚设修复（4信号动态权重替代硬编码）
- [P0] 动态优化器数据泄露修复（`result` 字段替代 `edge` 代理）
- [P0] ML 回测时间序列 CV 防数据泄露
- [P1] 情感/链上信号映射开环修复（自适应斜率+乘数闭环）
- [P1] Fractional Kelly 仓位管理（25% Kelly × 置信度 × 流动性）
- [P1] 动态集成模型权重（基于验证集准确率分配）

**信号融合:**
- [P1] 链上信号连续映射（4离散值→连续+置信度加权）
- [P1] 情感信号映射加宽（0.35 斜率，可自适应调参）
- [P1] 套利信号 5% 权重
- [P1] 风控传入正确置信度（投票置信度替代情感置信度）
- [P1] 高级投票系统动态阈值+置信度公式重构

**工程改进:**
- [P2] 新闻源质量评分真实现（基于交易结果统计）
- [P2] 交易记录补齐信号数据（ml_prob/onchain_signal/news_sources）
- [P2] 自适应权重输出映射调参参数（闭环可控）
- [P2] 断路器初始资金从环境变量读取

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
