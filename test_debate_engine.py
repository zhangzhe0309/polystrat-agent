#!/usr/bin/env python3
"""
Debate Engine 自动化单元测试套件
全面集成至 unittest 框架，支持 CI 与自动化测试门禁。
"""

import sys
import os
import unittest
from unittest.mock import patch

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from debate_engine import DebateEngine


class TestDebateEngineUnit(unittest.TestCase):
    """DebateEngine 单元测试"""

    def setUp(self):
        self.engine = DebateEngine()

    def test_basic_initialization(self):
        """测试 1: 模块导入与基本属性初始化"""
        self.assertIsNotNone(self.engine)
        self.assertTrue(hasattr(self.engine, "run_debate"))

    def test_missing_api_keys_graceful_fallback(self):
        """测试 2: API key 缺失时的优雅降级（返回默认 0.5 概率）"""
        orig_key = os.environ.pop("GROQ_API_KEY", None)
        try:
            with patch("debate_engine._call_with_fallback", return_value=(None, "groq", "no key")):
                result = self.engine.run_debate(
                    market_title="Test market without API key",
                    category="Other",
                    current_price=0.5,
                    news_context="No news",
                )
                self.assertIsInstance(result, dict)
                self.assertIn("verdict_probability", result)
                # 缺失 API Key 时应安全降级返回 0.5 默认值
                self.assertEqual(result["verdict_probability"], 0.5)
                self.assertIn("verdict_confidence", result)
        finally:
            if orig_key:
                os.environ["GROQ_API_KEY"] = orig_key

    def test_mocked_full_debate_flow(self):
        """测试 3: 模拟多 Agent（Bull/Bear/Judge）完整三轮辩论与强类型输出解析"""
        def mock_call(messages, role, temperature=0.3):
            if role == "bull":
                return ("【概率估计】\nPROB:75\n【信心水平】\nHIGH\n【核心论点】\n1. ETF 流入强劲", "groq", None)
            elif role == "bear":
                return ("【概率估计】\nPROB:40\n【信心水平】\nMEDIUM\n【核心论点】\n1. 宏观加息预期", "groq", None)
            elif role == "judge":
                return ("【裁决分析】\nBull 方论据更充分。\n【最终概率】\nVERDICT:70\n【信心水平】\nHIGH\n【关键因素】\nETF 流入, 宏观政策", "groq", None)
            return (None, "groq", "unknown role")

        with patch("debate_engine._call_with_fallback", side_effect=mock_call):
            result = self.engine.run_debate(
                market_title="Will Bitcoin break 100k?",
                category="Crypto",
                current_price=0.60,
                news_context="Strong institutional demand reported",
            )
            self.assertIsInstance(result, dict)
            self.assertAlmostEqual(result.get("verdict_probability", 0.5), 0.70)
            self.assertEqual(result.get("verdict_confidence"), "HIGH")
            self.assertIn("ETF 流入", result.get("key_factors", []))

    def test_debate_malformed_json_fallback(self):
        """测试 4: 大模型返回畸形文本时的安全容错与兜底"""
        with patch("debate_engine._call_with_fallback", return_value=("完全不符合格式的胡言乱语", "groq", None)):
            result = self.engine.run_debate(
                market_title="Malformed text market",
                category="Politics",
                current_price=0.40,
                news_context="Irrelevant",
            )
            self.assertIsInstance(result, dict)
            self.assertIn("verdict_probability", result)
            self.assertTrue(0.0 <= result["verdict_probability"] <= 1.0)


if __name__ == "__main__":
    unittest.main()
