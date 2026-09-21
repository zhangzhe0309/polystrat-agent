#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
阶段 1: Jev 极速情绪分析通道单测与零信任审查
"""

import sys
import os
import time

sys.path.insert(0, "/root/polystrat-agent")
from sentiment_analysis import analyze_sentiment_jev, analyze_news_sentiment

def test_phase1():
    print("==================================================")
    print("开始阶段 1 测试: Jev System 1 极速情绪打分与自愈降级")
    print("==================================================")

    # 1. 强利好测试
    text_bull = "Candidate surges 10 points in the latest poll, leading rival decisively."
    t0 = time.time()
    res_bull = analyze_sentiment_jev(text_bull, "Will Candidate win the election?")
    t_bull = round((time.time() - t0) * 1000, 1)
    print(f"\n[测试 1: 强利好新闻打分]")
    print(f"耗时: {t_bull}ms | 得分: {res_bull['score']} | 标签: {res_bull['label']} | 置信度: {res_bull['confidence']}")
    assert res_bull['score'] > 0.1, "利好打分断言失败"
    assert res_bull['label'] == "positive", "利好标签断言失败"
    assert t_bull < 2000, "Jev 响应时间过长"

    # 2. 强利空测试
    text_bear = "Severe crash reported, company announces bankruptcy and halts operations."
    t0 = time.time()
    res_bear = analyze_sentiment_jev(text_bear, "Will Company stay solvent in 2026?")
    t_bear = round((time.time() - t0) * 1000, 1)
    print(f"\n[测试 2: 强利空新闻打分]")
    print(f"耗时: {t_bear}ms | 得分: {res_bear['score']} | 标签: {res_bear['label']} | 置信度: {res_bear['confidence']}")
    assert res_bear['score'] < -0.1, "利空打分断言失败"
    assert res_bear['label'] == "negative", "利空标签断言失败"

    # 3. 新闻列表聚合打分 (analyze_news_sentiment)
    news_batch = [
        {"title": "Massive rally observed across major markets", "text": "Stocks and crypto soaring."},
        {"title": "Inflation numbers cool down more than expected", "text": "Good news for consumer prices."}
    ]
    t0 = time.time()
    batch_res = analyze_news_sentiment(news_batch, "Market Economy 2026")
    t_batch = round((time.time() - t0) * 1000, 1)
    print(f"\n[测试 3: 新闻列表聚合打分]")
    print(f"耗时: {t_batch}ms | 综合得分: {batch_res['overall_score']:.3f} | 标签: {batch_res['overall_label']}")
    assert batch_res['overall_score'] > 0.1
    assert batch_res['overall_label'] == "positive"

    # 4. 零信任审查: 故障注入模拟 Jev 接口不可达
    print(f"\n[测试 4: 零信任审查 - Jev 故障自愈降级]")
    import sentiment_analysis
    old_key = sentiment_analysis.TYPESAFE_API_KEY
    sentiment_analysis.TYPESAFE_API_KEY = "invalid_key_999"
    
    t0 = time.time()
    res_degraded = analyze_sentiment_jev("Market update neutral report")
    t_deg = round((time.time() - t0) * 1000, 1)
    print(f"Jev 异常时响应: source={res_degraded.get('source')} | 耗时: {t_deg}ms")
    assert res_degraded.get("source") in ("jev_failed", "jev_error")
    
    # 验证 analyze_news_sentiment 在 Jev 故障时是否平滑降级
    batch_degraded = analyze_news_sentiment(news_batch, "Market Economy")
    print(f"降级后聚合分析: 得分={batch_degraded['overall_score']:.3f} | 状态: 平滑降级通过")
    assert "overall_score" in batch_degraded

    # 恢复 Key
    sentiment_analysis.TYPESAFE_API_KEY = old_key

    print("\n==================================================")
    print("阶段 1 单元测试与零信任审查全部通过！状态：合格")
    print("==================================================")

if __name__ == "__main__":
    test_phase1()
