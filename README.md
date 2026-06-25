# 🤖 PolyStrat — AI 自主交易 Agent v2

基于多模型投票、新闻情感分析、链上数据和机器学习的 Polymarket 自动交易系统。

## ✨ 核心功能

| 功能 | 说明 |
|------|------|
| 🔍 **市场扫描** | 自动获取 Polymarket 活跃市场，按流动性排序 |
| 📰 **新闻搜索** | 6 源聚合：GNews、Currents、NewsData、NYTimes、SerpAPI、RSS |
| 🧠 **情感分析** | 关键词 + LLM 双重情感分析 |
| 🤖 **LLM 投票** | 3 模型 Ensemble：Qwen 3.5 + Kimi K2.6 + Llama 3.3 70B |
| ⛓️ **链上信号** | Solana/EVM 大额交易监控 |
| 📊 **ML 集成** | LR + RF + GBDT + KNN 四模型集成 |
| ⚖️ **自适应权重** | 根据历史交易自动调整各指标权重 |
| 🛡️ **风险管理** | 仓位控制、止损、分散投资 |
| 🔄 **去重机制** | 24小时内不重复交易同一市场 |
| 📱 **消息推送** | 自动推送到微信 |

## 📁 文件结构

```
polystrat_agent.py      # 主程序
news_search.py          # 6源新闻搜索模块
sentiment_analysis.py   # 情感分析模块
risk_management.py      # 风险管理模块
onchain_monitor.py      # 链上数据监控
adaptive_weights.py     # 自适应权重模块
ml_optimizer.py         # 机器学习优化模块
multi_platform.py       # 多平台信号模块
tavily_config.py        # Tavily API 双Key配置
```

## ⚙️ 配置

### 环境变量

```bash
# NVIDIA API (LLM)
NVIDIA_API_KEY_2=nvapi-xxx

# Polymarket
POLYMARKET_FUNDER_ADDRESS=0x...
POLYMARKET_PRIVATE_KEY=0x...
SIGNATURE_TYPE=1

# 新闻 API
GNEWS_API_KEY=xxx
CURRENTS_API_KEY=xxx
NEWSDATA_API_KEY=xxx
NYTIMES_API_KEY=xxx
SERPAPI_KEY=xxx
TAVILY_API_KEY=tvly-xxx
```

### 交易参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `DRY_RUN` | `True` | 测试模式，不实际下单 |
| `BET_AMOUNT` | `$2.0` | 单笔下注金额 |
| `EDGE_THRESHOLD` | `0.04` | 优势阈值（4%） |
| `MAX_TRADES_PER_RUN` | `3` | 每轮最大下单数 |
| `DEDUP_HOURS` | `24` | 去重窗口（小时） |
| `MIN_LIQUIDITY` | `$5000` | 最小流动性 |

## 🚀 运行

```bash
# 测试运行
python3 polystrat_agent.py

# 定时运行（每4小时）
# 已配置 Hermes Cron 任务
```

## 📊 权重配置

```
LLM 分析:    38.9%
新闻情感:    29.3%
链上数据:    31.8%
优势阈值:    3.00%
```

## 🔄 最近更新

### 2026-06-25
- ✅ **修复重复下单问题**：添加 24 小时去重机制
- ✅ **新增 NYTimes API**：500次/天
- ✅ **新增 SerpAPI**：每天限制 1 次（100次/月）
- ✅ **Tavily 双 Key**：自动切换
- ✅ **新闻源均衡**：每个来源至少 2 条

### 2026-06-24
- ✅ 新增 NewsData.io（无限次）
- ✅ 修复 LLM 执行顺序
- ✅ 禁用 Azuro API（404）

## ⚠️ 风险提示

- 本系统仅供研究学习，不构成投资建议
- DRY_RUN 模式下为模拟交易，不会实际使用资金
- 切换实盘前请充分测试并理解风险

## 📄 License

MIT License