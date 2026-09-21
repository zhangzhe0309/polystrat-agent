#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
阶段 4: PolyStrat + JEV 双环端到端仿真（全 mock，零网络）
验证：初筛→情感→守门的闭环协同；下单守门段零 JEV 调用；全宕机降级链。
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import jev_client
import sentiment_analysis
import guard_rail
from decision_engine import AutonomousDecisionEngine
from sentiment_analysis import analyze_news_sentiment
from guard_rail import guard_rail_check


def _http(json_body):
    m = MagicMock()
    m.status_code = 200
    m.json.return_value = json_body
    return m


def _mock_guard_deps():
    """守门链外部依赖 mock（健康路径）。"""
    cb = MagicMock(); cb.check_breaker.return_value = True
    tl = MagicMock(); tl.check_trade_allowed.return_value = (True, "限额内")
    rm = MagicMock(); rm.should_trade.return_value = (True, "风险通过")
    cv = MagicMock(); cv.validate_price_before_trade.return_value = {
        "valid": True, "real_price": 0.55, "spread_pct": 0.01, "reason": "价格校验通过",
    }
    return {"circuit_breaker": cb, "trade_limits": tl, "risk_management": rm, "clob_validator": cv}


MOCK_MARKETS = [
    {
        "title": "Will SpaceX catch the Super Heavy booster on the next flight?",
        "description": "Resolves YES if booster is caught mid-air by the tower arms.",
        "price": 0.72, "liquidity": 180000, "category": "Technology",
    },
    {
        "title": "Will random obscure coin XYZ reach $1,000,000 by tomorrow?",
        "description": "Zero volume meme coin market with no catalyst.",
        "price": 0.01, "liquidity": 4000, "category": "Crypto",
    },
]


class E2ETestCase(unittest.TestCase):

    def setUp(self):
        jev_client.reset()
        self.addCleanup(jev_client.reset)  # 结束后恢复，防止全局熔断状态泄漏到同进程其他用例
        sentiment_analysis._sentiment_cache.clear()
        env_patcher = patch.dict(os.environ, {"TYPESAFE_API_KEY": "test_key"})
        env_patcher.start()
        self.addCleanup(env_patcher.stop)
        self.engine = AutonomousDecisionEngine()


class TestE2EHappyPath(E2ETestCase):

    def test_e2e_triage_to_guardrail(self):
        # JEV 响应序列：市场1 放行(high_potential)、市场2 拦截(junk)、存活市场1的情感打分
        triage_hot = _http({"answers": {
            "tradability": {"choice": "high_potential", "confidence": 0.9},
            "is_catalyst_driven": {"noul": 0.85},
        }})
        triage_junk = _http({"answers": {
            "tradability": {"choice": "untradable_junk", "confidence": 0.9},
            "is_catalyst_driven": {"noul": 0.05},
        }})
        sentiment_ok = _http({"answers": {
            "sentiment": {"score": 4, "confidence": 0.9},
            "is_material": {"noul": 0.9},
        }})

        with patch("jev_client.requests.post") as mock_post:
            mock_post.side_effect = [triage_hot, triage_junk, sentiment_ok]

            # --- 步骤 1: JEV 外环初筛 ---
            survived = [m for m in MOCK_MARKETS if self.engine.fast_triage_market(m)["pass"]]
            self.assertEqual(len(survived), 1)
            self.assertIn("SpaceX", survived[0]["title"])

            # --- 步骤 2: 存活市场新闻情感 ---
            news = [{"title": "Booster catch milestone achieved", "description": "Full success."}]
            s_res = analyze_news_sentiment(news, survived[0]["title"])
            self.assertGreater(s_res["overall_score"], 0.1)

            # --- 步骤 3: 下单守门（不含 JEV；微结构归 clob_spread） ---
            with patch.dict(sys.modules, _mock_guard_deps()):
                ctx = {
                    "direction": "Yes", "intended_price": survived[0]["price"],
                    "confidence": 0.75, "balance": 1000, "trade_size": 2.0,
                    "existing_positions": [], "regime_data": {"price_std": 0.08},
                    "news_sentiment": s_res["overall_score"],
                    "token_id": "tok_1",
                }
                gr = guard_rail_check(survived[0], ctx)
            self.assertTrue(gr["approved"])

            # 核心断言：全程 JEV 恰好 3 次调用（2 初筛 + 1 情感），守门段零 JEV
            self.assertEqual(mock_post.call_count, 3)
            self.assertNotIn("jev_fast_guardrail", [c["name"] for c in gr["checks"]])


class TestE2ETotalOutage(E2ETestCase):

    def test_e2e_jev_total_outage_degrades_clean(self):
        # JEV 全部超时 → 熔断接管；初筛 fail-open、情感降级、守门不受影响
        with patch("jev_client.requests.post") as mock_post, \
                patch("sentiment_analysis.analyze_sentiment_with_llm") as mock_llm:
            mock_post.side_effect = jev_client.requests.exceptions.Timeout()
            mock_llm.return_value = {"score": 0.4, "label": "positive", "confidence": 0.8,
                                     "keywords": [], "explanation": "llm fallback"}

            survived = [m for m in MOCK_MARKETS if self.engine.fast_triage_market(m)["pass"]]
            self.assertEqual(len(survived), 2)  # 全部 fail-open 放行

            s_res = analyze_news_sentiment(
                [{"title": "some headline", "description": "text"}], "mkt")
            mock_llm.assert_called()  # 情感降级到 LLM 兜底

            with patch.dict(sys.modules, _mock_guard_deps()):
                ctx = {
                    "direction": "Yes", "intended_price": 0.5, "confidence": 0.7,
                    "balance": 1000, "trade_size": 2.0, "existing_positions": [],
                    "regime_data": {"price_std": 0.05}, "news_sentiment": 0,
                    "token_id": "tok_1",
                }
                gr = guard_rail_check(survived[0], ctx)
            self.assertTrue(gr["approved"])

            # 熔断生效：2 次初筛 + 1 次情感 = 3 次真实发网后，后续调用零网络
            self.assertLessEqual(mock_post.call_count, 3)
            self.assertTrue(jev_client.get_stats()["circuit_open"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
