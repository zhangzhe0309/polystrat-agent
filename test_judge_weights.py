#!/usr/bin/env python3
"""
Judge 动态权重模块回归测试

锁定两个关键不变量（源自 v4.2 评审发现的生产故障）：
1. result 字段必须是生产格式 "win"/"lose"（settlement_tracker.py 写入），
   而非 "won"/"lost"——否则 Judge 动态权重特性静默失效。
2. 预测正确性应由 direction × result 推导，result=="win" 即方向预测正确，
   避免系统性低估 "买 No 获胜" 类别的权重。
"""
import os
import sys
import json
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _write_trades(trades):
    """将交易列表写入临时文件，返回路径（调用方负责清理）"""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(trades, f)
    f.close()
    return f.name


class TestJudgeWeightsProductionFormat(unittest.TestCase):
    """验证 Judge 权重能识别生产格式的交易记录"""

    def setUp(self):
        from judge_weights import calculate_category_accuracy, get_judge_weight
        self.calculate_category_accuracy = calculate_category_accuracy
        self.get_judge_weight = get_judge_weight

    def tearDown(self):
        # 清理本测试可能遗留的临时文件
        for attr in ("tmp_path",):
            p = getattr(self, attr, None)
            if p and os.path.exists(p):
                os.unlink(p)

    def _build_sports_trades(self, n_win, n_lose):
        """生成 Sports 类别的已结算交易（生产格式 win/lose）"""
        win_trades = [
            {"category": "Sports", "direction": "Yes", "final_prob": 0.7, "result": "win"}
            for _ in range(n_win)
        ]
        lose_trades = [
            {"category": "Sports", "direction": "Yes", "final_prob": 0.6, "result": "lose"}
            for _ in range(n_lose)
        ]
        return win_trades + lose_trades

    def test_production_win_lose_format_recognized(self):
        """生产格式 win/lose 必须被统计（非 won/lost）"""
        trades = self._build_sports_trades(n_win=8, n_lose=2)  # 10笔, acc=0.8
        self.tmp_path = _write_trades(trades)

        acc = self.calculate_category_accuracy(self.tmp_path)
        self.assertEqual(acc["overall"]["samples"], 10, "10笔已结算交易应被统计")
        self.assertAlmostEqual(acc["overall"]["accuracy"], 0.8, places=2)

    def test_high_accuracy_yields_weight_boost(self):
        """高准确率(>65%)应提升 Judge 权重至 1.2"""
        trades = self._build_sports_trades(n_win=9, n_lose=1)  # acc=0.9
        self.tmp_path = _write_trades(trades)

        weight = self.get_judge_weight("Sports", self.tmp_path)
        self.assertGreaterEqual(weight, 1.2, "准确率90%应触发权重上调")


class TestJudgeWeightsNoDirectionWin(unittest.TestCase):
    """验证 '买 No 获胜' 被正确计为预测命中（P0-2 核心修复点）"""

    def setUp(self):
        from judge_weights import calculate_category_accuracy
        self.calculate_category_accuracy = calculate_category_accuracy

    def tearDown(self):
        p = getattr(self, "tmp_path", None)
        if p and os.path.exists(p):
            os.unlink(p)

    def test_no_direction_win_counted_as_correct(self):
        """direction=No 且 result=win 的交易必须计为 correct"""
        # 10笔 No 方向获胜：final_prob<0.5 但方向预测正确
        trades = [
            {
                "category": "Crypto",
                "direction": "No",
                "final_prob": 0.4,  # < 0.5，但方向 No 实际命中
                "result": "win",
            }
            for _ in range(10)
        ]
        self.tmp_path = _write_trades(trades)

        acc = self.calculate_category_accuracy(self.tmp_path)
        crypto = acc["categories"]["Crypto"]
        self.assertEqual(crypto["samples"], 10)
        self.assertAlmostEqual(crypto["accuracy"], 1.0, places=2,
                               msg="No方向获胜应计为预测正确，准确率应为100%")

    def test_yes_direction_win_counted_as_correct(self):
        """direction=Yes 且 result=win 的交易计为 correct（回归保护）"""
        trades = [
            {"category": "Sports", "direction": "Yes", "final_prob": 0.7, "result": "win"}
            for _ in range(10)
        ]
        self.tmp_path = _write_trades(trades)

        acc = self.calculate_category_accuracy(self.tmp_path)
        self.assertAlmostEqual(acc["categories"]["Sports"]["accuracy"], 1.0, places=2)

    def test_lose_counted_as_incorrect(self):
        """result=lose 必须计为预测错误"""
        trades = [
            {"category": "Politics", "direction": "Yes", "final_prob": 0.8, "result": "lose"}
            for _ in range(10)
        ]
        self.tmp_path = _write_trades(trades)

        acc = self.calculate_category_accuracy(self.tmp_path)
        self.assertAlmostEqual(acc["categories"]["Politics"]["accuracy"], 0.0, places=2)


class TestJudgeWeightsEdgeCases(unittest.TestCase):
    """边界场景"""

    def setUp(self):
        from judge_weights import get_judge_weight, calculate_category_accuracy
        self.get_judge_weight = get_judge_weight
        self.calculate_category_accuracy = calculate_category_accuracy

    def tearDown(self):
        p = getattr(self, "tmp_path", None)
        if p and os.path.exists(p):
            os.unlink(p)

    def test_insufficient_samples_returns_default(self):
        """样本数 < min_samples(10) 返回默认权重 1.0"""
        trades = [
            {"category": "Sports", "direction": "Yes", "final_prob": 0.7, "result": "win"}
            for _ in range(5)  # 仅5笔
        ]
        self.tmp_path = _write_trades(trades)

        weight = self.get_judge_weight("Sports", self.tmp_path)
        self.assertEqual(weight, 1.0, "样本不足应返回中性权重 1.0")

    def test_pending_trades_skipped(self):
        """pending 交易不计入统计"""
        trades = [
            {"category": "Sports", "direction": "Yes", "final_prob": 0.7, "result": "pending"}
            for _ in range(20)
        ]
        self.tmp_path = _write_trades(trades)

        acc = self.calculate_category_accuracy(self.tmp_path)
        self.assertEqual(acc["overall"]["samples"], 0, "pending 交易应被跳过")

    def test_missing_file_returns_default(self):
        """日志文件不存在时返回默认值，不抛异常"""
        weight = self.get_judge_weight("Sports", "/nonexistent/path.json")
        self.assertEqual(weight, 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
