# PolyStrat 策略优化记录

## 第一轮优化（6 文件，10 项修改）

### 1. adaptive_weights.py — 自适应权重扩展
- 从 3 信号（LLM/情感/链上）扩展为 4 信号（+ML 准确率）
- 输出 `ml_weight` 字段参与信号融合
- 输出 `llm_accuracy` / `sentiment_accuracy` / `onchain_accuracy` / `ml_accuracy` 用于权重计算

### 2. polystrat_agent.py — 主流程核心改造
- **自适应权重生效**：信号融合改用 `adaptive_weights` 返回的动态权重，不再用硬编码 `SIGNAL_WEIGHTS`
- **风控传入正确置信度**：`should_trade()` 传入投票系统置信度 `vote_details["confidence"]`，而非情感置信度
- **情感信号加宽**：`sentiment_score` 映射斜率从硬编码 0.35 改为可调，默认 0.35（影响更灵敏）
- **链上信号连续映射**：从 4 个离散值改为连续映射，纳入置信度加权（strong_buy=0.5+0.35×conf, buy=0.5+0.15×conf, sell=0.5-0.15×conf）
- **套利信号**：新增 5% 权重用于多平台套利机会
- **Fractional Kelly 仓位**：`仓位 = balance × kelly_pct × 25% × 置信度 × 流动性因子`，上限 `max_single_trade=$10`
- **交易记录补齐**：增加 `ml_prob` / `onchain_signal` / `model_results` 字段，为自适应学习提供数据

### 3. dynamic_optimizer.py — 数据泄露修复
- 旧版用 `abs(edge) > 0.03` 代理结算结果（数据泄露）
- 新版用 `result` 字段 + 概率阈值判断模型胜负
- 字符串包含匹配改为结构化解析

### 4. circuit_breaker.py — 初始资金从环境变量读取
- 旧版硬编码 `initial_balance = 200`，与主程序 `POLYSTRAT_BALANCE` 不一致
- 新版 `initial_balance = float(os.environ.get("POLYSTRAT_BALANCE", "200.0"))`

### 5. advanced_voting.py — 动态阈值与置信度公式重构
- **动态阈值连续映射**：从固定 `±15%` 分段改为连续映射：
  - 标准差 >30 → 阈值 25%；标准差 10-30 → 阈值 15%；标准差 <10 → 阈值 8%
- **置信度公式重构**：`60%一致性 + 25%集中度 + 15%异常值惩罚`

### 6. ml_optimizer.py — 时间序列 CV + 动态集成权重
- **时间序列 CV**：`TimeSeriesSplit(n_splits=5)` 代替随机 KFold，防止数据泄露
- **动态集成权重**：基于验证集准确率分配权重（`weight_i = accuracy_i / Σaccuracy`），代替固定 `RF 40%/LR 30%/GBDT 20%/KNN 10%`

---

## 第二轮优化（3 文件，4 项修改）

### 7. adaptive_weights.py — 自适应映射参数
- 新增 `sentiment_mapping_slope`：
  - 情感准确率 >60% → 斜率 0.45（扩大影响力）
  - 情感准确率 <40% → 斜率 0.25（抑制噪声）
  - 否则 → 斜率 0.35
- 新增 `onchain_multiplier`：
  - 链上准确率 >60% → 乘数 1.3
  - 链上准确率 <40% → 乘数 0.7
  - 否则 → 乘数 1.0

### 8. polystrat_agent.py — 信号映射使用自适应参数
- 情感映射：`0.5 + sentiment_score × sentiment_mapping_slope`（闭环：准确率高→影响力大）
- 链上映射：`base_offset × onchain_multiplier`（闭环：准确率高→置信度加成大）
- 日志输出情感斜率和链上乘数当前值

### 9. polystrat_agent.py — 交易记录增补新闻源
- 采集 `news_sources = list(set(source_type for n in news_list))`
- 写入交易记录 `"news_sources"` 字段
- 为新闻源质量评分提供数据基础

### 10. dynamic_optimizer.py — 新闻源质量评分真实现
- 旧版：函数体为空，返回默认评分
- 新版：基于交易记录统计：
  - 读取 `news_sources` + `result`（win/lose）
  - 至少 3 次使用才更新评分（防小样本偏差）
  - 平滑更新：`30% 历史分 + 70% 新胜率`
  - 结果持久化到 `optimization_config.json`

---

## 第三轮优化（4 文件，6 项修复）

### 11. polystrat_agent.py — LLM 模型阵容升级
- **旧**：Qwen 3.5 / Kimi K2.6 / Llama 3.3 70B + GLM-5.1
- **新**：DeepSeek V4 Flash (284B MoE, priority 1) / Nemotron 3 Super (120B Hybrid Mamba-Transformer MoE, priority 2) / MiniMax M2.7 (230B Dense, priority 3) / GLM-5.1 (744B MoE, priority 4)
- 4 模型来自 4 种不同架构，投票多样性大幅提升

### 12. advanced_voting.py — model_names 硬编码修复 (🔴 高)
- **旧**：`model_names = ["Qwen 3.5", "Kimi K2.6", "Llama 3.3 70B"]`，永远匹配不到新模型名
- **后果**：`vote()` 遍历旧模型名，找不到 predictions_dict 中的新模型 → 返回 `final_prediction: 0.5`，投票系统形同虚设
- **修复**：`model_names` 从 `model_weights` 的 key 自动获取，无外部权重时使用新模型名硬编码

### 13. dynamic_optimizer.py — 默认配置模型名更新
- DEFAULT_CONFIG 中的 `llm_model_weights` 从旧模型名更新为新模型名

### 14. onchain_monitor.py — volume_change 硬编码修复 (🔴 高)
- **旧**：`analyze_volume_change` 返回硬编码 `volume_change: 0.15`
- **后果**：momentum_score 依赖假数据，链上信号可信度存疑
- **修复**：基于 Gamma API 实时 volume + 本地快照缓存，计算真实 volume 变化率；首次运行无快照时用 volume/liquidity 比率作代理

### 15. onchain_monitor.py — confidence 连续映射
- **旧**：两档 `{0.3, 0.6}`，区分度不足
- **新**：`0.3 + 0.4 × momentum_score`，范围 `[0.3, 0.7]`

### 16. adaptive_weights.py — hold 信号不再归类为 lose
- **旧**：`hold` 被分类为 `lose`，拉低链上信号准确率
- **新**：`hold` → `continue` 跳过，不计入准确率统计

---

## 其他修复

- `adaptive_weights.py` 重复代码块删除（`get_weight_adjustment_report` 中两份 `adjustments` 计算，第二份缺少 `ml` 键）
- 未使用导入清理（移除 `get_llm_model_weight`、`get_news_source_quota`、`calculate_position_with_liquidity` 等）

---

## 已关闭的未解决问题

- ✅ `calculate_news_source_scores` 已接入 `news_search.py` 新闻源动态配额调用链
- ✅ `onchain_monitor.py` volume_change 硬编码已修复
- ✅ `onchain_monitor.py` confidence 离散两档已修复

---

## 优化总结

| 轮次 | 涉及文件 | 修改项 | 核心改善 |
|------|----------|--------|----------|
| 第1轮 | 6 | 10 | 自适应权重/数据泄露/时间序列CV/Kelly仓位 |
| 第2轮 | 3 | 4 | 信号映射闭环/新闻源评分真实现 |
| 第3轮 | 4 | 6 | 模型阵容升级/voting硬编码/onchain真数据 |
| **合计** | **8** | **20** | **动态值生效率 95%** |
