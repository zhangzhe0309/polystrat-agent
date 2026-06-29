#!/usr/bin/env python3
"""
高级投票系统模块
- 加权投票算法
- 分歧检测与处理
- 异常值过滤
- 置信度评估
"""

import numpy as np
from collections import defaultdict
from polystrat_logger import log


class AdvancedVotingSystem:
    """
    高级投票系统
    - 加权投票（基于历史准确率）
    - 分歧检测（标准差阈值）
    - 异常值处理（MAD检测）
    - 置信度评估
    """

    def __init__(self, model_names, historical_accuracy=None):
        """
        初始化投票系统

        Args:
            model_names: 模型名称列表
            historical_accuracy: 各模型历史准确率 {model_name: accuracy}
        """
        self.models = model_names
        self.n_models = len(model_names)

        # 初始化权重
        self.weights = {}
        if historical_accuracy:
            total_acc = sum(historical_accuracy.values())
            if total_acc == 0:
                total_acc = 1e-10  # 防零除
            for model in model_names:
                self.weights[model] = historical_accuracy.get(model, 0.5) / total_acc
        else:
            # 默认等权重
            self.weights = {model: 1.0 / self.n_models for model in model_names}

        # 分歧阈值（动态调整）
        # 低波动市场：15% 阈值
        # 正常市场：20% 阈值
        # 高波动市场：30% 阈值
        self.disagreement_threshold = 20  # 默认阈值

    def detect_outliers(self, predictions):
        """
        使用 MAD（中位数绝对偏差）检测异常值

        Args:
            predictions: 预测值列表

        Returns:
            numpy.array: 布尔数组，True表示异常值
        """
        if len(predictions) < 3:
            return np.array([False] * len(predictions))

        median = np.median(predictions)
        mad = np.median(np.abs(predictions - median))

        # 避免除零
        if mad == 0:
            return np.array([False] * len(predictions))

        # Modified Z-score
        modified_z_scores = 0.6745 * (predictions - median) / mad
        return np.abs(modified_z_scores) > 3.5

    def calculate_disagreement(self, predictions):
        """
        计算模型间的分歧程度

        Args:
            predictions: 预测值列表

        Returns:
            float: 标准差（分歧程度）
        """
        return np.std(predictions)

    def calculate_confidence(self, predictions, weights, n_outliers=0):
        """
        计算置信度分数

        Args:
            predictions: 预测值列表
            weights: 权重字典
            n_outliers: 异常值数量

        Returns:
            float: 置信度 (0-1)
        """
        # 基于一致性的置信度
        disagreement = self.calculate_disagreement(predictions)
        consistency_score = max(0, 1 - disagreement / 100)

        # 基于权重的集中度（主模型占比越高，置信度越高）
        weight_values = sorted(weights.values(), reverse=True)
        top_weight = weight_values[0] if weight_values else 0.25
        concentration_score = min(1, top_weight * 2.5)

        # 异常值惩罚
        outlier_penalty = 1.0 - (n_outliers / max(len(predictions), 1)) * 0.5

        # 综合置信度（移除熵，改用集中度）
        confidence = (
            0.6 * consistency_score
            + 0.25 * concentration_score
            + 0.15 * outlier_penalty
        )
        return min(1, max(0, confidence))

    def get_dynamic_threshold(self, predictions):
        """
        根据市场波动动态调整分歧阈值（连续映射）

        Args:
            predictions: 预测值数组

        Returns:
            float: 动态阈值
        """
        if len(predictions) < 2:
            return self.disagreement_threshold

        # 计算预测值的标准差
        std = np.std(predictions)

        # 连续映射：std 5-35 → 阈值 15-30
        # 低波动 → 低阈值（严格），高波动 → 高阈值（宽松）
        threshold = 15 + (max(0, std - 5) / 30) * 15
        return round(min(30, max(15, threshold)), 1)

    def vote(self, predictions_dict):
        """
        执行加权投票

        Args:
            predictions_dict: {model_name: prediction} 字典

        Returns:
            dict: 投票结果
        """
        # 提取预测值
        pred_values = []
        model_names = []
        for model in self.models:
            if model in predictions_dict:
                pred_values.append(predictions_dict[model])
                model_names.append(model)

        if not pred_values:
            return {
                "final_prediction": 0.5,
                "confidence": 0,
                "disagreement": 100,
                "need_review": True,
                "model_weights": {},
                "outliers": [],
            }

        pred_array = np.array(pred_values)

        # 检测异常值
        outliers = self.detect_outliers(pred_array)

        # 调整权重（异常值降权）
        adjusted_weights = {}
        for i, model in enumerate(model_names):
            base_weight = self.weights.get(model, 1.0 / self.n_models)
            if outliers[i]:
                adjusted_weights[model] = base_weight * 0.2  # 异常值权重降为20%
            else:
                adjusted_weights[model] = base_weight

        # 归一化权重
        total_weight = sum(adjusted_weights.values())
        if total_weight > 0:
            adjusted_weights = {
                m: w / total_weight for m, w in adjusted_weights.items()
            }

        # 计算加权平均
        weighted_sum = sum(
            predictions_dict[model] * adjusted_weights.get(model, 0)
            for model in model_names
        )

        # 计算分歧程度
        disagreement = self.calculate_disagreement(pred_array)

        # 计算置信度
        confidence = self.calculate_confidence(
            pred_array, adjusted_weights, n_outliers=int(sum(outliers))
        )

        # 获取动态阈值
        dynamic_threshold = self.get_dynamic_threshold(pred_array)

        # 判断是否需要人工审查
        need_review = disagreement > dynamic_threshold or confidence < 0.4

        return {
            "final_prediction": weighted_sum,
            "confidence": confidence,
            "disagreement": disagreement,
            "need_review": need_review,
            "model_weights": adjusted_weights,
            "outliers": outliers.tolist(),
            "individual_predictions": predictions_dict,
        }


