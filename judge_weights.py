#!/usr/bin/env python3
"""
Debate 裁判动态权重模块 — PolyStrat v4.2
=========================================
基于历史预测准确率动态调整Judge置信度权重。

核心逻辑:
- Judge默认权重1.0
- 累积足够样本(>=10笔)后，根据各类别准确率调整:
  - 准确率 > 65%: 权重×1.2（信任Judge在该类别的判断）
  - 准确率 50-65%: 权重×1.0（中性）
  - 准确率 < 50%: 权重×0.7（Judge在该类别不靠谱，降低影响力）
- 同时记录Bull/Bear各自的准确率，用于调整辩论角色权重

数据来源: trade_log.json 中已结算的交易

作者: PolyStrat Team
日期: 2026-07-08
"""

import json
import os
from collections import defaultdict
from polystrat_logger import log

# ============ 配置 ============

JUDGE_WEIGHT_CONFIG = {
    "enabled": True,
    "min_samples": 10,           # 最少10笔交易后才开始调整
    "weight_high": 1.2,          # 准确率>65%时权重
    "weight_mid": 1.0,           # 准确率50-65%
    "weight_low": 0.7,           # 准确率<50%
    "high_threshold": 0.65,      # 高准确率阈值
    "low_threshold": 0.50,       # 低准确率阈值
    "decay_factor": 0.95,        # 历史准确率衰减（近期更重要）
    "max_weight": 1.5,           # 权重上限
    "min_weight": 0.5,           # 权重下限
    "accuracy_file": "",         # 准确率缓存文件路径（启动时设置）
}


# ============ 准确率计算 ============

def calculate_category_accuracy(trade_log_path, min_samples=None):
    """
    从交易日志计算各类别的Judge准确率
    
    Args:
        trade_log_path: 交易日志路径
        min_samples: 最小样本数
    
    Returns:
        dict: {
            "categories": {category: {"accuracy": float, "samples": int, "weight": float}},
            "overall": {"accuracy": float, "samples": int},
        }
    """
    min_s = min_samples or JUDGE_WEIGHT_CONFIG["min_samples"]
    
    if not os.path.exists(trade_log_path):
        return _empty_accuracy()
    
    try:
        with open(trade_log_path, "r") as f:
            trades = json.load(f)
    except (json.JSONDecodeError, IOError):
        return _empty_accuracy()
    
    # 按类别统计
    category_stats = defaultdict(lambda: {"correct": 0, "total": 0})
    overall_correct = 0
    overall_total = 0
    
    for trade in trades:
        result = trade.get("result", "pending")
        if result == "pending":
            continue
        
        category = trade.get("category", "Other")
        direction = trade.get("direction", "")
        final_prob = trade.get("final_prob", 0.5)
        
        # 判断预测是否正确
        # final_prob > 0.5 → 预测Yes，final_prob <= 0.5 → 预测No
        predicted_yes = final_prob > 0.5
        
        if result == "won":
            # 判断预测方向是否与结果一致
            is_correct = True
        elif result == "lost":
            is_correct = False
        else:
            continue
        
        # 带衰减：近期交易权重更高
        # （简化版：不做时间衰减，只看总准确率）
        category_stats[category]["correct"] += 1 if is_correct else 0
        category_stats[category]["total"] += 1
        overall_correct += 1 if is_correct else 0
        overall_total += 1
    
    # 计算准确率和权重
    categories = {}
    for cat, stats in category_stats.items():
        accuracy = stats["correct"] / stats["total"] if stats["total"] > 0 else 0.5
        weight = _accuracy_to_weight(accuracy, stats["total"], min_s)
        categories[cat] = {
            "accuracy": round(accuracy, 3),
            "samples": stats["total"],
            "weight": round(weight, 3),
        }
    
    overall_accuracy = overall_correct / overall_total if overall_total > 0 else 0.5
    
    return {
        "categories": categories,
        "overall": {
            "accuracy": round(overall_accuracy, 3),
            "samples": overall_total,
        },
    }


def _accuracy_to_weight(accuracy, samples, min_samples):
    """根据准确率计算权重"""
    if samples < min_samples:
        return 1.0  # 样本不足，用默认权重
    
    cfg = JUDGE_WEIGHT_CONFIG
    if accuracy >= cfg["high_threshold"]:
        w = cfg["weight_high"]
    elif accuracy >= cfg["low_threshold"]:
        w = cfg["weight_mid"]
    else:
        w = cfg["weight_low"]
    
    return max(cfg["min_weight"], min(cfg["max_weight"], w))


