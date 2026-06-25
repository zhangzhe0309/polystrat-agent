# PolyStrat 持续评审机制

## 📋 评审 Prompt 模板

当需要评审 PolyStrat 工程时，使用以下 Prompt：

---

### 评审 Prompt

```
请作为高级开发者对 PolyStrat 交易机器人进行全面评审。

评审维度（每项 0-100 分）：

1. **完整性 (Completeness)**
   - 功能是否完整实现
   - 边界条件是否处理
   - 错误场景是否覆盖

2. **正确性 (Correctness)**
   - 业务逻辑是否正确
   - 数据计算是否准确
   - 状态转换是否合理

3. **健壮性 (Robustness)**
   - 异常处理是否完善
   - 并发安全是否有保障
   - 资源泄漏是否避免

4. **安全性 (Security)**
   - 敏感信息是否保护
   - API Key 是否安全存储
   - 输入验证是否充分

5. **性能 (Performance)**
   - 是否有性能瓶颈
   - 缓存策略是否合理
   - 并行处理是否利用

6. **可维护性 (Maintainability)**
   - 代码结构是否清晰
   - 日志是否充分
   - 文档是否完善

请读取以下文件后给出评分和改进建议：
- /root/.hermes/profiles/life/scripts/polystrat_agent.py (主程序)
- /root/.hermes/profiles/life/scripts/news_search.py (新闻搜索)
- /root/.hermes/profiles/life/scripts/sentiment_analysis.py (情感分析)
- /root/.hermes/profiles/life/scripts/risk_management.py (风险管理)
- /root/.hermes/profiles/life/scripts/ml_optimizer.py (ML优化)
- /root/.hermes/profiles/life/scripts/adaptive_weights.py (自适应权重)
- /root/.hermes/profiles/life/scripts/dynamic_optimizer.py (动态优化)
- /root/.hermes/profiles/life/scripts/onchain_monitor.py (链上监控)
- /root/.hermes/profiles/life/scripts/multi_platform.py (多平台)
- /root/.hermes/profiles/life/scripts/smart_keywords.py (智能关键词)
- /root/.hermes/profiles/life/scripts/polystrat_logger.py (日志系统)

输出格式：
## 评审报告

### 总分: XX/100

### 各维度评分:
1. 完整性: XX/100 - [简要说明]
2. 正确性: XX/100 - [简要说明]
3. 健壮性: XX/100 - [简要说明]
4. 安全性: XX/100 - [简要说明]
5. 性能: XX/100 - [简要说明]
6. 可维护性: XX/100 - [简要说明]

### 关键发现:
- [P0 严重问题]
- [P1 重要问题]
- [P2 改进建议]

### 修复建议:
[具体修复方案]
```

---

## 🔄 评审流程

### 1. 触发条件
- 代码重大修改后
- 定期（每周/每月）
- 发现问题需要诊断时

### 2. 评审步骤
1. 复制上面的 Prompt
2. 发送给独立的 AI 模型（非 PolyStrat 内置模型）
3. 收集评审报告
4. 按优先级修复问题
5. 更新评审基线

### 3. 评分标准

| 分数范围 | 等级 | 说明 |
|---------|------|------|
| 90-100 | A | 优秀，生产就绪 |
| 80-89 | B | 良好，可接受 |
| 70-79 | C | 一般，需要改进 |
| 60-69 | D | 较差，需要重构 |
| <60 | F | 不合格，需要重写 |

---

## 📊 评审历史记录

### 2026-06-25 评审（本次）

**评审模型**: Xiaomi MiMo v2.5
**总分**: 78/100

**各维度评分**:
1. 完整性: 80/100 - 功能基本完整，边界处理有改进空间
2. 正确性: 75/100 - 胜率计算已修复，ML标签已修正
3. 健壮性: 72/100 - 文件锁已添加，异常处理需加强
4. 安全性: 85/100 - API Key 已迁移，无硬编码
5. 性能: 78/100 - 并行搜索已实现，缓存已添加
6. 可维护性: 76/100 - 日志系统已添加，模块化良好

**本次修复**:
- ✅ P0: API Key 迁移到环境变量
- ✅ P0: 重复下单 BUG (condition_id 去重)
- ✅ P0: 竞态条件 (文件锁)
- ✅ P1: 胜率计算逻辑修复
- ✅ P1: ML 标签定义修正
- ✅ P1: 仓位计算逻辑统一
- ✅ P1: 新闻搜索并行化 + 缓存
- ✅ P2: 错误处理 + 日志系统

**待改进**:
- [ ] 添加单元测试框架
- [ ] 实现结算结果自动追踪
- [ ] 添加性能监控仪表盘
- [ ] 完善 API 限流处理

---

## 🎯 目标分数

**短期目标**: 85/100 (B+)
**中期目标**: 90/100 (A)
**长期目标**: 95/100 (A+)

---

*最后更新: 2026-06-25*
