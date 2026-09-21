#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
阶段 1: Jev 情感打分单元测试
mock jev_client 传输层，验证归一化/clamp/标签边界/降级标签/缓存/阶梯兜底。零网络。
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import jev_client
import sentiment_analysis
from sentiment_analysis import analyze_sentiment_jev, analyze_news_sentiment


def _jev_resp(sentiment_ans=None, material_ans=None):
    """构造 jev_ask 成功返回的 answers 对应 HTTP 响应。"""
    answers = {}
    if sentiment_ans is not None:
        answers["sentiment"] = sentiment_ans
    if material_ans is not None:
        answers["is_material"] = material_ans
    m = MagicMock()
    m.status_code = 200
    m.json.return_value = {"answers": answers}
    return m


class SentimentJevTestCase(unittest.TestCase):
    """公共基类：隔离熔断/key/情感缓存。"""

    def setUp(self):
        jev_client.reset()
        sentiment_analysis._sentiment_cache.clear()
        env_patcher = patch.dict(os.environ, {"TYPESAFE_API_KEY": "test_key"})
        env_patcher.start()
        self.addCleanup(env_patcher.stop)


class TestScoreNormalization(SentimentJevTestCase):

    @patch("jev_client.requests.post")
    def test_bullish_score4_maps_positive(self, mock_post):
        mock_post.return_value = _jev_resp({"score": 4, "confidence": 0.8}, {"noul": 0.9})
        res = analyze_sentiment_jev("big breakthrough news", "BTC market")
        self.assertEqual(res["score"], 1.0)
        self.assertEqual(res["label"], "positive")
        self.assertEqual(res["source"], "jev")
        self.assertIn("is_material", res)

    @patch("jev_client.requests.post")
    def test_bearish_score0_maps_negative(self, mock_post):
        mock_post.return_value = _jev_resp({"score": 0, "confidence": 0.8}, {"noul": 0.7})
        res = analyze_sentiment_jev("disaster strikes", "BTC market")
        self.assertEqual(res["score"], -1.0)
        self.assertEqual(res["label"], "negative")

    @patch("jev_client.requests.post")
    def test_score_clamp_high(self, mock_post):
        mock_post.return_value = _jev_resp({"score": 9, "confidence": 0.5}, {"noul": 0.5})
        res = analyze_sentiment_jev("overflow input", "mkt")
        self.assertEqual(res["score"], 1.0)  # (9-2)/2=3.5 → clamp 1.0

    @patch("jev_client.requests.post")
    def test_score_clamp_low(self, mock_post):
        mock_post.return_value = _jev_resp({"score": -3, "confidence": 0.5}, {"noul": 0.5})
        res = analyze_sentiment_jev("underflow input", "mkt")
        self.assertEqual(res["score"], -1.0)

    @patch("jev_client.requests.post")
    def test_score_missing_defaults_neutral(self, mock_post):
        mock_post.return_value = _jev_resp()  # answers 全空 → 默认值
        res = analyze_sentiment_jev("some news", "mkt")
        self.assertEqual(res["score"], 0.0)
        self.assertEqual(res["label"], "neutral")

    @patch("jev_client.requests.post")
    def test_score_non_numeric_degrades(self, mock_post):
        mock_post.return_value = _jev_resp({"score": "high", "confidence": "sure"})
        res = analyze_sentiment_jev("weird api day", "mkt")
        self.assertEqual(res["source"], "jev_error")
        self.assertEqual(res["score"], 0)

    @patch("jev_client.requests.post")
    def test_label_boundary_0p1_is_neutral(self, mock_post):
        # score=2.2 → 归一 0.1；0.1 > 0.1 为 False → neutral（边界不越线）
        mock_post.return_value = _jev_resp({"score": 2.2, "confidence": 0.9})
        res = analyze_sentiment_jev("boundary case", "mkt")
        self.assertEqual(res["score"], 0.1)
        self.assertEqual(res["label"], "neutral")

    @patch("jev_client.requests.post")
    def test_invalid_input_short_circuits(self, mock_post):
        res = analyze_sentiment_jev("   ", "mkt")
        self.assertEqual(res["explanation"], "无效输入")
        mock_post.assert_not_called()

        res2 = analyze_sentiment_jev(None, "mkt")
        self.assertEqual(res2["score"], 0)
        self.assertEqual(mock_post.call_count, 0)


