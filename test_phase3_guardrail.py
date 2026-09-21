#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
阶段 3: 守门链单元测试（JEV 哨兵移除后）
验证：链结构无 LLM 项、CLOB 真实微结构确定性阻断、相关性/波动率/健康路径。
守门链外部子模块以 sys.modules 注入 mock，规避平台差异（fcntl 等）。零网络。
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import guard_rail
from guard_rail import guard_rail_check


def _mock_deps(circuit_open=False, trade_allowed=True, should_trade=True,
               price_valid=True, price_reason="价格校验通过 spread=1.0% slippage=+0.01"):
    """构造守门链外部依赖的 mock sys.modules 覆盖集。"""
    cb = MagicMock()
    cb.check_breaker.return_value = not circuit_open

    tl = MagicMock()
    tl.check_trade_allowed.return_value = (trade_allowed, "限额内" if trade_allowed else "超出限额")

    rm = MagicMock()
    rm.should_trade.return_value = (should_trade, "风险通过" if should_trade else "风险过高")

    cv = MagicMock()
    cv.validate_price_before_trade.return_value = {
        "valid": price_valid,
        "real_price": 0.55,
        "spread_pct": 0.01,
        "edge_after_spread": 0.02,
        "original_price": 0.54,
        "price_slippage": 0.01,
        "reason": price_reason,
    }
    return {"circuit_breaker": cb, "trade_limits": tl, "risk_management": rm, "clob_validator": cv}


def _market(**overrides):
    base = {
        "title": "Will BTC hit 150k by Dec 31?",
        "category": "Crypto",
        "price": 0.54,
        "liquidity": 80000,
        "condition_id": "0xabc",
    }
    base.update(overrides)
    return base


def _context(**overrides):
    base = {
        "existing_positions": [],
        "regime_data": {"price_std": 0.05},
        "balance": 1000,
        "trade_size": 20,
        "direction": "Yes",
        "token_id": "tok_123",
        "intended_price": 0.54,
        "confidence": 0.7,
        "news_sentiment": 0.2,
        "edge": 0.08,
    }
    base.update(overrides)
    return base


class ChainTestCase(unittest.TestCase):
    """公共基类：默认健康依赖。"""

    def setUp(self):
        self.deps = _mock_deps()
        modules_patcher = patch.dict(sys.modules, self.deps)
        modules_patcher.start()
        self.addCleanup(modules_patcher.stop)


class TestChainStructure(ChainTestCase):

    def test_jev_check_absent_from_chain(self):
        result = guard_rail_check(_market(), _context())
        names = [c["name"] for c in result["checks"]]
        self.assertEqual(
            names,
            ["circuit_breaker", "trade_limits", "correlation", "volatility", "risk_management", "clob_spread"],
        )
        self.assertNotIn("jev_fast_guardrail", names)

    def test_jev_function_removed(self):
        # JEV 哨兵已从本模块彻底移除（职责归 clob_spread 真实数据 + 初筛语义层）
        self.assertFalse(hasattr(guard_rail, "check_jev_fast_guardrail"))
        self.assertFalse(hasattr(guard_rail, "JEV_API_ENDPOINT"))
        self.assertNotIn("jev_fast_guardrail", guard_rail.GUARDRAIL_CONFIG["checks"])


class TestClobMicrostructureBlock(ChainTestCase):
    """确定性微结构阻断：取代原 JEV 哨兵声称的防踩踏能力。"""

    def test_clob_wide_spread_blocks(self):
        deps = _mock_deps(price_valid=False, price_reason="Spread 8.0%>2%，利润被吃掉")
        with patch.dict(sys.modules, deps):
            result = guard_rail_check(_market(), _context())
        self.assertFalse(result["approved"])
        self.assertIn("CLOB", result["block_reason"])

    def test_clob_shallow_depth_blocks(self):
        deps = _mock_deps(price_valid=False, price_reason="订单簿深度不足 $3000<$10000")
        with patch.dict(sys.modules, deps):
            result = guard_rail_check(_market(), _context())
        self.assertFalse(result["approved"])


class TestOtherChecks(ChainTestCase):

    def test_correlation_blocks_third_same_event(self):
        # 同一事件组（世界杯）已有 2 笔持仓，第 3 个同组市场被相关性检查拦截
        positions = [
            {"title": "Will France win the World Cup?", "category": "Sports", "direction": "Yes", "amount": 10},
            {"title": "Will Brazil win the World Cup?", "category": "Sports", "direction": "Yes", "amount": 10},
        ]
        market = _market(title="Will Argentina win the World Cup?", category="Sports")
        result = guard_rail_check(market, _context(existing_positions=positions))
        self.assertFalse(result["approved"])
        self.assertIn("相关性", result["block_reason"])

    def test_volatility_extreme_scales(self):
        # price_std=0.40 > 0.35 极端波动阈值 → 仓位缩至 20%，但不阻断
        result = guard_rail_check(_market(), _context(regime_data={"price_std": 0.40}))
        self.assertTrue(result["approved"])
        self.assertAlmostEqual(result["position_scale"], 0.2)

    def test_healthy_path_approved(self):
        result = guard_rail_check(_market(), _context())
        self.assertTrue(result["approved"])
        self.assertEqual(result["block_reason"], "")
        self.assertTrue(all(c["pass"] for c in result["checks"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
