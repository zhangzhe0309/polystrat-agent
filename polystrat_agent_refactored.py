#!/usr/bin/env python3
"""
简易版 PolyStrat — AI 自主交易 Agent v2（重构版）
功能：
1. 扫描 Polymarket 活跃市场
2. 搜索相关新闻（GNews + Currents + RSS）
3. 情感分析（LLM + 关键词）
4. LLM 分析概率（4模型投票）
5. 风险管理（仓位/止损/分散）
6. 自动下单（DRY_RUN 模式）
7. 输出结果（Hermes Cron 推送）
"""

import os
import sys
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

from error_handler import safe_execute, handle_error
from constants import DEFAULT_BALANCE

load_dotenv(Path.home() / ".hermes" / "profiles" / "life" / ".env")
load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from news_search import search_news_for_market
from sentiment_analysis import analyze_news_sentiment
from risk_management import should_trade, calculate_position_size, get_risk_report, set_trade_log_path as set_risk_log_path
from onchain_monitor import get_onchain_signal
from adaptive_weights import calculate_adaptive_weights, load_trade_history, set_trade_log_path as set_adaptive_log_path
from ml_optimizer import get_ml_signal
from multi_platform import get_multiplatform_signal
from smart_keywords import get_search_queries
from advanced_voting import create_voting_system
from dynamic_optimizer import (
    calculate_llm_model_weights,
    get_dynamic_price_thresholds,
    get_dynamic_dedup_hours,
    format_optimization_report,
)
from polystrat_logger import log, log_error, log_api_call, log_performance
from safe_file_ops import atomic_write_json, atomic_read_json, append_to_json_array
from circuit_breaker import check_breaker, record_trade_result, get_breaker_status
from trade_limits import (
    check_trade_allowed,
    record_trade,
    get_limits_status,
    LIMITS_CONFIG,
)
from settlement_tracker import (
    update_settled_trades,
    format_settlement_report as fmt_settlement_report,
)
from settlement_tracker import set_trade_log_path as set_settlement_log_path
from market_microstructure import calculate_microstructure_signal, format_microstructure_report
from arbitrage_engine import scan_all_arbitrage, format_arbitrage_report
from config_center import TRADE_LOG


