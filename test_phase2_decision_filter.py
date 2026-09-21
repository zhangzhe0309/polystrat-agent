#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
阶段 2: JEV 盘口初筛门禁单元测试
mock jev_client 传输层，验证阻断阈值边界值、静态拦截、默认值、fail-open。零网络。
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import jev_client
from decision_engine import AutonomousDecisionEngine


def _jev_resp(choice="high_potential", conf=0.9, noul=0.8):
    """构造 jev_ask 成功响应。"""
    m = MagicMock()
    m.status_code = 200
    m.json.return_value = {
        "answers": {
            "tradability": {"choice": choice, "confidence": conf},
            "is_catalyst_driven": {"noul": noul},
        }
    }
    return m


def _market(**overrides):
    base = {
        "title": "Will BTC hit 150k by Dec 31?",
        "description": "Resolves YES if price trades above threshold.",
        "price": 0.42,
        "liquidity": 50000,
    }
    base.update(overrides)
    return base


class TriageTestCase(unittest.TestCase):
    """公共基类：隔离熔断/key。"""

    def setUp(self):
        jev_client.reset()
        env_patcher = patch.dict(os.environ, {"TYPESAFE_API_KEY": "test_key"})
        env_patcher.start()
        self.addCleanup(env_patcher.stop)
        self.engine = AutonomousDecisionEngine()


class TestStaticGate(TriageTestCase):

    @patch("jev_client.requests.post")
    def test_low_liquidity_static_block(self, mock_post):
        res = self.engine.fast_triage_market(_market(liquidity=1500))
        self.assertFalse(res["pass"])
        self.assertEqual(res["category"], "untradable_junk")
        self.assertIn("流动性极低", res["reason"])
        mock_post.assert_not_called()  # 静态拦截零网络


class TestBlockThresholds(TriageTestCase):

    @patch("jev_client.requests.post")
    def test_junk_blocked_at_boundary(self, mock_post):
        # conf=0.60 恰好触发（>=0.60 含边界）
        mock_post.return_value = _jev_resp(choice="untradable_junk", conf=0.60, noul=0.9)
        res = self.engine.fast_triage_market(_market())
        self.assertFalse(res["pass"])
        self.assertIn("长尾死盘", res["reason"])

    @patch("jev_client.requests.post")
    def test_junk_below_boundary_passes(self, mock_post):
        # conf=0.59 未达置信门 → 不按 junk 阻断
        mock_post.return_value = _jev_resp(choice="untradable_junk", conf=0.59, noul=0.9)
        res = self.engine.fast_triage_market(_market())
        self.assertTrue(res["pass"])

    @patch("jev_client.requests.post")
    def test_no_catalyst_blocked_at_boundary(self, mock_post):
        # noul=0.14 < 0.15 且 conf=0.70 → 阻断
        mock_post.return_value = _jev_resp(choice="speculative_acceptable", conf=0.70, noul=0.14)
        res = self.engine.fast_triage_market(_market())
        self.assertFalse(res["pass"])
        self.assertIn("缺乏新闻催化剂", res["reason"])

    @patch("jev_client.requests.post")
    def test_no_catalyst_at_0p15_passes(self, mock_post):
        # noul=0.15 非 <0.15 → 放行
        mock_post.return_value = _jev_resp(choice="speculative_acceptable", conf=0.70, noul=0.15)
        res = self.engine.fast_triage_market(_market())
        self.assertTrue(res["pass"])

    @patch("jev_client.requests.post")
    def test_no_catalyst_low_confidence_passes(self, mock_post):
        # noul=0.10 但 conf=0.69 < 0.70 → 置信门未达，放行
        mock_post.return_value = _jev_resp(choice="speculative_acceptable", conf=0.69, noul=0.10)
        res = self.engine.fast_triage_market(_market())
        self.assertTrue(res["pass"])


class TestDefaultsAndPass(TriageTestCase):

    @patch("jev_client.requests.post")
    def test_defaults_when_answers_empty(self, mock_post):
        # answers 空 → choice 默认 speculative_acceptable, conf 0.5, noul 0.5 → 放行
        m = MagicMock()
        m.status_code = 200
        m.json.return_value = {"answers": {}}
        mock_post.return_value = m
        res = self.engine.fast_triage_market(_market())
        self.assertTrue(res["pass"])
        self.assertEqual(res["category"], "speculative_acceptable")

    @patch("jev_client.requests.post")
    def test_good_market_passes(self, mock_post):
        mock_post.return_value = _jev_resp(choice="high_potential", conf=0.9, noul=0.8)
        res = self.engine.fast_triage_market(_market())
        self.assertTrue(res["pass"])
        self.assertEqual(res["category"], "high_potential")


class TestFailOpen(TriageTestCase):

    @patch("jev_client.requests.post")
    def test_http_error_fail_open(self, mock_post):
        mock_post.return_value = MagicMock(status_code=500, json=MagicMock(return_value={}))
        res = self.engine.fast_triage_market(_market())
        self.assertTrue(res["pass"])
        self.assertEqual(res["category"], "unknown")
        self.assertIn("降级放行", res["reason"])

    @patch("jev_client.requests.post")
    def test_circuit_open_fail_open(self, mock_post):
        # 触发熔断（3 次网络失败）后，初筛放行且不再发网
        mock_post.side_effect = jev_client.requests.exceptions.Timeout()
        for _ in range(3):
            self.engine.fast_triage_market(_market())
        calls_after_breaker = mock_post.call_count
        res = self.engine.fast_triage_market(_market())
        self.assertTrue(res["pass"])
        self.assertIn("circuit_open", res["reason"])
        self.assertEqual(mock_post.call_count, calls_after_breaker)


if __name__ == "__main__":
    unittest.main(verbosity=2)
