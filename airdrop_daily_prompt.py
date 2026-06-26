#!/usr/bin/env python3
"""
加密空投情报日报 - Agent mode
- 搜索 X/Twitter 热门空投话题
- 分析质量和成本
- 推荐 3-5 个值得跟进的项目
"""

import sys

PROMPT = """
你是加密空投研究员。任务：
1. 搜索 X/Twitter 上过去 24 小时最热门的空投讨论（关键词：#airdrop #crypto #defi）
2. 筛选出 3-5 个值得关注的项目，标准：
   - 有知名 VC 投资（a16z, Paradigm, Binance Labs, Coinbase Ventures 等）
   - 交互成本<50 USD（Gas 低）
   - 社区热度高（X 讨论多）
   - 尚未发币（无 token）
3. 对每个项目输出：
   - 项目名称 + 链
   - 投资背景
   - 交互步骤（3-5 步）
   - 预估成本
   - 风险评级（低/中/高）

输出格式（markdown）：
# 🔍 空投情报日报
日期：YYYY-MM-DD

## 📌 推荐项目

### 1. [项目名] ([链名])
- **投资：** VC 名
- **交互：** 步骤 1 → 步骤 2 → 步骤 3
- **成本：** ~$XX
- **风险：** 低/中/高

### 2. ...

## ⚠️ 风险提示
- 空投不确定性高，可能无回报
- 链上交互有 smart contract 风险
- Gas 费波动可能增加成本

数据来源：X/Twitter
"""

print(PROMPT)