class TestFailureTags(SentimentJevTestCase):

    @patch("jev_client.requests.post")
    def test_http_error_source_tag(self, mock_post):
        mock_post.return_value = MagicMock(status_code=500, json=MagicMock(return_value={}))
        res = analyze_sentiment_jev("api broke", "mkt")
        self.assertEqual(res["source"], "jev_failed")

    def test_no_key_source_tag_fallback_engages(self):
        # 无 key → jev_error（修复点：原 source="jev" 会绕过 simple/LLM 兜底）
        with patch.dict(os.environ), \
                patch.object(jev_client, "ENV_FILE", "/nonexistent-env-file"), \
                patch.object(jev_client, "_env_file_key_cache", None):
            os.environ.pop("TYPESAFE_API_KEY", None)
            res = analyze_sentiment_jev("no key deploy", "mkt")
            self.assertEqual(res["source"], "jev_error")
            self.assertEqual(res["score"], 0)

    @patch("jev_client.requests.post")
    def test_circuit_open_source_tag(self, mock_post):
        # 触发熔断后 → circuit_open → jev_error
        mock_post.side_effect = jev_client.requests.exceptions.Timeout()
        for _ in range(3):
            analyze_sentiment_jev("outage", "mkt")
        res = analyze_sentiment_jev("outage again", "mkt2")  # 换 context 避免缓存
        self.assertEqual(res["source"], "jev_error")


class TestCache(SentimentJevTestCase):

    @patch("jev_client.requests.post")
    def test_cache_hit_single_network_call(self, mock_post):
        mock_post.return_value = _jev_resp({"score": 3, "confidence": 0.8})
        r1 = analyze_sentiment_jev("cached news", "mkt")
        r2 = analyze_sentiment_jev("cached news", "mkt")
        self.assertEqual(mock_post.call_count, 1)
        self.assertEqual(r1["score"], r2["score"])
        # 换 context → 缓存 miss → 第二次网络
        analyze_sentiment_jev("cached news", "other-mkt")
        self.assertEqual(mock_post.call_count, 2)


class TestNewsSentimentLadder(SentimentJevTestCase):

    @patch("sentiment_analysis.analyze_sentiment_with_llm")
    @patch("jev_client.requests.post")
    def test_ladder_jev_ok_skips_llm(self, mock_post, mock_llm):
        mock_post.return_value = _jev_resp({"score": 4, "confidence": 0.9})
        news = [{"title": "bullish headline", "description": "great stuff"}]
        res = analyze_news_sentiment(news, "mkt")
        self.assertGreater(res["overall_score"], 0.1)
        mock_llm.assert_not_called()

    @patch("sentiment_analysis.analyze_sentiment_with_llm")
    @patch("jev_client.requests.post")
    def test_ladder_jev_down_falls_to_llm(self, mock_post, mock_llm):
        mock_post.side_effect = jev_client.requests.exceptions.Timeout()
        mock_llm.return_value = {"score": 0.6, "label": "positive", "confidence": 0.8, "keywords": [], "explanation": "llm"}
        news = [{"title": "some headline", "description": "text"}]
        res = analyze_news_sentiment(news, "mkt")
        mock_llm.assert_called_once()
        self.assertEqual(res["overall_score"], 0.6)

    def test_empty_news_list(self):
        res = analyze_news_sentiment([], "mkt")
        self.assertEqual(res["overall_score"], 0)
        self.assertEqual(res["news_count"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
