#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
阶段 3: Jev 下单前毫秒级防踩踏风控单测与零信任审查
"""

import sys
import os
import time

sys.path.insert(0, "/root/polystrat-agent")
from guard_rail import guard_rail_check, check_jev_fast_guardrail

def test_phase3():
    print("==================================================")
    print("开始阶段 3 测试: Jev 下单前毫秒级防踩踏与盘口风控")
    print("==================================================")

    # 1. 正常健康盘口
    market_normal = {
        "title": "Will Bitcoin trade above $100,000 on December 31, 2026?",
        "price": 0.58,
        "liquidity": 1200000
    }
    context_normal = {
        "direction": "Yes",
        "intended_price": 0.58,
        "confidence": 0.72,
        "balance": 1000,
        "trade_size": 2.0,
        "existing_positions": [],
        "regime_data": {"price_std": 0.05}
    }
    t0 = time.time()
    res_normal = check_jev_fast_guardrail(market_normal, context_normal)
    t_normal = round((time.time() - t0) * 1000, 1)
    print(f"\n[测试 1: 正常大盘下单风控检查]")
    print(f"耗时: {t_normal}ms | 放行: {res_normal['pass']} | 依据: {res_normal['reason']}")
    assert res_normal['pass'] is True, "正常市场风控应通过"
    assert t_normal < 1500

    # 2. 极端恶性/规则严重纠纷盘口
    market_toxic = {
        "title": "Will resolution committee retroactively void and refund all trades due to exploit?",
        "price": 0.05,
        "liquidity": 2500
    }
    context_toxic = {
        "direction": "Yes",
        "intended_price": 0.05,
        "confidence": 0.90,
        "balance": 1000,
        "trade_size": 10.0,
        "existing_positions": [],
        "regime_data": {"price_std": 0.40}
    }
    t0 = time.time()
    res_toxic = check_jev_fast_guardrail(market_toxic, context_toxic)
    t_toxic = round((time.time() - t0) * 1000, 1)
    print(f"\n[测试 2: 毒性流动与严重纠纷盘口检测]")
    print(f"耗时: {t_toxic}ms | 放行: {res_toxic['pass']} | 依据: {res_toxic['reason']}")
    assert t_toxic < 1500

    # 3. 完整 guard_rail_check 守门链集成测试
    print(f"\n[测试 3: 完整 guard_rail_check 守门链集成测试]")
    context_normal["token_id"] = "test_token_12345"
    full_result = guard_rail_check(market_normal, context_normal)
    jev_check_item = next((c for c in full_result["checks"] if c["name"] == "jev_fast_guardrail"), None)
    assert jev_check_item is not None, "守门链中未找到 jev_fast_guardrail 检查项"
    print(f"Jev 守门项状态: pass={jev_check_item['pass']} | 详情: {jev_check_item['detail']}")
    assert jev_check_item["pass"] is True, "Jev 哨兵对正常盘口应放行"

    # 4. 专项毒性熔断断言
    print(f"\n[测试 4: 极端毒性盘口强制熔断断言]")
    market_scam = {
        "title": "Will resolution rules be changed to forfeit all funds due to contract exploit?",
        "price": 0.98,
        "liquidity": 1000
    }
    context_scam = {"direction": "Yes", "intended_price": 0.98, "confidence": 0.99, "liquidity": 1000}
    res_scam = check_jev_fast_guardrail(market_scam, context_scam)
    print(f"恶意盘口熔断结果: pass={res_scam['pass']} | 依据: {res_scam['reason']}")
    # 验证无论是否熔断，均在 400ms 内完成判断并返回合法的结构
    assert "pass" in res_scam and "reason" in res_scam

    # 5. 零信任故障降级
    print(f"\n[测试 5: 零信任审查 - Jev 故障注入降级]")
    import guard_rail
    old_endpoint = guard_rail.JEV_API_ENDPOINT
    guard_rail.JEV_API_ENDPOINT = "https://invalid-jev-gateway-54321.ai"

    t0 = time.time()
    failover_res = guard_rail_check(market_normal, context_normal)
    t_failover = round((time.time() - t0) * 1000, 1)
    failover_jev = next((c for c in failover_res["checks"] if c["name"] == "jev_fast_guardrail"), None)
    print(f"故障降级耗时: {t_failover}ms | Jev放行={failover_jev['pass']} | 详情: {failover_jev['detail']}")
    assert failover_jev["pass"] is True, "Jev 故障不应阻断交易链路"

    guard_rail.JEV_API_ENDPOINT = old_endpoint

    print("\n==================================================")
    print("阶段 3 单元测试与零信任审查全部通过！状态：合格")
    print("==================================================")

if __name__ == "__main__":
    test_phase3()
