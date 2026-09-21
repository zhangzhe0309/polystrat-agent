#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
阶段 2: Jev 盘口前置初筛门禁单测与零信任审查
"""

import sys
import os
import time

sys.path.insert(0, "/root/polystrat-agent")
from decision_engine import AutonomousDecisionEngine

def test_phase2():
    print("==================================================")
    print("开始阶段 2 测试: Jev 盘口极速前置初筛与门禁断言")
    print("==================================================")

    engine = AutonomousDecisionEngine()

    # 1. 优质高潜力市场
    market_hot = {
        "title": "Fed interest rate cut in upcoming October FOMC meeting?",
        "description": "Resolves YES if Federal Reserve cuts rates by at least 25bps at the October meeting.",
        "price": 0.65,
        "liquidity": 350000
    }
    t0 = time.time()
    res_hot = engine.fast_triage_market(market_hot)
    t_hot = round((time.time() - t0) * 1000, 1)
    print(f"\n[测试 1: 优质宏观盘口初筛]")
    print(f"耗时: {t_hot}ms | 放行: {res_hot['pass']} | 分类: {res_hot['category']} | 原因: {res_hot['reason']}")
    assert res_hot['pass'] is True, "优质盘口应被放行"
    assert res_hot['category'] in ("high_potential", "speculative_acceptable")
    assert t_hot < 1500

    # 2. 荒谬/超长尾死盘
    market_junk = {
        "title": "Will humans confirm existence of ghosts or paranormal spirits before year 2100?",
        "description": "Resolves YES if UN officially declares existence of ghosts.",
        "price": 0.02,
        "liquidity": 6000
    }
    t0 = time.time()
    res_junk = engine.fast_triage_market(market_junk)
    t_junk = round((time.time() - t0) * 1000, 1)
    print(f"\n[测试 2: 荒谬长尾垃圾盘口拦截]")
    print(f"耗时: {t_junk}ms | 放行: {res_junk['pass']} | 分类: {res_junk['category']} | 原因: {res_junk['reason']}")
    assert res_junk['pass'] is False, "垃圾盘口应被拦截"
    assert t_junk < 1500

    # 3. 超低流动性静态拦截
    market_low_liq = {
        "title": "Local municipal election turnout in small village",
        "description": "Turnout numbers",
        "price": 0.50,
        "liquidity": 1500
    }
    t0 = time.time()
    res_low_liq = engine.fast_triage_market(market_low_liq)
    t_low = round((time.time() - t0) * 1000, 1)
    print(f"\n[测试 3: 低流动性前置静态拦截]")
    print(f"耗时: {t_low}ms | 放行: {res_low_liq['pass']} | 原因: {res_low_liq['reason']}")
    assert res_low_liq['pass'] is False
    assert t_low < 10, "静态拦截耗时应极低 (<10ms)"

    # 4. 零信任审查: 故障注入模拟 Jev 接口挂掉
    print(f"\n[测试 4: 零信任审查 - Jev 接口故障降级]")
    import decision_engine
    old_endpoint = decision_engine.JEV_API_ENDPOINT
    decision_engine.JEV_API_ENDPOINT = "https://invalid-jev-domain-12345.ai/v1"
    
    t0 = time.time()
    res_failover = engine.fast_triage_market(market_hot)
    t_fail = round((time.time() - t0) * 1000, 1)
    print(f"降级耗时: {t_fail}ms | 放行: {res_failover['pass']} | 原因: {res_failover['reason']}")
    assert res_failover['pass'] is True, "Jev 故障时应安全放行降级至后续流程"
    
    # 恢复配置
    decision_engine.JEV_API_ENDPOINT = old_endpoint

    print("\n==================================================")
    print("阶段 2 单元测试与零信任审查全部通过！状态：合格")
    print("==================================================")

if __name__ == "__main__":
    test_phase2()
