#!/usr/bin/env python3
"""
Zero-Trust Verification Suite for PolyStrat Execution & Risk Management Optimizations
===================================================================================
涵盖:
1. CLOB 卖出订单簿深度与滑点前置校验 (validate_sell_depth)
2. 阶梯止盈与止损两阶段状��机 (confirm_exit_fill / non-destructive check)
3. 高价合约 (>0.80) 赔率非对称惩罚与累计敞口硬限制 (calculate_position_size)
4. 宏观相关性事件分组与多品种同向共振拦截 (check_correlation_exposure)
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

# 导入待测模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from clob_validator import validate_sell_depth
from take_profit_manager import TakeProfitManager, Position, ExitSignal
from risk_management import calculate_position_size
from guard_rail import check_correlation_exposure


class TestCLOBSellDepthValidation(unittest.TestCase):
    """测试 CLOB 卖盘/平仓深度与滑点校验"""

    @patch("clob_validator.get_clob_orderbook")
    def test_sufficient_depth_pass(self, mock_book):
        # 模拟深度充裕的订单簿
        mock_book.return_value = {
            "success": True,
            "best_bid": 0.85,
            "raw_bids": [
                {"price": "0.85", "size": "100"},
                {"price": "0.84", "size": "100"},
            ],
        }
        res = validate_sell_depth(token_id="tok123", sell_shares=50, max_slippage_pct=0.10)
        self.assertTrue(res["valid"], "深度充足时应校验通过")
        self.assertEqual(res["best_bid"], 0.85)
        self.assertAlmostEqual(res["weighted_bid_price"], 0.85)
        self.assertAlmostEqual(res["slippage_pct"], 0.0)

    @patch("clob_validator.get_clob_orderbook")
    def test_insufficient_depth_block(self, mock_book):
        # 模拟流动性枯竭：只有 5 份买单，却要卖 100 份
        mock_book.return_value = {
            "success": True,
            "best_bid": 0.50,
            "raw_bids": [
                {"price": "0.50", "size": "5"},
            ],
        }
        res = validate_sell_depth(token_id="tok123", sell_shares=100, max_slippage_pct=0.10)
        self.assertFalse(res["valid"], "买盘深度不足50%时必须硬拦截")
        self.assertIn("买盘深度不足", res["reason"])

    @patch("clob_validator.get_clob_orderbook")
    def test_high_slippage_block(self, mock_book):
        # 模拟第一档只有 10 份 0.90，第二档 90 份 0.50，加权滑点过大
        mock_book.return_value = {
            "success": True,
            "best_bid": 0.90,
            "raw_bids": [
                {"price": "0.90", "size": "10"},
                {"price": "0.50", "size": "90"},
            ],
        }
        res = validate_sell_depth(token_id="tok123", sell_shares=100, max_slippage_pct=0.10)
        self.assertFalse(res["valid"], "加权滑点超过10%时应硬拦截")
        self.assertIn("滑点过大", res["reason"])

    @patch("clob_validator.get_clob_orderbook")
    def test_empty_bids_liquidity_vacuum(self, mock_book):
        # 模拟订单簿无买单
        mock_book.return_value = {
            "success": True,
            "best_bid": 0.0,
            "raw_bids": [],
        }
        res = validate_sell_depth(token_id="tok123", sell_shares=10, max_slippage_pct=0.10)
        self.assertFalse(res["valid"], "无买单流动性真空时必须拦截")


class TestTakeProfitTwoStageState(unittest.TestCase):
    """测试止盈/止损两阶段状态机与数据一致性"""

    def setUp(self):
        import tempfile
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tp_manager = TakeProfitManager(data_dir=self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_check_does_not_mutate_position_before_fill(self):
        # 录入持仓
        pos = self.tp_manager.add_position(
            position_id="pos_1",
            entry_price=0.50,
            size_usdc=100.0,
            market_question="Will BTC reach 100k?",
            category="Crypto",
            token_id="tok_btc"
        )
        self.assertEqual(pos.remaining_pct, 1.0)
        self.assertEqual(pos.shares, 200.0)

        # 触发 TP1 价格 0.60 (+20%)
        signals = self.tp_manager.check_take_profits({"pos_1": 0.60})
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].stage, "TP1")

        # 核心断言：生成信号时，持仓状态不得提前归档或扣减
        self.assertIn("pos_1", self.tp_manager.positions)
        self.assertEqual(self.tp_manager.positions["pos_1"].remaining_pct, 1.0, "未收到成交回报前不得提前扣减仓位")

    def test_confirm_fill_updates_pnl_and_archives(self):
        pos = self.tp_manager.add_position(
            position_id="pos_2",
            entry_price=0.90,
            size_usdc=90.0,
            market_question="High probability event",
            category="Politics",
            token_id="tok_poly"
        )
        # 触发止损 (-20%)
        signals = self.tp_manager.check_take_profits({"pos_2": 0.70})
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].stage, "STOP_LOSS")

        # 阶段二：收到真实成交回报确认
        fill_res = self.tp_manager.confirm_exit_fill(
            position_id="pos_2",
            stage="STOP_LOSS",
            fill_shares=100.0,
            fill_price=0.70,
            fee_usd=0.50
        )
        self.assertTrue(fill_res["success"])
        # Cost = 100 * 0.90 = 90, Revenue = 100 * 0.70 = 70, Fee = 0.50 -> PnL = -20.50
        self.assertAlmostEqual(fill_res["realized_pnl"], -20.50)
        # 完全平仓后自动归档
        self.assertNotIn("pos_2", self.tp_manager.positions)
        self.assertEqual(len(self.tp_manager.exit_history), 1)


class TestHighPriceAsymmetricRisk(unittest.TestCase):
    """测试高价/高概率合约非对称风险缩减"""

    @patch("risk_management.load_trade_history")
    def test_high_price_position_scaling(self, mock_trades):
        mock_trades.return_value = []
        balance = 1000.0
        confidence = 0.20

        # 普通价格 (0.50) 仓位: 1000 * 1.0 * 0.2 = 200
        normal_pos = calculate_position_size(balance, confidence, market_category="Crypto", entry_price=0.50)
        
        # 高价合约 (0.90) 仓位: 200 * 0.4 = 80 (< 10% 敞口上限 100)
        high_price_pos = calculate_position_size(balance, confidence, market_category="Crypto", entry_price=0.90)

        self.assertLess(high_price_pos, normal_pos, "高价合约仓位应比普通合约显著缩减")
        self.assertAlmostEqual(high_price_pos, normal_pos * 0.4, places=2)

    @patch("risk_management.load_trade_history")
    def test_high_price_exposure_cap(self, mock_trades):
        # 模拟已有 95 USD 的高价未结算持仓（已接近总资金 1000 的 10% 上限）
        mock_trades.return_value = [
            {"amount": 95.0, "market_price": 0.88, "result": "pending", "category": "Crypto"}
        ]
        balance = 1000.0
        confidence = 0.90

        # 尝试再次买入高价合约 (0.85)
        pos = calculate_position_size(balance, confidence, market_category="Crypto", entry_price=0.85)
        # 剩余额度只有 100 - 95 = 5.0
        self.assertLessEqual(pos, 5.0, "高价合约总敞口不得突破资金的10%")


class TestCorrelationGuardRail(unittest.TestCase):
    """测试宏观与加密事件同向踩踏硬拦截"""

    def test_correlation_blocks_same_macro_event(self):
        existing = [
            {"title": "Will Fed cut interest rates in September 2026?", "amount": 20, "category": "Economics"}
        ]
        market = {"title": "Will Jerome Powell announce rate hike in FOMC meeting?", "category": "Economics"}
        
        res = check_correlation_exposure(market, existing)
        self.assertFalse(res["pass"], "同一宏观事件（美联储/利率）下的多个市场应被硬拦截")
        self.assertIn("interest_rate", res["event_group"])


if __name__ == "__main__":
    unittest.main()
