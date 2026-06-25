#!/usr/bin/env python3
"""
机器学习优化模块（多模型集成）
- LogisticRegression
- RandomForest
- GradientBoosting
- KNN
- 加权平均集成
"""
import json
import os
import numpy as np
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pickle

# 交易记录文件
TRADE_LOG = Path("/root/.hermes/profiles/life/home/.hermes/polymarket_bot/logs/polystrat_trades.json")
MODEL_CACHE = Path("/root/.hermes/profiles/life/home/.hermes/polymarket_bot/logs/ml_model.pkl")

# 模型配置
MODELS = {
    "logistic": {
        "name": "LogisticRegression",
        "weight": 0.3,
        "class": "LogisticRegression",
        "params": {"max_iter": 100, "random_state": 42}
    },
    "random_forest": {
        "name": "RandomForest",
        "weight": 0.4,
        "class": "RandomForestClassifier",
        "params": {"n_estimators": 50, "max_depth": 5, "random_state": 42}
    },
    "gradient_boosting": {
        "name": "GradientBoosting",
        "weight": 0.2,
        "class": "GradientBoostingClassifier",
        "params": {"n_estimators": 50, "max_depth": 3, "random_state": 42}
    },
    "knn": {
        "name": "KNN",
        "weight": 0.1,
        "class": "KNeighborsClassifier",
        "params": {"n_neighbors": 5}
    }
}

def load_trade_data():
    """加载交易数据"""
    try:
        if TRADE_LOG.exists():
            with open(TRADE_LOG, 'r') as f:
                return json.load(f)
        return []
    except Exception as e:
        print(f"⚠️ 加载交易数据失败: {e}")
        return []

def extract_features(trades):
    """
    提取特征
    
    特征列表（只使用交易时可获取的信息）:
    1. llm_prob: LLM 预测概率（交易时已知）
    2. sentiment_score: 新闻情感分数（交易时已知）
    3. abs(edge): 优势绝对值（交易时已知）
    4. market_price: 市场价格（交易时已知）
    5. direction: 方向 (Yes=1, No=0)（交易时已知）
    6. amount: 下注金额（交易时已知）
    
    注意：不能使用 final_prob 或 confidence，这些是决策输出！
    使用决策输出作为特征会导致数据泄露。
    
    标签定义:
    - 1 = 已结算盈利 (result == "win")
    - 0 = 已结算亏损 (result == "lose")
    - 未结算交易: 排除（不参与训练）
    """
    features = []
    labels = []
    
    for trade in trades:
        result = trade.get("result", "")
        
        # 只用已结算的交易做训练数据
        if result not in ("win", "lose"):
            continue
        
        # 只使用交易时可获取的信息作为特征
        feature = [
            trade.get("llm_prob", 0.5),           # LLM 预测概率
            trade.get("sentiment_score", 0),       # 情感分数
            abs(trade.get("edge", 0)),             # 优势绝对值
            trade.get("market_price", 0.5),        # 市场价格
            1 if trade.get("direction") == "Yes" else 0,  # 方向
            trade.get("amount", 2),                # 金额
        ]
        
        label = 1 if result == "win" else 0
        
        features.append(feature)
        labels.append(label)
    
    return np.array(features), np.array(labels)

def train_model(model_class, params, features_scaled, labels):
    """
    训练单个模型
    """
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
    from sklearn.neighbors import KNeighborsClassifier
    
    model_map = {
        "LogisticRegression": LogisticRegression,
        "RandomForestClassifier": RandomForestClassifier,
        "GradientBoostingClassifier": GradientBoostingClassifier,
        "KNeighborsClassifier": KNeighborsClassifier
    }
    
    ModelClass = model_map.get(model_class)
    if not ModelClass:
        return None
    
    model = ModelClass(**params)
    model.fit(features_scaled, labels)
    return model

def train_ensemble_models(features, labels):
    """
    训练集成模型
    """
    from sklearn.preprocessing import StandardScaler
    
    # 标准化
    scaler = StandardScaler()
    features_scaled = scaler.fit_transform(features)
    
    # 训练各个模型
    trained_models = {}
    for model_key, model_config in MODELS.items():
        try:
            model = train_model(
                model_config["class"],
                model_config["params"],
                features_scaled,
                labels
            )
            if model:
                trained_models[model_key] = {
                    "model": model,
                    "weight": model_config["weight"],
                    "name": model_config["name"]
                }
                print(f"   ✅ {model_config['name']} 训练完成")
        except Exception as e:
            print(f"   ⚠️ {model_config['name']} 训练失败: {e}")
    
    return trained_models, scaler

def predict_ensemble(trained_models, scaler, features):
    """
    集成预测
    """
    features_scaled = scaler.transform([features])
    
    predictions = []
    total_weight = 0
    
    for model_key, model_info in trained_models.items():
        try:
            prob = model_info["model"].predict_proba(features_scaled)[0][1]
            weight = model_info["weight"]
            predictions.append(prob * weight)
            total_weight += weight
        except Exception as e:
            continue
    
    if total_weight > 0:
        return sum(predictions) / total_weight
    return 0.5

def save_model(trained_models, scaler):
    """保存模型"""
    try:
        MODEL_CACHE.parent.mkdir(parents=True, exist_ok=True)
        with open(MODEL_CACHE, 'wb') as f:
            pickle.dump({"models": trained_models, "scaler": scaler}, f)
        return True
    except Exception as e:
        print(f"⚠️ 保存模型失败: {e}")
        return False

