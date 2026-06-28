"""
PolyStrat 动态优化模块
实现全流程动态调整：
1. LLM 模型动态加权（根据每个模型的历史准确率）
2. 新闻源质量评分（根据返回结果质量动态分配配额）
3. 仓位流动性适配（大额下注考虑市场深度）
4. 市场过滤动态化（根据历史胜率调整阈值）
5. 去重窗口优化（根据市场结算时间动态调整）
"""

import json
from safe_file_ops import atomic_read_json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import defaultdict

# 交易记录文件
TRADE_LOG = Path(
    "/root/.hermes/profiles/life/home/.hermes/polymarket_bot/logs/polystrat_trades.json"
)

# 优化配置文件
OPTIMIZATION_CONFIG = Path("/root/.hermes/profiles/life/data/optimization_config.json")

# 默认配置
DEFAULT_CONFIG = {
    "llm_model_weights": {
        "MiniMax M2.7": 0.35,
        "Nemotron 3 Super": 0.30,
        "Llama 3.3 70B": 0.20,
        "GLM-5.1": 0.15,
    },
    "news_source_scores": {
        "gnews": 0.7,
        "currents": 0.8,
        "newsdata": 0.75,
        "nytimes": 0.9,
        "serpapi": 0.85,
        "rss": 0.75,
    },
    "price_thresholds": {"min_price": 0.03, "max_price": 0.97},
    "dedup_hours": 24,
    "liquidity_multiplier": 0.1,  # 仓位 = 基础仓位 * (流动性/10000) * multiplier
    "max_position_pct": 0.05,  # 单笔最大仓位占总资金比例
}


def load_optimization_config():
    """加载优化配置"""
    try:
        if OPTIMIZATION_CONFIG.exists():
            with open(OPTIMIZATION_CONFIG) as f:
                return json.load(f)
    except Exception:
        pass
    return DEFAULT_CONFIG.copy()


def save_optimization_config(config):
    """保存优化配置"""
    try:
        OPTIMIZATION_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        with open(OPTIMIZATION_CONFIG, "w") as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        print(f"⚠️ 保存优化配置失败: {e}")


def load_trade_history():
    """加载交易历史（使用安全文件操作）"""
    return atomic_read_json(TRADE_LOG, default=[])


def get_recent_trades(days=7):
    """获取最近N天的交易"""
    trades = load_trade_history()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    recent = []
    for t in trades:
        try:
            ts = t.get("timestamp", "")
            if ts:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if dt >= cutoff:
                    recent.append(t)
        except Exception:
            continue
    return recent


# ============================================================
# 1. LLM 模型动态加权
# ============================================================


def calculate_llm_model_weights(trades=None, window_days=7):
    """
    根据每个 LLM 模型的历史准确率，动态调整权重

    逻辑：
    - 统计每个模型的预测准确率
    - 准确率高的模型获得更高权重
    - 使用指数移动平均平滑调整
    """
    config = load_optimization_config()

    if trades is None:
        trades = get_recent_trades(window_days)

    if len(trades) < 10:
        return config["llm_model_weights"]

    # 统计每个模型的准确率
    model_stats = defaultdict(lambda: {"correct": 0, "total": 0})

    for trade in trades:
        model_results = trade.get("model_results", [])
        actual_result = trade.get("result", "")
        if actual_result not in ("win", "lose"):
            continue

        actual_is_win = actual_result == "win"

        for model_result in model_results:
            # 与 polystrat_agent.py 一致：格式 "ModelName:XX¢"
            if ":" in model_result:
                parts = model_result.rsplit(":", 1)
                model_name = parts[0].strip()
                try:
                    pred_prob = int(parts[1].replace("¢", "").strip()) / 100
                except Exception:
                    continue

                # 判断预测是否正确
                predicted_win = pred_prob > 0.5
                if predicted_win == actual_is_win:
                    model_stats[model_name]["correct"] += 1
                model_stats[model_name]["total"] += 1

    # 计算新权重
    new_weights = {}
    total_accuracy = 0

    for model_name, stats in model_stats.items():
        if stats["total"] >= 3:  # 至少3次预测才计算
            accuracy = stats["correct"] / stats["total"]
            new_weights[model_name] = accuracy
            total_accuracy += accuracy

    # 归一化
    if total_accuracy > 0 and new_weights:
        for model_name in new_weights:
            new_weights[model_name] /= total_accuracy

        # 使用指数移动平均平滑调整（避免剧烈波动）
        alpha = 0.3  # 平滑因子
        old_weights = config["llm_model_weights"]

        for model_name in new_weights:
            if model_name in old_weights:
                new_weights[model_name] = (
                    alpha * new_weights[model_name]
                    + (1 - alpha) * old_weights[model_name]
                )

        # 再次归一化
        total = sum(new_weights.values())
        for model_name in new_weights:
            new_weights[model_name] /= total

        config["llm_model_weights"] = new_weights
        save_optimization_config(config)

        return new_weights

    return config["llm_model_weights"]


