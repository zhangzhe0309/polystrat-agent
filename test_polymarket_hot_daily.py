#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
polymarket_hot_daily 单元测试：类别关键词、畸形数据防御。mock Gamma 响应，零网络。
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from polymarket_hot_daily import fetch_hot_markets


def _gamma_market(question, volume24hr=500000, liquidity_num=100000, outcome_prices=None):
    return {
        "question": question,
        "slug": "test-slug",
        "volume24hr": volume24hr,
        "liquidityNum": liquidity_num,
        "outcomePrices": outcome_prices if outcome_prices is not None else '["0.55", "0.45"]',
        "outcomes": '["Yes", "No"]',
    }


def _mock_gamma(markets):
    resp = MagicMock()
    resp.json.return_value = markets
    resp.raise_for_status.return_value = None
    return resp


class TestCategoryClassification(unittest.TestCase):

    @patch("polymarket_hot_daily.requests.get")
    def test_separate_not_misclassified_macro(self, mock_get):
        # "separate" 含子串 "rate"——'rate' 关键词已删，不得误判为 macro
        mock_get.return_value = _mock_gamma([_gamma_market("Will the committee separate the two bills?")])
        results = fetch_hot_markets()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["category"], "general")

    @patch("polymarket_hot_daily.requests.get")
    def test_interest_rate_still_macro(self, mock_get):
        mock_get.return_value = _mock_gamma([_gamma_market("Will the Fed cut interest rates in 2026?")])
        results = fetch_hot_markets()
        self.assertEqual(results[0]["category"], "macro")


class TestMalformedData(unittest.TestCase):

    @patch("polymarket_hot_daily.requests.get")
    def test_malformed_prices_skipped_not_crashed(self, mock_get):
        # outcomePrices 非法 JSON → 该市场被跳过，不崩溃
        bad = _gamma_market("Broken market", outcome_prices="not-json")
        good = _gamma_market("Will the Fed cut interest rates in 2026?")
        mock_get.return_value = _mock_gamma([bad, good])
        results = fetch_hot_markets()
        self.assertEqual(len(results), 1)
        self.assertNotIn("Broken", results[0]["question"])

    @patch("polymarket_hot_daily.requests.get")
    def test_api_failure_returns_empty(self, mock_get):
        mock_get.side_effect = Exception("network down")
        self.assertEqual(fetch_hot_markets(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