def load_model():
    """加载模型"""
    try:
        if MODEL_CACHE.exists():
            with open(MODEL_CACHE, 'rb') as f:
                data = pickle.load(f)
            return data.get("models"), data.get("scaler")
        return None, None
    except Exception as e:
        print(f"⚠️ 加载模型失败: {e}")
        return None, None

def optimize_with_ml():
    """
    使用机器学习优化策略
    """
    trades = load_trade_data()
    
    if len(trades) < 10:
        return {
            "status": "数据不足",
            "message": f"只有 {len(trades)} 笔交易，需要至少 10 笔",
            "recommendation": "继续收集数据"
        }
    
    # 提取特征
    features, labels = extract_features(trades)
    
    # 如果没有已结算的交易，无法训练
    if len(features) < 2:
        return {
            "status": "数据不足",
            "message": f"只有 {len(features)} 条已结算交易，需要至少 2 条",
            "recommendation": "等待市场结算后重试"
        }
    
    # 训练集成模型
    print("   训练集成模型...")
    trained_models, scaler = train_ensemble_models(features, labels)
    
    if not trained_models:
        return {
            "status": "训练失败",
            "message": "没有模型训练成功",
            "recommendation": "检查数据质量"
        }
    
    # 保存模型
    save_model(trained_models, scaler)
    
    # 回测
    correct = 0
    total = 0
    total_pnl = 0
    
    for i, trade in enumerate(trades):
        if i >= len(features):  # 跳过未结算交易（已被 extract_features 过滤）
            break
        
        feature = features[i]
        ml_prob = predict_ensemble(trained_models, scaler, feature)
        
        result = trade.get("result", "")
        actual = labels[i]  # 使用真实标签
        predicted = 1 if ml_prob > 0.5 else 0
        
        if predicted == actual:
            correct += 1
        
        # 模拟盈亏
        edge = trade.get("edge", 0)
        amount = trade.get("amount", 2)
        if ml_prob > 0.6 and result == "win":
            total_pnl += amount * abs(edge)
        elif ml_prob > 0.6 and result == "lose":
            total_pnl -= amount * 0.1  # 亏损惩罚
        
        total += 1
    
    # 特征重要性（使用 RandomForest）
    feature_names = ["LLM概率", "情感分数", "优势", "市场价格", "方向", "金额"]
    if "random_forest" in trained_models:
        importance = trained_models["random_forest"]["model"].feature_importances_
        importance_ranking = sorted(zip(feature_names, importance), key=lambda x: -x[1])
    else:
        importance_ranking = [(name, 0) for name in feature_names]
    
    return {
        "status": "成功",
        "models_trained": len(trained_models),
        "model_names": [m["name"] for m in trained_models.values()],
        "backtest": {
            "total_trades": total,
            "correct_predictions": correct,
            "accuracy": correct / total if total > 0 else 0,
            "total_pnl": total_pnl
        },
        "feature_importance": importance_ranking,
        "recommendation": "集成模型可用"
    }

def get_ml_signal(llm_prob, sentiment_score, edge, market_price, direction, amount):
    """
    获取 ML 信号
    
    Args:
        llm_prob: LLM 预测概率
        sentiment_score: 情感分数
        edge: 优势
        market_price: 市场价格
        direction: 方向 (Yes/No)
        amount: 金额
    
    注意：不能使用 final_prob，这是决策输出，会导致数据泄露！
    """
    # 尝试加载缓存模型
    trained_models, scaler = load_model()
    
    # 如果没有缓存或交易数据更新了，重新训练
    if not trained_models:
        result = optimize_with_ml()
        if result["status"] == "成功":
            trained_models, scaler = load_model()
    
    if not trained_models:
        return {
            "ml_prob": 0.5,
            "confidence": 0.3,
            "recommendation": "数据不足",
            "models_used": 0
        }
    
    # 预测（6个特征，与 extract_features 一致）
    # 只使用交易时可获取的信息，不使用决策输出
    feature = [
        llm_prob, 
        sentiment_score, 
        abs(edge), 
        market_price, 
        1 if direction == "Yes" else 0, 
        amount,
    ]
    ml_prob = predict_ensemble(trained_models, scaler, feature)
    
    return {
        "ml_prob": ml_prob,
        "confidence": 0.7 if len(trained_models) >= 3 else 0.5,
        "recommendation": "买入" if ml_prob > 0.6 else "卖出" if ml_prob < 0.4 else "持有",
        "models_used": len(trained_models)
    }

if __name__ == "__main__":
    print("🤖 机器学习优化模块测试（多模型集成）")
    print("=" * 50)
    
    print("\n1. 策略优化:")
    result = optimize_with_ml()
    print(f"   状态: {result['status']}")
    
    if result["status"] == "成功":
        print(f"   训练模型数: {result['models_trained']}")
        print(f"   模型列表: {', '.join(result['model_names'])}")
        print(f"   回测准确率: {result['backtest']['accuracy']:.2%}")
        print(f"   总盈亏: {result['backtest']['total_pnl']:.2f}")
        
        print(f"\n2. 特征重要性:")
        for name, importance in result["feature_importance"][:3]:
            print(f"   {name}: {importance:.4f}")
    
    print(f"\n3. ML 信号测试:")
    signal = get_ml_signal(0.6, 0.3, 0.1, 0.5, "Yes", 2.0)
    print(f"   ML 概率: {signal['ml_prob']:.2f}")
    print(f"   使用模型: {signal['models_used']} 个")
    print(f"   建议: {signal['recommendation']}")