def get_llm_model_weight(model_name):
    """获取单个模型的权重"""
    weights = calculate_llm_model_weights()
    return weights.get(model_name, 0.33)


# ============================================================
# 2. 新闻源质量评分
# ============================================================


def calculate_news_source_scores(trades=None, window_days=7):
    """
    根据新闻源的历史表现动态调整质量评分

    质量指标：
    - 来源在获胜交易中的出现频率
    - 至少3次使用记录才更新评分（避免小样本偏差）
    - 使用平滑更新（30% 历史分 + 70% 新分）
    """
    config = load_optimization_config()

    if trades is None:
        trades = get_recent_trades(window_days)

    if len(trades) < 5:
        return config["news_source_scores"]

    source_stats = defaultdict(lambda: {"count": 0, "wins": 0})

    for trade in trades:
        result = trade.get("result", "")
        if result not in ("win", "lose"):
            continue

        news_sources = trade.get("news_sources", [])
        if not news_sources:
            continue

        for source in news_sources:
            source_stats[source]["count"] += 1
            if result == "win":
                source_stats[source]["wins"] += 1

    scores = config["news_source_scores"].copy()

    for source, stats in source_stats.items():
        if stats["count"] >= 3:
            win_rate = stats["wins"] / stats["count"]
            base_score = config["news_source_scores"].get(source, 0.7)
            scores[source] = round(0.3 * base_score + 0.7 * win_rate, 2)

    config["news_source_scores"] = scores
    save_optimization_config(config)

    return scores


def get_news_source_quota(source_type, base_quota=2):
    """获取新闻源的动态配额"""
    scores = calculate_news_source_scores()
    score = scores.get(source_type, 0.7)

    # 根据质量评分调整配额
    # 评分 0.9+ -> 3条
    # 评分 0.7-0.9 -> 2条
    # 评分 <0.7 -> 1条
    if score >= 0.9:
        return base_quota + 1
    elif score < 0.7:
        return max(1, base_quota - 1)
    return base_quota


# ============================================================
# 3. 仓位流动性适配
# ============================================================


def calculate_position_with_liquidity(balance, confidence, liquidity, base_amount=2.0):
    """
    根据市场流动性动态调整仓位

    逻辑：
    - 流动性高（>$50k）：可以下大注
    - 流动性中（$10k-$50k）：正常下注
    - 流动性低（<$10k）：下小注，避免滑点
    """
    config = load_optimization_config()
    max_position_pct = config.get("max_position_pct", 0.05)
    liquidity_multiplier = config.get("liquidity_multiplier", 0.1)

    # 基础仓位
    base_position = base_amount * confidence

    # 流动性调整因子
    if liquidity >= 50000:
        liquidity_factor = 1.5  # 高流动性，可以下大注
    elif liquidity >= 10000:
        liquidity_factor = 1.0  # 正常
    else:
        liquidity_factor = max(0.3, liquidity / 10000)  # 低流动性，减小仓位

    # 最终仓位
    position = base_position * liquidity_factor

    # 限制最大仓位
    max_position = balance * max_position_pct
    position = min(position, max_position, base_amount * 2)  # 不超过基础仓位的2倍

    return round(position, 2)


# ============================================================
# 4. 市场过滤动态化
# ============================================================


