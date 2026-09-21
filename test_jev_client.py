#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
jev_client 单元测试：传输层、五种失败 reason、内存熔断、统计
全部 mock requests.post，零网络依赖。
"""

import os
import sys
import time
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import jev_client
from jev_client import jev_ask, get_stats, reset, JevUnavailableError


def _mock_resp(status=200, json_data=None, json_exc=None):
    """构造 mock HTTP 响应。"""
    m = MagicMock()
    m.status_code = status
    if json_exc is not None:
        m.json.side_effect = json_exc
    else:
        m.json.return_value = json_data if json_data is not None else {}
    return m


class JevClientTestCase(unittest.TestCase):
    """公共基类：隔离熔断状态与 key 来源。"""

    def setUp(self):
        reset()
        env_patcher = patch.dict(os.environ, {"TYPESAFE_API_KEY": "test_key"})
        env_patcher.start()
        self.addCleanup(env_patcher.stop)


class TestJevAskSuccess(JevClientTestCase):

    @patch("jev_client.requests.post")
    def test_success_returns_answers(self, mock_post):
        mock_post.return_value = _mock_resp(200, {"answers": {"sentiment": {"score": 3}}})
        result = jev_ask("s", {})
        self.assertEqual(result, {"sentiment": {"score": 3}})
        stats = get_stats()
        self.assertEqual(stats["successes"], 1)
        self.assertFalse(stats["circuit_open"])

    @patch("jev_client.requests.post")
    def test_missing_answers_returns_empty_dict(self, mock_post):
        mock_post.return_value = _mock_resp(200, {})
        result = jev_ask("s", {})
        self.assertEqual(result, {})
        # 传输层健康，计 success 不计失败
        stats = get_stats()
        self.assertEqual(stats["successes"], 1)
        self.assertEqual(stats["failures"], 0)

    @patch("jev_client.requests.post")
    def test_answers_not_dict_returns_empty(self, mock_post):
        mock_post.return_value = _mock_resp(200, {"answers": "garbage"})
        self.assertEqual(jev_ask("s", {}), {})

    @patch("jev_client.requests.post")
    def test_success_resets_consecutive_failures(self, mock_post):
        # 先注入 2 次失败
        mock_post.side_effect = jev_client.requests.exceptions.Timeout()
        for _ in range(2):
            with self.assertRaises(JevUnavailableError):
                jev_ask("s", {})
        # 再成功
        mock_post.side_effect = None
        mock_post.return_value = _mock_resp(200, {"answers": {}})
        jev_ask("s", {})
        self.assertEqual(get_stats()["consecutive_failures"], 0)


class TestJevAskFailure(JevClientTestCase):

    def test_no_key_raises_no_key(self):
        # 同时清 env 与文件回退，模拟无 key 部署
        with patch.dict(os.environ), \
                patch.object(jev_client, "ENV_FILE", "/nonexistent-env-file"), \
                patch.object(jev_client, "_env_file_key_cache", None):
            os.environ.pop("TYPESAFE_API_KEY", None)
            with patch("jev_client.requests.post") as mock_post:
                with self.assertRaises(JevUnavailableError) as ctx:
                    jev_ask("s", {})
                self.assertEqual(ctx.exception.reason, "no_key")
                mock_post.assert_not_called()
        # no_key 不计失败、不触发熔断
        stats = get_stats()
        self.assertEqual(stats["failures"], 0)
        self.assertEqual(stats["calls"], 0)

    @patch("jev_client.requests.post")
    def test_http_500_raises_http_error(self, mock_post):
        mock_post.return_value = _mock_resp(500)
        with self.assertRaises(JevUnavailableError) as ctx:
            jev_ask("s", {})
        self.assertEqual(ctx.exception.reason, "http_error")
        self.assertIn("500", ctx.exception.detail)
        self.assertEqual(get_stats()["failures_by_reason"].get("http_error"), 1)

    @patch("jev_client.requests.post")
    def test_timeout_raises_network(self, mock_post):
        mock_post.side_effect = jev_client.requests.exceptions.Timeout()
        with self.assertRaises(JevUnavailableError) as ctx:
            jev_ask("s", {})
        self.assertEqual(ctx.exception.reason, "network")

    @patch("jev_client.requests.post")
    def test_bad_json_raises_bad_response(self, mock_post):
        mock_post.return_value = _mock_resp(200, json_exc=ValueError("not json"))
        with self.assertRaises(JevUnavailableError) as ctx:
            jev_ask("s", {})
        self.assertEqual(ctx.exception.reason, "bad_response")


class TestCircuitBreaker(JevClientTestCase):

    @patch("jev_client.requests.post")
    def test_opens_after_three_consecutive_failures(self, mock_post):
        mock_post.side_effect = jev_client.requests.exceptions.Timeout()
        for _ in range(3):
            with self.assertRaises(JevUnavailableError):
                jev_ask("s", {})
        # 第 4 次：熔断直接拒绝，零网络
        with self.assertRaises(JevUnavailableError) as ctx:
            jev_ask("s", {})
        self.assertEqual(ctx.exception.reason, "circuit_open")
        self.assertEqual(mock_post.call_count, 3)

    @patch("jev_client.requests.post")
    def test_cooldown_expiry_allows_probe(self, mock_post):
        mock_post.side_effect = jev_client.requests.exceptions.Timeout()
        for _ in range(3):
            with self.assertRaises(JevUnavailableError):
                jev_ask("s", {})
        # 手动让冷却期过期（half-open 试探）
        with jev_client._LOCK:
            jev_client._state["open_until"] = time.monotonic() - 1
        mock_post.side_effect = None
        mock_post.return_value = _mock_resp(200, {"answers": {}})
        result = jev_ask("s", {})
        self.assertEqual(result, {})
        self.assertEqual(mock_post.call_count, 4)  # 3 失败 + 1 试探均真实发网

    @patch("jev_client.requests.post")
    def test_half_open_failure_reopens(self, mock_post):
        mock_post.side_effect = jev_client.requests.exceptions.Timeout()
        for _ in range(3):
            with self.assertRaises(JevUnavailableError):
                jev_ask("s", {})
        with jev_client._LOCK:
            jev_client._state["open_until"] = time.monotonic() - 1
        # 试探仍失败 → 重新开放
        with self.assertRaises(JevUnavailableError):
            jev_ask("s", {})
        self.assertTrue(get_stats()["circuit_open"])
        with jev_client._LOCK:
            self.assertGreater(jev_client._state["open_until"], time.monotonic())

    @patch("jev_client.requests.post")
    def test_circuit_open_during_cooldown_zero_cost(self, mock_post):
        mock_post.side_effect = jev_client.requests.exceptions.Timeout()
        for _ in range(3):
            with self.assertRaises(JevUnavailableError):
                jev_ask("s", {})
        mock_post.side_effect = None
        t0 = time.monotonic()
        with self.assertRaises(JevUnavailableError):
            jev_ask("s", {})
        self.assertLess(time.monotonic() - t0, 0.05)  # 无网络开销
        self.assertEqual(mock_post.call_count, 3)

    def test_reset_clears_state(self):
        with patch("jev_client.requests.post") as mock_post:
            mock_post.side_effect = jev_client.requests.exceptions.Timeout()
            for _ in range(3):
                with self.assertRaises(JevUnavailableError):
                    jev_ask("s", {})
        reset()
        stats = get_stats()
        self.assertEqual(stats["calls"], 0)
        self.assertEqual(stats["failures"], 0)
        self.assertFalse(stats["circuit_open"])
        self.assertEqual(stats["failures_by_reason"], {})


class TestGetStats(JevClientTestCase):

    @patch("jev_client.requests.post")
    def test_stats_shape(self, mock_post):
        mock_post.return_value = _mock_resp(200, {"answers": {}})
        jev_ask("s", {})
        stats = get_stats()
        for key in ("calls", "successes", "failures", "failures_by_reason",
                    "consecutive_failures", "circuit_open", "cooldown_remaining", "last_error"):
            self.assertIn(key, stats)
        self.assertEqual(stats["calls"], stats["successes"] + stats["failures"])

    @patch("jev_client.requests.post")
    def test_failures_by_reason_aggregation(self, mock_post):
        responses = [_mock_resp(500), _mock_resp(500), jev_client.requests.exceptions.Timeout()]
        mock_post.side_effect = responses
        for _ in range(3):
            with self.assertRaises(JevUnavailableError):
                jev_ask("s", {})
        stats = get_stats()
        self.assertEqual(stats["failures_by_reason"].get("http_error"), 2)
        self.assertEqual(stats["failures_by_reason"].get("network"), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