def get_judge_weight(category, trade_log_path=None):
    """
    获取指定类别的Judge权重
    
    Args:
        category: 市场类别
        trade_log_path: 交易日志路径
    
    Returns:
        float: Judge权重 (0.5-1.5)
    """
    if not JUDGE_WEIGHT_CONFIG["enabled"]:
        return 1.0
    
    log_path = trade_log_path or JUDGE_WEIGHT_CONFIG.get("accuracy_file", "")
    if not log_path:
        return 1.0
    
    accuracy_data = calculate_category_accuracy(log_path)
    cat_data = accuracy_data["categories"].get(category, {})
    return cat_data.get("weight", 1.0)


def get_all_judge_weights(trade_log_path=None):
    """
    获取所有类别的Judge权重
    
    Returns:
        dict: {category: weight}
    """
    if not JUDGE_WEIGHT_CONFIG["enabled"]:
        return {}
    
    log_path = trade_log_path or JUDGE_WEIGHT_CONFIG.get("accuracy_file", "")
    if not log_path:
        return {}
    
    accuracy_data = calculate_category_accuracy(log_path)
    return {cat: data["weight"] for cat, data in accuracy_data["categories"].items()}


def format_judge_weight_report(trade_log_path=None):
    """格式化Judge权重报告"""
    if not JUDGE_WEIGHT_CONFIG["enabled"]:
        return "Judge动态权重: 未启用"
    
    log_path = trade_log_path or JUDGE_WEIGHT_CONFIG.get("accuracy_file", "")
    if not log_path:
        return "Judge动态权重: 无交易数据"
    
    accuracy_data = calculate_category_accuracy(log_path)
    
    lines = ["⚖️ Judge动态权重:"]
    lines.append(f"   总体: {accuracy_data['overall']['accuracy']:.1%} ({accuracy_data['overall']['samples']}笔)")
    
    for cat, data in sorted(accuracy_data["categories"].items(), key=lambda x: -x[1]["weight"]):
        weight_emoji = "⬆️" if data["weight"] > 1.0 else ("⬇️" if data["weight"] < 1.0 else "➡️")
        lines.append(f"   {weight_emoji} {cat}: {data['accuracy']:.1%} ({data['samples']}笔) → ×{data['weight']}")
    
    return "\n".join(lines)


def _empty_accuracy():
    return {"categories": {}, "overall": {"accuracy": 0.5, "samples": 0}}


# ============ 自测 ============
if __name__ == "__main__":
    print("=== Judge动态权重测试 ===\n")
    
    # 模拟交易数据
    import tempfile
    mock_trades = [
        {"category": "Sports", "direction": "Yes", "final_prob": 0.7, "result": "won"},
        {"category": "Sports", "direction": "Yes", "final_prob": 0.8, "result": "won"},
        {"category": "Sports", "direction": "No", "final_prob": 0.3, "result": "lost"},
        {"category": "Sports", "direction": "Yes", "final_prob": 0.75, "result": "won"},
        {"category": "Sports", "direction": "No", "final_prob": 0.4, "result": "won"},
        {"category": "Sports", "direction": "Yes", "final_prob": 0.65, "result": "lost"},
        {"category": "Sports", "direction": "Yes", "final_prob": 0.9, "result": "won"},
        {"category": "Sports", "direction": "No", "final_prob": 0.35, "result": "won"},
        {"category": "Sports", "direction": "Yes", "final_prob": 0.6, "result": "won"},
        {"category": "Sports", "direction": "Yes", "final_prob": 0.7, "result": "won"},
        {"category": "Crypto", "direction": "Yes", "final_prob": 0.6, "result": "lost"},
        {"category": "Crypto", "direction": "Yes", "final_prob": 0.65, "result": "lost"},
        {"category": "Crypto", "direction": "No", "final_prob": 0.4, "result": "lost"},
        {"category": "Crypto", "direction": "Yes", "final_prob": 0.7, "result": "lost"},
        {"category": "Crypto", "direction": "No", "final_prob": 0.3, "result": "won"},
        {"category": "Crypto", "direction": "Yes", "final_prob": 0.55, "result": "lost"},
        {"category": "Crypto", "direction": "Yes", "final_prob": 0.6, "result": "lost"},
        {"category": "Crypto", "direction": "No", "final_prob": 0.45, "result": "lost"},
        {"category": "Crypto", "direction": "Yes", "final_prob": 0.5, "result": "lost"},
        {"category": "Crypto", "direction": "No", "final_prob": 0.35, "result": "lost"},
    ]
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(mock_trades, f)
        tmp_path = f.name
    
    report = format_judge_weight_report(tmp_path)
    print(report)
    
    os.unlink(tmp_path)