def get_dynamic_price_thresholds(trades=None, window_days=7):
    """
    根据历史胜率动态调整价格过滤阈值

    逻辑：
    - 胜率高：可以放宽阈值（0.02-0.98）
    - 胜率正常：保持默认（0.03-0.97）
    - 胜率低：收紧阈值（0.05-0.95）
    """
    config = load_optimization_config()

    if trades is None:
        trades = get_recent_trades(window_days)

    if len(trades) < 10:
        return config["price_thresholds"]

    # 计算近期胜率（仅基于已结算结果）
    # 注意：不能用 edge 方向一致性，这是数据泄露！
    wins = 0
    settled_count = 0
    for t in trades:
        result = t.get("result", "")

        # 只使用已结算的交易
        if result == "win":
            wins += 1
            settled_count += 1
        elif result == "lose":
            settled_count += 1
        # 未结算的交易跳过，不计入

    # 如果没有已结算交易，使用默认阈值
    if settled_count == 0:
        return config["price_thresholds"]

    win_rate = wins / settled_count

    # 根据胜率调整阈值
    if win_rate > 0.6:
        # 胜率高，放宽阈值
        return {"min_price": 0.02, "max_price": 0.98}
    elif win_rate < 0.4:
        # 胜率低，收紧阈值
        return {"min_price": 0.05, "max_price": 0.95}
    else:
        # 正常
        return config["price_thresholds"]


# ============================================================
# 5. 去重窗口优化
# ============================================================


def get_dynamic_dedup_hours(end_date_str):
    """
    根据市场结算时间动态调整去重窗口

    逻辑：
    - 结算时间 < 24小时：去重窗口 = 结算时间的一半
    - 结算时间 1-7天：去重窗口 = 24小时
    - 结算时间 > 7天：去重窗口 = 48小时（避免频繁交易）
    """
    if not end_date_str:
        return 24

    try:
        end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        hours_to_settlement = (end_date - now).total_seconds() / 3600

        if hours_to_settlement < 0:
            return 0  # 已结算，不交易
        elif hours_to_settlement < 24:
            return max(1, int(hours_to_settlement / 2))  # 结算临近，减少去重窗口
        elif hours_to_settlement > 168:  # 7天
            return 48  # 远期市场，增加去重窗口
        else:
            return 24  # 正常
    except Exception:
        return 24


# ============================================================
# 综合优化报告
# ============================================================


def get_optimization_report():
    """获取优化状态报告"""
    config = load_optimization_config()
    trades = get_recent_trades(7)

    report = {
        "sample_size": len(trades),
        "llm_weights": config.get("llm_model_weights", {}),
        "news_scores": config.get("news_source_scores", {}),
        "price_thresholds": config.get("price_thresholds", {}),
        "dedup_hours": config.get("dedup_hours", 24),
    }

    # 计算动态值
    if len(trades) >= 10:
        report["dynamic_llm_weights"] = calculate_llm_model_weights(trades)
        report["dynamic_thresholds"] = get_dynamic_price_thresholds(trades)

    return report


def format_optimization_report():
    """格式化优化报告"""
    report = get_optimization_report()

    lines = []
    lines.append("📊 PolyStrat 动态优化报告")
    lines.append("=" * 50)
    lines.append(f"样本数量: {report['sample_size']} 笔交易")
    lines.append("")

    lines.append("🤖 LLM 模型权重:")
    for model, weight in report.get(
        "dynamic_llm_weights", report["llm_weights"]
    ).items():
        lines.append(f"   {model}: {weight:.1%}")

    lines.append("")
    lines.append("📰 新闻源质量评分:")
    for source, score in report["news_scores"].items():
        emoji = "⭐" if score >= 0.8 else "✅" if score >= 0.7 else "⚠️"
        lines.append(f"   {emoji} {source}: {score:.2f}")

    lines.append("")
    thresholds = report.get("dynamic_thresholds", report["price_thresholds"])
    lines.append(
        f"💰 价格阈值: {thresholds['min_price']:.0%} - {thresholds['max_price']:.0%}"
    )
    lines.append(f"⏰ 去重窗口: {report['dedup_hours']} 小时")

    return "\n".join(lines)


# 测试
if __name__ == "__main__":
    print(format_optimization_report())
    print()

    # 测试仓位计算
    print("📊 仓位流动性适配测试:")
    test_cases = [
        (1000, 0.8, 50000),  # 高流动性
        (1000, 0.8, 10000),  # 中流动性
        (1000, 0.8, 5000),  # 低流动性
    ]
    for balance, conf, liq in test_cases:
        pos = calculate_position_with_liquidity(balance, conf, liq)
        print(f"   余额=${balance}, 置信度={conf}, 流动性=${liq} -> 仓位=${pos}")