class PolyStratAgent:
    """PolyStrat 交易 Agent（重构版）"""

    # === 配置 ===
    # LLM Ensemble 链：双主力(reasoning) + 双辅助(快速验证)
    # Primary: MiniMax M2.7 + Nemotron 3 Super (reasoning模型，输出完整推理链)
    # Secondary: Llama 3.3 70B + GLM-5.1 (快速方向验证)
    LLM_PROVIDERS = [
        {
            "name": "MiniMax M2.7",
            "api_key": os.environ.get("NVIDIA_API_KEY_2", ""),
            "base_url": "https://integrate.api.nvidia.com/v1",
            "model": "minimaxai/minimax-m2.7",
            "temperature": 0.5,
            "priority": 1,
            "role": "primary",
        },
        {
            "name": "Nemotron 3 Super",
            "api_key": os.environ.get("NVIDIA_API_KEY", ""),
            "base_url": "https://integrate.api.nvidia.com/v1",
            "model": "nvidia/nemotron-3-super-120b-a12b",
            "temperature": 0.5,
            "priority": 2,
            "role": "primary",
        },
        {
            "name": "Llama 3.3 70B",
            "api_key": os.environ.get("NVIDIA_API_KEY", ""),
            "base_url": "https://integrate.api.nvidia.com/v1",
            "model": "meta/llama-3.3-70b-instruct",
            "temperature": 0.3,
            "priority": 3,
            "role": "secondary",
        },
        {
            "name": "GLM-5.1",
            "api_key": os.environ.get("GLM_API_KEY", ""),
            "base_url": "https://open.bigmodel.cn/api/paas/v4",
            "model": "glm-5.1",
            "temperature": 0.4,
            "priority": 4,
            "role": "secondary",
        },
    ]

    # 信号权重（用于显示，实际使用自适应权重）
    SIGNAL_WEIGHTS = {
        "llm": 0.40,
        "sentiment": 0.20,
        "onchain": 0.20,
        "ml": 0.20,
    }

    # 边际优势阈值（用于显示，实际使用自适应阈值）
    EDGE_THRESHOLD = 0.04

    # 微观结构配置
    MICROSTRUCTURE_CONFIG = {
        "weight": 0.05,
        "enabled": False,
    }

    # 甜蜜点配置
    SWEET_SPOT_MODE = True
    SWEET_SPOT_CONFIG = {
        "min_price": 0.05,
        "max_price": 0.50,
        "min_liquidity": 5000,
        "min_disagreement": 1,
        "max_disagreement": 15,
        "min_confidence": 0.55,
        "preferred_categories": ["Politics", "Economics", "Crypto"],
    }

    # DRY_RUN 模式
    DRY_RUN = True

    # 最小流动性
    MIN_LIQUIDITY = 1000

    # 每轮最大交易数
    MAX_TRADES_PER_RUN = 3

    def __init__(self):
        """初始化 Agent"""
        self.balance = float(os.environ.get("POLYSTRAT_BALANCE", str(DEFAULT_BALANCE)))
        self.trade_history = []
        self.traded_markets = set()
        self.stop_loss_triggered = False
        self.stop_loss_result = None
        self.trades_made = 0
        self.decisions = []
        self.start_time = None

    def sync_settlements(self):
        """结算同步（先更新交易结果，让 ML 学习有目标变量）"""
        try:
            set_settlement_log_path(TRADE_LOG)
            settle_stats = update_settled_trades()
            if settle_stats.get("updated", 0) > 0 or settle_stats.get("timeout", 0) > 0:
                log.info(
                    f"结算同步: {settle_stats['wins']}胜/{settle_stats['losses']}负, PnL {settle_stats.get('total_pnl', 0):+.2f}"
                )
        except Exception as e:
            log_error("settlement", e, "结算同步失败（非致命）")

    def scan_arbitrage(self):
        """套利扫描（Dutch Book + negRisk）"""
        try:
            arb_result = scan_all_arbitrage()
            if arb_result["total"] > 0:
                print(format_arbitrage_report(arb_result))
                # 套利机会直接输出，不参与后续信号分析
        except Exception as e:
            log_error("arbitrage", e, "套利扫描失败（非致命）")

    def fetch_markets(self, limit=50):
        """获取活跃市场（按流动性排序取前50，覆盖更多机会）"""
        markets = fetch_active_markets(limit=limit)
        if not markets:
            return None
        return markets

    def load_trade_history_and_calculate_weights(self):
        """加载交易历史并计算自适应权重"""
        self.trade_history = load_trade_history()
        adaptive_weights = calculate_adaptive_weights(self.trade_history)
        return adaptive_weights

    def check_stop_loss(self):
        """检查止损"""
        from risk_management import check_stop_loss as _check_stop_loss

        self.stop_loss_result = _check_stop_loss(self.balance, self.trade_history)
        if self.stop_loss_result["triggered"]:
            log.warning(f"止损触发: {self.stop_loss_result['reason']}")
            print(f"🛑 止损触发: {self.stop_loss_result['reason']}")
            print(f"   累计回撤: {self.stop_loss_result['drawdown_pct']:.2%}")
            # 仍继续分析市场，但不下单
            self.stop_loss_triggered = True
        else:
            self.stop_loss_triggered = False

    def calculate_dynamic_optimization(self):
        """计算动态优化参数"""
        llm_model_weights = calculate_llm_model_weights(self.trade_history)
        dynamic_thresholds = get_dynamic_price_thresholds(self.trade_history)
        return llm_model_weights, dynamic_thresholds

    def build_traded_markets_set(self):
        """构建已交易市场集合（动态去重窗口）"""
        self.traded_markets = set()
        now = datetime.now(timezone.utc)
        for t in self.trade_history:
            try:
                trade_time = datetime.fromisoformat(
                    t.get("timestamp", "").replace("Z", "+00:00")
                )
                hours_ago = (now - trade_time).total_seconds() / 3600
                # 使用动态去重窗口
                dedup_hours = get_dynamic_dedup_hours(t.get("end_date", ""))
                if hours_ago < dedup_hours:
                    # 使用 condition_id 作为去重键（比 title 更可靠）
                    cid = t.get("condition_id", "")
                    if cid:
                        self.traded_markets.add(cid)
                    else:
                        # 兼容旧记录：无 condition_id 时用 title 小写去重
                        self.traded_markets.add(t.get("market", "").lower())
            except Exception as e:
                print(f"⚠️ 交易历史加载失败: {e}")

    def calculate_adaptive_weights_and_thresholds(self, adaptive_weights):
        """计算自适应权重和阈值"""
        llm_weight = adaptive_weights.get("llm_weight", self.SIGNAL_WEIGHTS["llm"])
        sentiment_weight = adaptive_weights.get(
            "sentiment_weight", self.SIGNAL_WEIGHTS["sentiment"]
        )
        onchain_weight = adaptive_weights.get("onchain_weight", self.SIGNAL_WEIGHTS["onchain"])
        ml_weight = adaptive_weights.get("ml_weight", self.SIGNAL_WEIGHTS["ml"])
        edge_threshold = adaptive_weights.get("edge_threshold", self.EDGE_THRESHOLD)

        # 归一化确保4信号权重总和=1.0（不含微观结构和套利）
        adaptive_weight_sum = llm_weight + sentiment_weight + onchain_weight + ml_weight
        if abs(adaptive_weight_sum - 1.0) > 0.01:
            llm_weight /= adaptive_weight_sum
            sentiment_weight /= adaptive_weight_sum
            onchain_weight /= adaptive_weight_sum
            ml_weight /= adaptive_weight_sum

        # 多平台/套利信号权重（从各信号等比抽取，保持总和1.0）
        ARBITRAGE_WEIGHT = 0.05
        MICROSTRUCTURE_WEIGHT = self.MICROSTRUCTURE_CONFIG["weight"] if self.MICROSTRUCTURE_CONFIG["enabled"] else 0

        # 调整权重，确保总和=1.0（含微观结构和套利）
        total_extra_weight = ARBITRAGE_WEIGHT + MICROSTRUCTURE_WEIGHT
        if total_extra_weight > 0:
            llm_weight *= 1 - total_extra_weight
            sentiment_weight *= 1 - total_extra_weight
            onchain_weight *= 1 - total_extra_weight
            ml_weight *= 1 - total_extra_weight

        return {
            "llm_weight": llm_weight,
            "sentiment_weight": sentiment_weight,
            "onchain_weight": onchain_weight,
            "ml_weight": ml_weight,
            "edge_threshold": edge_threshold,
            "ARBITRAGE_WEIGHT": ARBITRAGE_WEIGHT,
            "MICROSTRUCTURE_WEIGHT": MICROSTRUCTURE_WEIGHT,
            "adaptive_weights": adaptive_weights,
        }

    def print_weight_configuration(self, weights_info):
        """输出权重配置（包含动态优化信息）"""
        print(f"⚖️ 自适应权重配置:")
        print(
            f"   LLM: {weights_info['llm_weight']:.3f} | 情感: {weights_info['sentiment_weight']:.3f} | 链上: {weights_info['onchain_weight']:.3f} | ML: {weights_info['ml_weight']:.3f}"
        )
        print(f"   优势阈值: {weights_info['edge_threshold']:.2%} | 套利信号: {weights_info['ARBITRAGE_WEIGHT']:.0%} | 微观结构: {weights_info['MICROSTRUCTURE_WEIGHT']:.0%}")
        print(
            f"   情感斜率: {weights_info['adaptive_weights'].get('sentiment_mapping_slope', 0.40):.2f} | 链上乘数: {weights_info['adaptive_weights'].get('onchain_multiplier', 1.0):.2f}"
        )
        print(f"   样本大小: {weights_info['adaptive_weights'].get('sample_size', 0)}")
        print()

    def print_sweet_spot_configuration(self):
        """输出甜蜜点配置"""
        if self.SWEET_SPOT_MODE:
            print(f"🎯 甜蜜点模式: 已启用")
            print(f"   价格区间: {self.SWEET_SPOT_CONFIG['min_price']:.0%} - {self.SWEET_SPOT_CONFIG['max_price']:.0%}")
            print(f"   最低流动性: ${self.SWEET_SPOT_CONFIG['min_liquidity']:,}")
            print(f"   分歧区间: {self.SWEET_SPOT_CONFIG['min_disagreement']}% - {self.SWEET_SPOT_CONFIG['max_disagreement']}%")
            print(f"   最低置信度: {self.SWEET_SPOT_CONFIG['min_confidence']:.0%}")
            print(f"   优选类型: {', '.join(self.SWEET_SPOT_CONFIG['preferred_categories'])}")
            print()

    def print_microstructure_configuration(self):
        """输出微观结构配置"""
        if self.MICROSTRUCTURE_CONFIG["enabled"]:
            print(f"📊 市场微观结构信号: 已启用")
            print(f"   权重: {self.MICROSTRUCTURE_CONFIG['weight']:.0%}")
            print(f"   最低置信度: {self.MICROSTRUCTURE_CONFIG['min_confidence']:.0%}")
            print()

    def print_llm_model_weights(self, llm_model_weights):
        """输出 LLM 模型动态权重"""
        print(f"🤖 LLM 模型动态权重:")
        for model, weight in llm_model_weights.items():
            print(f"   {model}: {weight:.1%}")
        print()

    def print_dynamic_thresholds(self, dynamic_thresholds):
        """输出动态价格阈值"""
        print(
            f"💰 动态价格阈值: {dynamic_thresholds['min_price']:.0%} - {dynamic_thresholds['max_price']:.0%}"
        )
        print()

    def llm_analyze_probability(self, title, news_text, yes_price, category):
        """LLM 分析概率（使用高级投票系统，返回加权平均和投票详情）"""
        # 这里需要调用原 main 函数中的 LLM 分析逻辑
        # 由于原代码较长，这里只是一个占位符
        # 实际实现需要从原 main 函数中提取
        pass

    def search_news(self, title, category):
        """搜索相关新闻"""
        search_queries = get_search_queries(title, category, max_queries=2)
        search_query = search_queries[0] if search_queries else title[:50]

        # 打印使用的关键词（调试用）
        print(f"🔍 搜索关键词: {search_query}")

        try:
            # 2026-06-29: 只搜1个query(原2个), 避免累积超时 >90s
            all_news = []
            news = search_news_for_market(search_query, max_results=2)
            all_news.extend(news)

            # 去重
            seen_titles = set()
            news_list = []
            for n in all_news:
                t = n.get("title", "").lower()
                if t and t not in seen_titles:
                    seen_titles.add(t)
                    news_list.append(n)

            news_sources = list(set(n.get("source_type", "unknown") for n in news_list))
            news_text = "\n".join(
                [
                    f"标题: {n.get('title', '')}\n描述: {n.get('description', '')}"
                    for n in news_list[:4]
                ]
            )
            return news_list, news_sources, news_text
        except Exception as e:
            print(f"⚠️ 新闻搜索失败: {e}")
            return [], [], ""

    def analyze_sentiment(self, news_list, title):
        """情感分析（LLM优先 + 关键词降级，置信度加权聚合）"""
        try:
            if news_list:
                # 使用 analyze_news_sentiment：LLM优先，低置信度自动降级为关键词
                # 分析更多新闻（最多5条），保留真实置信度
                analysis_limit = min(len(news_list), 5)
                sentiment_result = analyze_news_sentiment(
                    news_list[:analysis_limit], market_context=title
                )
                sentiment_score = sentiment_result["overall_score"]
                sentiment_confidence = sentiment_result["confidence"]
            else:
                sentiment_score = 0
                sentiment_confidence = 0
            return sentiment_score, sentiment_confidence
        except Exception as e:
            print(f"⚠️ 情感分析失败: {e}")
            return 0, 0

    def get_onchain_analysis(self, title):
        """链上信号分析"""
        try:
            onchain_signal = get_onchain_signal(title)
            onchain_recommendation = onchain_signal.get("recommendation", "hold")
            onchain_confidence = onchain_signal.get("confidence", 0.3)
            return onchain_signal, onchain_recommendation, onchain_confidence
        except Exception as e:
            print(f"⚠️ 链上信号分析失败: {e}")
            return {"recommendation": "hold", "confidence": 0.3}, "hold", 0.3

    def get_multiplatform_analysis(self, title):
        """多平台信号分析"""
        try:
            multiplatform_signal = get_multiplatform_signal(title)
            has_arbitrage = multiplatform_signal.get("arbitrage_count", 0) > 0
            arbitrage_opportunities = multiplatform_signal.get(
                "arbitrage_opportunities", []
            )
            return multiplatform_signal, has_arbitrage, arbitrage_opportunities
        except Exception as e:
            print(f"⚠️ 多平台信号分析失败: {e}")
            return {"found": False, "arbitrage_count": 0}, False, []

    def get_ml_analysis(self, llm_prob, sentiment_score, preliminary_edge, yes_price,
                       preliminary_direction, onchain_signal, time_to_expiry, category,
                       news_count, vote_details, microstructure_signal):
        """ML 信号分析"""
        try:
            ml_signal = get_ml_signal(
                llm_prob,
                sentiment_score,
                preliminary_edge,
                yes_price,
                preliminary_direction,
                onchain_signal=onchain_signal,
                time_to_expiry=time_to_expiry,
                category=category,
                news_count=news_count,
                vote_details=vote_details,
                microstructure_signal=microstructure_signal,
            )
            ml_prob = ml_signal.get("ml_prob", 0.5)
            ml_confidence = ml_signal.get("confidence", 0.5)
            return ml_signal, ml_prob, ml_confidence
        except Exception as e:
            print(f"⚠️ ML 信号分析失败: {e}")
            return {
                "ml_prob": 0.5,
                "confidence": 0.5,
                "recommendation": "数据不足",
            }, 0.5, 0.5

    def get_microstructure_analysis(self, condition_id, token_id, slug):
        """市场微观结构信号分析"""
        if not self.MICROSTRUCTURE_CONFIG["enabled"]:
            return {"recommendation": "hold", "confidence": 0.3}, 0.5

        try:
            microstructure_signal = calculate_microstructure_signal(
                condition_id, token_id, slug
            )
            microstructure_prob = microstructure_signal.get("confidence", 0.3)
            microstructure_recommendation = microstructure_signal.get("recommendation", "hold")

            # 将微观结构信号转换为概率
            if microstructure_recommendation == "buy":
                microstructure_signal_prob = 0.5 + 0.2 * microstructure_prob
            elif microstructure_recommendation == "sell":
                microstructure_signal_prob = 0.5 - 0.2 * microstructure_prob
            else:
                microstructure_signal_prob = 0.5

            microstructure_signal_prob = max(0.01, min(0.99, microstructure_signal_prob))
            return microstructure_signal, microstructure_signal_prob
        except Exception as e:
            print(f"⚠️ 微观结构信号分析失败: {e}")
            return {"recommendation": "hold", "confidence": 0.3}, 0.5

    def calculate_final_probability(self, llm_signal_prob, sentiment_signal_prob,
                                   onchain_signal_prob, ml_signal_prob,
                                   microstructure_signal_prob, arbitrage_signal,
                                   weights_info):
        """计算最终概率（加权平均）"""
        final_prob = (
            llm_signal_prob * weights_info["llm_weight"]
            + sentiment_signal_prob * weights_info["sentiment_weight"]
            + onchain_signal_prob * weights_info["onchain_weight"]
            + ml_signal_prob * weights_info["ml_weight"]
            + microstructure_signal_prob * weights_info["MICROSTRUCTURE_WEIGHT"]
            + arbitrage_signal * weights_info["ARBITRAGE_WEIGHT"]
        )

        # 边界检查
        final_prob = max(0.01, min(0.99, final_prob))  # 防止极端值
        return final_prob

    def calculate_position_size_for_trade(self, edge, yes_price, voting_confidence, liquidity):
        """计算仓位大小（Fractional Kelly + 投票置信度 + 流动性适配）"""
        # Kelly 公式: f* = edge / (1 - market_price) for Yes bets
        kelly_fraction = 0.25  # 25% Kelly 保守策略
        if edge > 0:  # Yes
            kelly_pct = edge / (1 - yes_price) if (1 - yes_price) > 0.01 else 0
        else:  # No
            kelly_pct = abs(edge) / yes_price if yes_price > 0.01 else 0
        kelly_pct = max(0, min(0.5, kelly_pct))  # 限制单笔不超过50%
        kelly_position = self.balance * kelly_pct * kelly_fraction * voting_confidence

        # 流动性调整
        if liquidity >= 50000:
            liquidity_factor = 1.5
        elif liquidity >= 10000:
            liquidity_factor = 1.0
        else:
            liquidity_factor = max(0.3, liquidity / 10000)

        # 最终仓位 = min(Kelly × 流动性调整, 硬上限)
        # trade_limits.check_trade_allowed 进一步限制单笔≤$10、仓位≤5%
        position_size = min(
            kelly_position * liquidity_factor,
            self.balance * 0.05,
            LIMITS_CONFIG["max_single_trade"],
        )
        # Polymarket 最小下单量 $0.25，若 Kelly 建议低于此值则跳过（边缘优势不足）
        MIN_ORDER = 0.25
        if position_size < MIN_ORDER:
            log.warning(
                f"Kelly仓位 ${position_size:.2f} 低于最小下单额 ${MIN_ORDER}，跳过"
            )
            return None
        return round(position_size, 2)

    def place_order(self, token_id, direction, token_count, order_price):
        """下单（调用 Polymarket API）"""
        # 这里需要调用原 main 函数中的 place_order 函数
        # 由于原代码较长，这里只是一个占位符
        # 实际实现需要从原 main 函数中提取
        pass

    def save_trade_record(self, trade_data):
        """保存交易记录"""
        # 这里需要调用原 main 函数中的 save_trade 函数
        # 由于原代码较长，这里只是一个占位符
        # 实际实现需要从原 main 函数中提取
        pass

    def analyze_market(self, market, weights_info, llm_model_weights, dynamic_thresholds, adaptive_weights):
        """分析单个市场"""
        title = market["title"]
        yes_price = market["yes_price"]
        category = market.get("category", "Other")
        liquidity = market.get("liquidity", 0)
        condition_id = market.get("condition_id", "")
        token_id = market.get("yes_token", "")

        # 初始化所有信号的默认值（防止 NameError）
        microstructure_signal = {"recommendation": "hold", "confidence": 0.3}

        # 全局超时检查：超过 80 秒硬截断（防止某个市场卡死整次 cron）
        elapsed = time.time() - self.start_time
        if elapsed >= 80:
            print(f"⏰ 全局超时 {elapsed:.0f}s >= 80s，中断后续市场扫描")
            log.warning(f"全局超时 {elapsed:.0f}s，仅处理了 {len(self.decisions)}/{len(self.markets)} 个市场")
            return None

        # 甜蜜点模式：聚焦高胜率区间
        if self.SWEET_SPOT_MODE:
            # 跳过甜蜜点区间外的市场
            if yes_price < self.SWEET_SPOT_CONFIG["min_price"] or yes_price > self.SWEET_SPOT_CONFIG["max_price"]:
                return None
            # 跳过低流动性市场（甜蜜点需要更高流动性）
            if liquidity < self.SWEET_SPOT_CONFIG["min_liquidity"]:
                return None
            # 优先选择擅长的事件类型
            if category not in self.SWEET_SPOT_CONFIG["preferred_categories"]:
                return None
        else:
            # 原始模式：使用动态阈值
            if (
                yes_price > dynamic_thresholds["max_price"]
                or yes_price < dynamic_thresholds["min_price"]
            ):
                return None
            # 跳过低流动性市场
            if liquidity < self.MIN_LIQUIDITY:
                return None

        # === 修复：跳过DEDUP_HOURS小时内已交易的市场（用 condition_id 去重） ===
        dedup_key = condition_id if condition_id else title.lower()
        if dedup_key in self.traded_markets:
            print(f"⏭️ 跳过已交易市场: {title[:40]}...")
            return None

        # 2. 搜索相关新闻
        news_list, news_sources, news_text = self.search_news(title, category)

        # 3. 情感分析
        sentiment_score, sentiment_confidence = self.analyze_sentiment(news_list, title)

        # 4. 链上信号分析
        onchain_signal, onchain_recommendation, onchain_confidence = self.get_onchain_analysis(title)

        # 5. 多平台信号分析
        multiplatform_signal, has_arbitrage, arbitrage_opportunities = self.get_multiplatform_analysis(title)

        # 6. LLM 分析概率
        llm_prob, model_results, vote_details = self.llm_analyze_probability(
            title, news_text, yes_price, category
        )
        llm_failed = vote_details.get("llm_failed", False) if vote_details else False

        if llm_prob is None and not llm_failed:
            # 纯 LLM 失败（无回退标记），跳过
            return None

        # LLM 回退模式：用市场当前价格+新闻情感生成一个保守预估
        if llm_prob is None and llm_failed:
            print(f"🔄 LLM 回退模式: 用市场价 {yes_price:.0%} + 情感 {sentiment_score:.2f} 合成")
            # 使用市场当前价作为 base，用情感斜率微调
            sentiment_adjustment = sentiment_score * 0.05  # 情感最多调 ±5pp
            llm_prob = max(0.02, min(0.98, yes_price + sentiment_adjustment))
            model_results = [f"回退(市场{yes_price:.0%}+情感{sentiment_score:.2f})"]

        # 记录投票详情
        if vote_details.get("need_review"):
            log.warning(f"市场 '{title[:30]}' LLM投票分歧大，置信度低")

        # 甜蜜点模式：检查投票质量
        if self.SWEET_SPOT_MODE and not llm_failed:  # LLM 回退模式豁免甜蜜点分歧阈值
            disagreement = vote_details.get("disagreement", 0)
            confidence = vote_details.get("confidence", 0)

            # 分歧太小 = 市场已定价，无优势
            if disagreement < self.SWEET_SPOT_CONFIG["min_disagreement"]:
                print(f"⏭️ 跳过 {title[:40]}... (分歧 {disagreement:.1f}% < {self.SWEET_SPOT_CONFIG['min_disagreement']}%)")
                return None

            # 分歧太大 = 噪声，不可靠
            if disagreement > self.SWEET_SPOT_CONFIG["max_disagreement"]:
                print(f"⏭️ 跳过 {title[:40]}... (分歧 {disagreement:.1f}% > {self.SWEET_SPOT_CONFIG['max_disagreement']}%)")
                return None

            # 置信度太低 = 模型不确定
            if confidence < self.SWEET_SPOT_CONFIG["min_confidence"]:
                print(f"⏭️ 跳过 {title[:40]}... (置信度 {confidence:.2f} < {self.SWEET_SPOT_CONFIG['min_confidence']})")
                return None

        # 7. ML 信号分析（在 LLM 分析之后，因为需要 llm_prob）
        # 先计算 edge 供 ML 使用（ML 需要 edge 作为特征）
        preliminary_edge = llm_prob - yes_price
        preliminary_direction = "Yes" if preliminary_edge > 0 else "No"

        # 计算到期时间（天数）
        end_date = market.get("end_date", "")
        time_to_expiry = 0
        if end_date:
            try:
                if "T" in end_date:
                    dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                else:
                    dt = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                time_to_expiry = max(0, (dt - datetime.now(timezone.utc)).days)
            except (ValueError, TypeError):
                time_to_expiry = 0

        ml_signal, ml_prob, ml_confidence = self.get_ml_analysis(
            llm_prob, sentiment_score, preliminary_edge, yes_price,
            preliminary_direction, onchain_signal, time_to_expiry, category,
            len(news_list), vote_details, microstructure_signal
        )

        # 7. 综合判断（各信号独立计算概率，然后加权平均）
        # 所有信号统一为概率格式 (0-1)
        # 权重来自自适应权重模块（基于历史胜率动态调整）

        # 追踪哪些信号是真实值 vs 回退值
        signal_fallbacks = 0

        # 信号1: LLM 概率（已经是概率，直接使用）
        llm_signal_prob = llm_prob
        # LLM 失败时 llm_prob 为 None → continue，不会到这里

        # 信号2: 情感概率（将 sentiment_score 转换为概率）
        # 使用自适应映射斜率（基于情感信号历史准确率）
        sentiment_mapping_slope = adaptive_weights.get("sentiment_mapping_slope", 0.40)
        sentiment_signal_prob = 0.5 + sentiment_score * sentiment_mapping_slope
        # 放宽截断范围，允许情感信号产生更强影响
        sentiment_signal_prob = max(0.10, min(0.90, sentiment_signal_prob))
        if sentiment_score == 0 and sentiment_confidence == 0:
            signal_fallbacks += 1  # 情感信号完全回退

        # 信号3: 链上概率（连续映射，纳入置信度 × 自适应乘数）
        onchain_confidence_val = onchain_signal.get("confidence", 0.3)
        onchain_mult = adaptive_weights.get("onchain_multiplier", 1.0)
        if onchain_recommendation == "strong_buy":
            onchain_signal_prob = 0.5 + 0.35 * onchain_confidence_val * onchain_mult
        elif onchain_recommendation == "buy":
            onchain_signal_prob = 0.5 + 0.15 * onchain_confidence_val * onchain_mult
        elif onchain_recommendation == "strong_sell":
            onchain_signal_prob = 0.5 - 0.35 * onchain_confidence_val * onchain_mult
        elif onchain_recommendation == "sell":
            onchain_signal_prob = 0.5 - 0.15 * onchain_confidence_val * onchain_mult
        else:
            onchain_signal_prob = 0.5
            if onchain_recommendation == "hold" and onchain_confidence_val <= 0.3:
                signal_fallbacks += 1  # 链上信号无有效数据
        onchain_signal_prob = max(0.01, min(0.99, onchain_signal_prob))  # 边界保护

        # 信号4: ML 概率（已经是概率，直接使用）
        ml_signal_prob = ml_prob
        if ml_confidence <= 0.5 and ml_prob == 0.5:
            signal_fallbacks += 1  # ML 信号无有效数据

        # 信号5: 市场微观结构信号（订单簿、价差、成交量）
        microstructure_signal, microstructure_signal_prob = self.get_microstructure_analysis(
            condition_id, token_id, market.get("slug")
        )

        # 信号6: 多平台/套利信号（方向感知：套利信号不偏向 Yes 或 No）
        # 套利本身是价格差异，不改变事件概率判断，仅作为置信度加成
        if has_arbitrage and arbitrage_opportunities:
            # 套利机会的存在增强了对当前市场定价的置信度
            # 但不改变方向判断 → 回归 0.5（中性），加成体现在权重而非偏移
            arbitrage_signal = 0.5
        else:
            arbitrage_signal = 0.5

        # 使用自适应权重进行加权平均（含微观结构和套利信号）
        final_prob = self.calculate_final_probability(
            llm_signal_prob, sentiment_signal_prob, onchain_signal_prob,
            ml_signal_prob, microstructure_signal_prob, arbitrage_signal,
            weights_info
        )

        # 信号质量检查：2026-06-29 降级为≥3（原≥2），允许LLM回退时有2个信号可用
        if signal_fallbacks >= 3:
            print(f"⏭️ 跳过 {title[:40]}... ({signal_fallbacks}/4 信号回退)")
            return None

        # 8. 计算优势
        edge = final_prob - yes_price

        if edge > 0:
            direction = "Yes"
            token_id = market.get("yes_token", "")
            order_price = yes_price
        else:
            direction = "No"
            token_id = market.get("no_token", "")
            order_price = market.get("no_price", 1 - yes_price)

        # 跳过无 token_id 的市场
        if not token_id:
            return None

        # 7. 风险检查（使用投票置信度，默认中性值 0.5）
        voting_confidence = vote_details.get("confidence", 0.5)
        should_trade_flag, risk_reason = should_trade(
            market,
            confidence=voting_confidence,
            news_sentiment=sentiment_score,
            balance=self.balance,
        )

        decision = {
            "market": market,
            "llm_prob": llm_prob,
            "sentiment_score": sentiment_score,
            "onchain_signal": onchain_signal,
            "ml_signal": ml_signal,
            "multiplatform_signal": multiplatform_signal,
            "arbitrage_opportunities": arbitrage_opportunities,
            "final_prob": final_prob,
            "edge": edge,
            "direction": direction,
            "order_result": None,
            "model_results": model_results,
            "vote_details": vote_details,  # 投票详情（置信度、分歧度）
            "risk_check": {"should_trade": should_trade_flag, "reason": risk_reason},
        }

        # 8. 如果优势足够大，且通过风险检查，下单
        if (
            abs(edge) >= weights_info["edge_threshold"]
            and self.trades_made < self.MAX_TRADES_PER_RUN
            and token_id
            and should_trade_flag
            and not self.stop_loss_triggered
        ):
            # 检查断路器
            try:
                breaker_ok = check_breaker()
            except Exception as e:
                log_error("breaker", e, "断路器检查失败")
                breaker_ok = False  # 断路器异常时禁止交易（fail-closed，保护资金安全）
            if not breaker_ok:
                log.warning("断路器已断开，跳过交易")
                decision["order_result"] = {"status": "BLOCKED", "reason": "断路器断开"}
                return decision

            # 计算仓位大小
            position_size = self.calculate_position_size_for_trade(
                edge, yes_price, voting_confidence, liquidity
            )
            if position_size is None:
                decision["order_result"] = {
                    "status": "SKIPPED",
                    "reason": f"Kelly仓位低于最小下单额",
                }
                return decision

            # 检查交易限额（DRY_RUN 模式跳过资金限额检查，只统计执行）
            if not self.DRY_RUN:
                allowed, limit_reason = check_trade_allowed(position_size, self.balance)
                if not allowed:
                    log.warning(f"交易限额拒绝: {limit_reason}")
                    decision["order_result"] = {"status": "BLOCKED", "reason": limit_reason}
                    return decision

            # Kelly 计算出的是美元金额，CLOB 需要代币数量（shares）
            token_count = (
                position_size / order_price if order_price > 0 else position_size
            )
            result = self.place_order(token_id, "BUY", round(token_count, 2), order_price)
            decision["order_result"] = result

            # 记录交易（包含 condition_id 用于去重，含信号数据用于自适应学习）
            self.save_trade_record({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "mode": "DRY_RUN" if self.DRY_RUN else "LIVE",
                "market": title,
                "condition_id": condition_id,
                "category": category,
                "direction": direction,
                "market_price": yes_price if direction == "Yes" else market["no_price"],
                "llm_prob": llm_prob,
                "sentiment_score": sentiment_score,
                "onchain_signal": onchain_signal,
                "ml_prob": ml_prob,
                "model_results": model_results,
                "final_prob": final_prob,
                "edge": edge,
                "amount": position_size,
                "status": result.get("status"),
                "token_id": token_id,
                "risk_reason": risk_reason,
                "news_sources": news_sources,
                "end_date": market.get("end_date", ""),
                "result": "pending",  # 初始状态：待结算
            })
            self.trades_made += 1

            # 记录到交易限额
            record_trade(position_size)

        return decision

    def execute_trade(self, decision):
        """执行交易（已集成到 analyze_market 中）"""
        # 这里只是为了保持接口一致性
        return decision

    def process_markets(self, markets, weights_info, llm_model_weights, dynamic_thresholds, adaptive_weights):
        """处理所有市场"""
        self.markets = markets
        for market in markets:
            # 检查断路器
            if check_breaker():
                log.warning("断路器触发，停止交易")
                print("🚨 断路器触发，停止交易")
                break

            # 检查交易限额
            allowed, reason = check_trade_allowed()
            if not allowed:
                log.warning(f"交易限额: {reason}")
                print(f"⚠️ 交易限额: {reason}")
                break

            # 分析市场
            try:
                decision = self.analyze_market(market, weights_info, llm_model_weights, dynamic_thresholds, adaptive_weights)
                if decision:
                    self.decisions.append(decision)
            except Exception as e:
                log_error("market_analysis", e, f"市场分析失败: {market.get('title', '')[:50]}")
                continue

            # 避免 API 限流
            time.sleep(1)

    def generate_reports(self):
        """生成报告"""
        # 8. 结算同步报告
        try:
            print(fmt_settlement_report())
        except Exception as e:
            log_error("main", e, "结算报告生成失败")

        # 9. 风险报告
        try:
            print(get_risk_report())
        except Exception as e:
            log_error("main", e, "风险报告生成失败")
            print(f"⚠️ 风险报告生成失败: {e}")

        # 10. 断路器状态
        try:
            breaker_status = get_breaker_status()
            status_emoji = {"closed": "🟢", "open": "🔴", "half_open": "🟡"}
            print(f"\n⚡ 断路器状态:")
            print(
                f"   状态: {status_emoji.get(breaker_status['status'], '❓')} {breaker_status['status']}"
            )
            print(f"   连续亏损: {breaker_status['consecutive_losses']}")
            print(f"   今日盈亏: ${breaker_status['daily_pnl']:+.2f}")
        except Exception as e:
            log_error("main", e, "断路器状态获取失败")

        # 11. 交易限额状态
        try:
            limits_status = get_limits_status()
            print(f"\n📊 交易限额:")
            print(
                f"   今日交易: {limits_status['daily_trades']}/{limits_status['max_daily_trades']}"
            )
            print(
                f"   今日交易量: ${limits_status['daily_volume']:.2f}/${limits_status['max_daily_volume']:.2f}"
            )
        except Exception as e:
            log_error("main", e, "交易限额状态获取失败")

        # 输出止损状态
        if self.stop_loss_triggered:
            print(
                f"\n🛑 止损已触发：累计回撤 {self.stop_loss_result['drawdown_pct']:.2%}，暂停新交易"
            )
        else:
            print(f"\n✅ 止损状态：正常（累计回撤 {self.stop_loss_result['drawdown_pct']:.2%}）")

        # 输出动态优化报告
        try:
            print(format_optimization_report())
        except Exception as e:
            print(f"⚠️ 优化报告生成失败: {e}")

    def print_summary(self, markets):
        """输出运行汇总"""
        elapsed = time.time() - self.start_time
        print(f"\n📋 运行汇总:")
        print(f"   扫描市场: {len(markets)} 个")
        print(f"   分析决策: {len(self.decisions)} 个")
        print(f"   本轮下单: {self.trades_made} 笔")
        print(f"   耗时: {elapsed:.1f} 秒")
        if len(self.decisions) == 0 and len(markets) > 0:
            print(f"   ⚠️ 所有市场均被跳过（去重/价格/流动性过滤）")

    def run(self):
        """主流程（集成新闻搜索、情感分析、风险管理、自适应权重 + 动态优化）"""
        self.start_time = time.time()
        log.info("=" * 50)
        log.info("PolyStrat 启动")

        # 1. 结算同步
        self.sync_settlements()

        # 2. 套利扫描
        self.scan_arbitrage()

        # 3. 获取活跃市场
        markets = self.fetch_markets(limit=50)
        if not markets:
            return

        # 4. 加载交易历史并计算自适应权重
        adaptive_weights = self.load_trade_history_and_calculate_weights()

        # 5. 检查止损
        self.check_stop_loss()

        # 6. 计算动态优化参数
        llm_model_weights, dynamic_thresholds = self.calculate_dynamic_optimization()

        # 7. 构建已交易市场集合
        self.build_traded_markets_set()

        # 8. 计算自适应权重和阈值
        weights_info = self.calculate_adaptive_weights_and_thresholds(adaptive_weights)

        # 9. 输出配置信息
        self.print_weight_configuration(weights_info)
        self.print_sweet_spot_configuration()
        self.print_microstructure_configuration()
        self.print_llm_model_weights(llm_model_weights)
        self.print_dynamic_thresholds(dynamic_thresholds)

        # 10. 处理所有市场
        self.process_markets(markets, weights_info, llm_model_weights, dynamic_thresholds, adaptive_weights)

        # 11. 生成报告
        self.generate_reports()

        # 12. 输出运行汇总
        self.print_summary(markets)


def main():
    """主流程入口（重构版）"""
    agent = PolyStratAgent()
    agent.run()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        handle_error(e, "PolyStrat 主流程崩溃")
        raise