def create_voting_system(trade_history=None, model_weights=None):
    """
    创建投票系统实例

    Args:
        trade_history: 交易历史（用于计算历史准确率）
        model_weights: 外部传入的模型权重 {model_name: weight}（优先级最高）
                       dict 的 key 作为模型列表，避免硬编码

    Returns:
        AdvancedVotingSystem: 投票系统实例
    """
    # 优先使用外部传入的动态权重
    if model_weights and isinstance(model_weights, dict):
        model_names = list(model_weights.keys())
        historical_accuracy = model_weights
    elif trade_history:
        model_names = [
            "MiniMax M2.7",
            "Nemotron 3 Super",
            "Llama 3.3 70B",
            "GLM-5.1",
        ]
        historical_accuracy = calculate_historical_accuracy(trade_history)
    else:
        model_names = [
            "MiniMax M2.7",
            "Nemotron 3 Super",
            "Llama 3.3 70B",
            "GLM-5.1",
        ]
        historical_accuracy = None

    return AdvancedVotingSystem(model_names, historical_accuracy)


def calculate_historical_accuracy(trade_history):
    """
    从交易历史计算各模型准确率（方向感知）

    准确率评判逻辑：
    - Yes 方向交易：模型概率 > 市场价 → 预测赢
    - No 方向交易：模型概率 < 市场价 → 预测赢
    （模型概率高于市场价意味着模型认为 Yes 更可能，支持 Yes 方向）

    Args:
        trade_history: 交易历史列表

    Returns:
        dict: {model_name: accuracy}
    """
    model_stats = defaultdict(lambda: {"correct": 0, "total": 0})

    for trade in trade_history:
        model_results = trade.get("model_results", [])
        actual_result = trade.get("result", "")
        direction = trade.get("direction", "Yes")
        market_price = trade.get("market_price", 0.5)

        if actual_result not in ("win", "lose"):
            continue

        for result_str in model_results:
            # 解析 "ModelName:XX¢" 格式（用 rsplit 防止模型名含冒号）
            if ":" in result_str:
                parts = result_str.rsplit(":", 1)
                model_name = parts[0].strip()
                try:
                    prob = int(parts[1].replace("¢", "").strip()) / 100
                except (ValueError, AttributeError):
                    continue

                # 方向感知判断：模型预测是否支持交易方向
                if direction == "Yes":
                    # Yes 方向：模型概率 > 市场价 → 模型支持该交易方向
                    predicted_correct = prob > market_price
                elif direction == "No":
                    # No 方向：模型概率 < 市场价 → 模型支持该交易方向
                    predicted_correct = prob < market_price
                else:
                    continue

                actual_win = actual_result == "win"
                if predicted_correct == actual_win:
                    model_stats[model_name]["correct"] += 1
                model_stats[model_name]["total"] += 1

    # 计算准确率
    accuracy = {}
    for model, stats in model_stats.items():
        if stats["total"] >= 5:  # 至少5次预测才计算
            accuracy[model] = stats["correct"] / stats["total"]

    return accuracy if accuracy else None


if __name__ == "__main__":
    print("=" * 50)
    print("高级投票系统测试")
    print("=" * 50)

    # 创建投票系统
    voting_system = create_voting_system()

    # 测试1: 正常情况（模型一致）
    print("\n1. 正常情况（模型一致）:")
    predictions = {
        "MiniMax M2.7": 65,
        "Nemotron 3 Super": 60,
        "Llama 3.3 70B": 70,
        "GLM-5.1": 68,
    }
    result = voting_system.vote(predictions)
    print(f"   最终预测: {result['final_prediction']:.2f}")
    print(f"   置信度: {result['confidence']:.2f}")
    print(f"   分歧程度: {result['disagreement']:.2f}")
    print(f"   需要审查: {result['need_review']}")

    # 测试2: 分歧大
    print("\n2. 分歧大:")
    predictions = {
        "MiniMax M2.7": 30,
        "Nemotron 3 Super": 60,
        "Llama 3.3 70B": 90,
        "GLM-5.1": 75,
    }
    result = voting_system.vote(predictions)
    print(f"   最终预测: {result['final_prediction']:.2f}")
    print(f"   置信度: {result['confidence']:.2f}")
    print(f"   分歧程度: {result['disagreement']:.2f}")
    print(f"   需要审查: {result['need_review']}")

    # 测试3: 有异常值
    print("\n3. 有异常值:")
    predictions = {
        "MiniMax M2.7": 50,
        "Nemotron 3 Super": 55,
        "Llama 3.3 70B": 5,  # 异常低
        "GLM-5.1": 52,
    }
    result = voting_system.vote(predictions)
    print(f"   最终预测: {result['final_prediction']:.2f}")
    print(f"   置信度: {result['confidence']:.2f}")
    print(f"   异常值: {result['outliers']}")
    print(f"   模型权重: {result['model_weights']}")

    print("\n✅ 高级投票系统测试完成")
