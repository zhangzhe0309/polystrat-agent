#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
阶段 4: PolyStrat + JEV 双环架构端到端仿真测试 (E2E Simulation)
"""

import sys
import os
import time

sys.path.insert(0, "/root/polystrat-agent")
from decision_engine import AutonomousDecisionEngine
from sentiment_analysis import analyze_sentiment_jev, analyze_news_sentiment
from guard_rail import guard_rail_check

def test_phase4_e2e():
    print("==================================================")
    print("开始阶段 4 测试: PolyStrat + JEV 双环端到端决策仿真")
    print("==================================================")

    engine = AutonomousDecisionEngine()

    mock_markets = [
        {
            "title": "Will SpaceX successfully catch Super Heavy booster on flight 6?",
            "description": "Resolves YES if booster is caught mid-air by the tower arms.",
            "price": 0.72,
            "liquidity": 180000,
            "category": "Technology"
        },
        {
            "title": "Will random obscure cryptocurrency XYZ reach $1,000,000 by tomorrow morning?",
            "description": "Zero volume meme coin market.",
            "price": 0.01,
            "liquidity": 4000,
            "category": "Crypto"
        }
    ]

    print("\n--- 步骤 1: JEV 外环极速盘口初筛 ---")
    survived_markets = []
    for m in mock_markets:
        t0 = time.time()
        res = engine.fast_triage_market(m)
        cost = round((time.time() - t0) * 1000, 1)
        print(f"盘口: {m['title'][:35]}... -> 放行={res['pass']} | 分类={res.get('category')} | 耗时={cost}ms")
        if res['pass']:
            survived_markets.append(m)

    assert len(survived_markets) == 1, "应该只放行 1 个优质市场，过滤掉 1 个垃圾市场"
    selected_market = survived_markets[0]

    print("\n--- 步骤 2: JEV 新闻情绪快打分 ---")
    mock_news = [
        {"title": "SpaceX Starship successfully completes historic catch milestone", "description": "FAA approves and mission achieves complete breakthrough."}
    ]
    t0 = time.time()
    s_res = analyze_news_sentiment(mock_news, selected_market["title"])
    s_cost = round((time.time() - t0) * 1000, 1)
    print(f"情绪打分: 得分={s_res['overall_score']} | 标签={s_res['overall_label']} | 耗时={s_cost}ms")
    assert s_res['overall_score'] > 0.1, "强利好新闻打分应大于0.1"

    print("\n--- 步骤 3: JEV 毫秒级防踩踏下单守门 ---")
    context = {
        "direction": "Yes",
        "intended_price": selected_market["price"],
        "confidence": 0.75,
        "balance": 1000,
        "trade_size": 2.0,
        "existing_positions": [],
        "regime_data": {"price_std": 0.08}
    }
    t0 = time.time()
    gr_res = guard_rail_check(selected_market, context)
    gr_cost = round((time.time() - t0) * 1000, 1)
    jev_check = next((c for c in gr_res["checks"] if c["name"] == "jev_fast_guardrail"), None)
    print(f"JEV守门检查: pass={jev_check['pass']} | 依据={jev_check['detail']} | 耗时={gr_cost}ms")
    assert jev_check['pass'] is True

    print("\n==================================================")
    print("阶段 4 端到端双环仿真测试全量通过！系统协同无误。")
    print("==================================================")

if __name__ == "__main__":
    test_phase4_e2e()
