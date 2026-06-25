#!/usr/bin/env python3
"""
PolyStrat 单元测试框架
覆盖核心模块的关键函数
"""
import os
import sys
import json
import unittest
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

# 添加脚本目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

class TestRiskManagement(unittest.TestCase):
    """风险管理模块测试"""
    
    def setUp(self):
        from risk_management import calculate_risk_score, should_trade, calculate_position_size
        self.calculate_risk_score = calculate_risk_score
        self.should_trade = should_trade
        self.calculate_position_size = calculate_position_size
    
    def test_risk_score_low_risk(self):
        """低风险市场测试"""
        market = {
            "liquidity": 100000,
            "yes_price": 0.5,
            "end_date": (datetime.now(timezone.utc) + timedelta(days=60)).isoformat()
        }
        score = self.calculate_risk_score(market, 0.8, 0.1)
        self.assertLess(score, 0.5, "低风险市场分数应 < 0.5")
    
    def test_risk_score_high_risk(self):
        """高风险市场测试"""
        market = {
            "liquidity": 5000,
            "yes_price": 0.95,
            "end_date": (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        }
        score = self.calculate_risk_score(market, 0.3, 0.8)
        self.assertGreater(score, 0.5, "高风险市场分数应 > 0.5")
    
    def test_should_trade_reject_low_confidence(self):
        """低置信度应拒绝交易"""
        market = {"liquidity": 50000, "yes_price": 0.5, "end_date": "2027-01-01T00:00:00Z"}
        should, reason = self.should_trade(market, 0.2, 0.1, 1000)
        self.assertFalse(should, "低置信度应拒绝")
        self.assertIn("置信度过低", reason)
    
    def test_position_size_capped(self):
        """仓位应有上限"""
        size = self.calculate_position_size(10000, 1.0, "Crypto")
        self.assertLessEqual(size, 10000 * 0.05, "仓位不应超过5%")


class TestAdaptiveWeights(unittest.TestCase):
    """自适应权重模块测试"""
    
    def setUp(self):
        from adaptive_weights import calculate_overall_win_rate, calculate_signal_accuracy
        self.calculate_overall_win_rate = calculate_overall_win_rate
        self.calculate_signal_accuracy = calculate_signal_accuracy
    
    def test_win_rate_with_settled_trades(self):
        """已结算交易胜率计算"""
        trades = [
            {"direction": "Yes", "edge": 0.05, "result": "win"},
            {"direction": "Yes", "edge": 0.03, "result": "lose"},
            {"direction": "No", "edge": -0.04, "result": "win"},
        ]
        rate = self.calculate_overall_win_rate(trades)
        self.assertAlmostEqual(rate, 2/3, places=2)
    
    def test_win_rate_with_pending_trades(self):
        """未结算交易胜率计算"""
        trades = [
            {"direction": "Yes", "edge": 0.05, "result": "pending"},
            {"direction": "Yes", "edge": -0.03, "result": "pending"},
        ]
        rate = self.calculate_overall_win_rate(trades)
        self.assertAlmostEqual(rate, 0.5, places=2)
    
    def test_win_rate_empty(self):
        """空交易列表"""
        rate = self.calculate_overall_win_rate([])
        self.assertEqual(rate, 0.5)
    
    def test_signal_accuracy_llm(self):
        """LLM信号准确率计算"""
        trades = [
            {"llm_prob": 0.7, "market_price": 0.6, "direction": "Yes", "edge": 0.05, "result": "win"},
            {"llm_prob": 0.4, "market_price": 0.5, "direction": "No", "edge": -0.04, "result": "win"},
        ]
        accuracy = self.calculate_signal_accuracy(trades, "llm")
        self.assertGreater(accuracy, 0, "准确率应 > 0")


class TestMLOptimizer(unittest.TestCase):
    """ML优化模块测试"""
    
    def setUp(self):
        from ml_optimizer import extract_features
        self.extract_features = extract_features
    
    def test_extract_features_filters_unsettled(self):
        """应过滤未结算交易"""
        trades = [
            {"llm_prob": 0.7, "sentiment_score": 0.3, "edge": 0.1, "market_price": 0.6,
             "direction": "Yes", "amount": 2, "final_prob": 0.7, "result": "win"},
            {"llm_prob": 0.8, "sentiment_score": 0.5, "edge": 0.15, "market_price": 0.65,
             "direction": "Yes", "amount": 2, "final_prob": 0.8, "result": "pending"},
            {"llm_prob": 0.6, "sentiment_score": 0.1, "edge": 0.05, "market_price": 0.55,
             "direction": "Yes", "amount": 2, "final_prob": 0.6},  # 无result
        ]
        features, labels = self.extract_features(trades)
        self.assertEqual(len(features), 1, "应只保留已结算交易")
        self.assertEqual(labels[0], 1, "win标签应为1")
    
    def test_feature_count(self):
        """特征数量应为8"""
        trades = [
            {"llm_prob": 0.7, "sentiment_score": 0.3, "edge": 0.1, "market_price": 0.6,
             "direction": "Yes", "amount": 2, "final_prob": 0.7, "result": "win"},
        ]
        features, labels = self.extract_features(trades)
        self.assertEqual(len(features[0]), 8, "特征数应为8")


class TestSmartKeywords(unittest.TestCase):
    """智能关键词模块测试"""
    
    def setUp(self):
        from smart_keywords import get_search_queries
        self.get_search_queries = get_search_queries
    
    def test_crypto_keywords(self):
        """加密市场关键词提取"""
        queries = self.get_search_queries("Will Bitcoin hit $100k?", "Crypto")
        # 关键词可能全大写，使用不区分大小写检查
        self.assertTrue(any("bitcoin" in q.lower() or "btc" in q.lower() for q in queries))
    
    def test_politics_keywords(self):
        """政治市场关键词提取"""
        queries = self.get_search_queries("Trump win election 2028?", "Politics")
        self.assertTrue(any("Trump" in q for q in queries))
    
    def test_empty_title(self):
        """空标题处理"""
        queries = self.get_search_queries("", "Other")
        self.assertGreater(len(queries), 0, "应返回默认关键词")


class TestDynamicOptimizer(unittest.TestCase):
    """动态优化模块测试"""
    
    def setUp(self):
        from dynamic_optimizer import get_dynamic_dedup_hours, calculate_position_with_liquidity
        self.get_dynamic_dedup_hours = get_dynamic_dedup_hours
        self.calculate_position_with_liquidity = calculate_position_with_liquidity
    
    def test_dedup_hours_near_settlement(self):
        """临近结算应缩短去重窗口"""
        end_date = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()
        hours = self.get_dynamic_dedup_hours(end_date)
        self.assertLessEqual(hours, 12)
    
    def test_dedup_hours_far_settlement(self):
        """远期市场应增加去重窗口"""
        end_date = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        hours = self.get_dynamic_dedup_hours(end_date)
        self.assertEqual(hours, 48)
    
    def test_position_high_liquidity(self):
        """高流动性应允许更大仓位"""
        pos_high = self.calculate_position_with_liquidity(1000, 0.8, 100000, 2.0)
        pos_low = self.calculate_position_with_liquidity(1000, 0.8, 5000, 2.0)
        self.assertGreater(pos_high, pos_low)
    
    def test_position_capped_at_2x(self):
        """仓位不超过基础仓位2倍"""
        pos = self.calculate_position_with_liquidity(100000, 1.0, 200000, 2.0)
        self.assertLessEqual(pos, 4.0)


class TestSentimentAnalysis(unittest.TestCase):
    """情感分析模块测试"""
    
    def setUp(self):
        from sentiment_analysis import analyze_sentiment_simple
        self.analyze_sentiment_simple = analyze_sentiment_simple
    
    def test_positive_sentiment(self):
        """正面情感识别"""
        result = self.analyze_sentiment_simple("Bitcoin surges to new highs, bullish sentiment")
        self.assertGreater(result["score"], 0)
    
    def test_negative_sentiment(self):
        """负面情感识别"""
        result = self.analyze_sentiment_simple("Market crash expected, bearish sentiment widespread")
        self.assertLess(result["score"], 0)
    
    def test_neutral_sentiment(self):
        """中性情感识别"""
        result = self.analyze_sentiment_simple("The weather is cloudy today")
        self.assertEqual(result["score"], 0)


class TestFileLock(unittest.TestCase):
    """文件锁测试"""
    
    def test_concurrent_write_safety(self):
        """并发写入安全性"""
        import fcntl
        from concurrent.futures import ThreadPoolExecutor
        
        test_file = Path("/tmp/test_polystrat_lock.json")
        
        def save_with_lock(data):
            lock_path = str(test_file) + ".lock"
            with open(lock_path, "w") as lock_file:
                fcntl.flock(lock_file, fcntl.LOCK_EX)
                try:
                    trades = []
                    if test_file.exists():
                        try:
                            trades = json.loads(test_file.read_text())
                        except:
                            pass
                    trades.append(data)
                    test_file.write_text(json.dumps(trades))
                finally:
                    fcntl.flock(lock_file, fcntl.LOCK_UN)
        
        # 清理
        if test_file.exists():
            test_file.unlink()
        
        # 并发写入
        with ThreadPoolExecutor(max_workers=10) as executor:
            list(executor.map(lambda i: save_with_lock({"id": i}), range(50)))
        
        # 验证
        trades = json.loads(test_file.read_text())
        self.assertEqual(len(trades), 50, "应有50条记录")
        
        # 清理
        test_file.unlink()
        os.unlink(str(test_file) + ".lock")


def run_tests():
    """运行所有测试"""
    print("=" * 60)
    print("PolyStrat 单元测试")
    print("=" * 60)
    
    # 创建测试套件
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # 添加测试类
    suite.addTests(loader.loadTestsFromTestCase(TestRiskManagement))
    suite.addTests(loader.loadTestsFromTestCase(TestAdaptiveWeights))
    suite.addTests(loader.loadTestsFromTestCase(TestMLOptimizer))
    suite.addTests(loader.loadTestsFromTestCase(TestSmartKeywords))
    suite.addTests(loader.loadTestsFromTestCase(TestDynamicOptimizer))
    suite.addTests(loader.loadTestsFromTestCase(TestSentimentAnalysis))
    suite.addTests(loader.loadTestsFromTestCase(TestFileLock))
    
    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # 统计
    print("\n" + "=" * 60)
    print(f"测试结果: {result.testsRun} 个测试")
    print(f"成功: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"失败: {len(result.failures)}")
    print(f"错误: {len(result.errors)}")
    print("=" * 60)
    
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
