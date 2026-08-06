#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Meta Kats 核心算法提炼与顶级量化升级版 (纯 Python + NumPy)
适合 961MB VPS 环境，零重依赖 (免 PyTorch/Statsmodels)，内存占用 < 5MB。

经过异构大模型 Code Review 优化:
1. 包含对数收益率 (Log Returns) 转换，消除价格量级干扰
2. 标准 R/S (Rescaled Range) 重标极差 Hurst 算法，金融定量更严谨
3. NaN / Inf 异常过滤防崩溃 (Defensive Data Cleaning)
4. 样本无偏估计 (ddof=1) 置信区间套利

用于:
- Polymarket 赔率变盘检测 (CUSUM Change Point)
- 加密货币/链上标的趋势形态识别 (Hurst Exponent)
- 极端插针/假突破风控 (Outlier Detection)
- 赔率置信区间套利 (Probability Confidence Interval)
"""

import math
import json
import numpy as np
from typing import List, Dict, Any, Union

class TimeSeriesQuant:
    """
    轻量级时间序列分析核心库 (Meta Kats 顶级优化版)
    """

    @staticmethod
    def _clean_data(series: Union[List[float], np.ndarray]) -> np.ndarray:
        """数据清洗与防崩溃保护 (过滤 NaN 和 Inf)"""
        arr = np.array(series, dtype=float)
        valid_mask = ~np.isnan(arr) & ~np.isinf(arr)
        return arr[valid_mask]

    @classmethod
    def detect_change_points(
        cls, 
        series: List[float], 
        threshold: float = 2.5, 
        drift: float = 0.5,
        use_log_returns: bool = True
    ) -> Dict[str, Any]:
        """
        1. CUSUM (累积和) 变盘/趋势拐点检测算法 (支持对数收益率模式)
        :param series: 价格/赔率序列 (按时间升序)
        :param threshold: 触发变盘告警的标准差倍数 (默认 2.5)
        :param drift: 允许的平稳漂移量
        :param use_log_returns: 是否使用对数收益率 (推荐 True)
        :return: 变盘索引、变盘方向、CUSUM值
        """
        data = cls._clean_data(series)
        if len(data) < 5:
            return {"has_change": False, "change_points": [], "message": "有效数据量不足 (需>=5)"}

        # 如果开启对数收益率模式且全为正数，转换计算 log returns
        if use_log_returns and np.all(data > 0) and len(data) >= 6:
            calc_series = np.diff(np.log(data))
            offset = 1 # 收益率序列比原始序列少 1
        else:
            calc_series = data
            offset = 0

        mean_val = np.mean(calc_series)
        std_val = np.std(calc_series, ddof=1) if len(calc_series) > 1 else 0

        if std_val == 0 or np.isnan(std_val):
            return {"has_change": False, "change_points": [], "message": "序列无波动"}

        # 标准化序列
        normalized = (calc_series - mean_val) / std_val

        pos_cusum = np.zeros(len(calc_series))
        neg_cusum = np.zeros(len(calc_series))

        change_indices = []
        directions = []

        for i in range(1, len(calc_series)):
            pos_cusum[i] = max(0, pos_cusum[i-1] + normalized[i] - drift)
            neg_cusum[i] = max(0, neg_cusum[i-1] - normalized[i] - drift)

            orig_idx = i + offset

            if pos_cusum[i] > threshold:
                change_indices.append(orig_idx)
                directions.append("UP")
                pos_cusum[i] = 0  # 重置

            elif neg_cusum[i] > threshold:
                change_indices.append(orig_idx)
                directions.append("DOWN")
                neg_cusum[i] = 0  # 重置

        latest_change = None
        if change_indices:
            latest_idx = change_indices[-1]
            latest_change = {
                "index": latest_idx,
                "direction": directions[-1],
                "price": float(data[latest_idx]),
                "pos_score": round(float(pos_cusum[-1]), 4),
                "neg_score": round(float(neg_cusum[-1]), 4)
            }

        return {
            "has_change": len(change_indices) > 0,
            "change_count": len(change_indices),
            "latest_change": latest_change,
            "change_points": [{"index": idx, "dir": d} for idx, d in zip(change_indices, directions)]
        }

    @classmethod
    def calculate_hurst(cls, series: List[float], max_lag: int = 20) -> Dict[str, Any]:
        """
        2. 标准 R/S (Rescaled Range) 重标极差 Hurst 指数计算器
        :param series: 价格/赔率时间序列
        :param max_lag: 最大滞后阶数
        :return: Hurst 指数 (0.5 = 随机游走, > 0.5 强趋势/动量, < 0.5 均值回归/震荡)
        """
        ts = cls._clean_data(series)
        if len(ts) < 15:
            return {"hurst": 0.5, "regime": "UNKNOWN", "message": "样本数量不足 (需要>=15)"}

        # 使用对数收益率计算差分
        if np.all(ts > 0):
            returns = np.diff(np.log(ts))
        else:
            returns = np.diff(ts)

        N = len(returns)
        if N < 10:
            return {"hurst": 0.5, "regime": "UNKNOWN"}

        # 尝试不同的子窗口长度
        max_k = min(max_lag, N // 2)
        lags = range(4, max_k + 1)

        rs_values = []
        valid_lags = []

        for lag in lags:
            # 切分多个长度为 lag 的子序列
            num_splits = N // lag
            if num_splits < 1:
                continue

            rs_sub = []
            for i in range(num_splits):
                sub_seq = returns[i * lag : (i + 1) * lag]
                mean_sub = np.mean(sub_seq)
                # 累积离差
                cum_deviations = np.cumsum(sub_seq - mean_sub)
                # 极差 R
                R = np.max(cum_deviations) - np.min(cum_deviations)
                # 标准差 S
                S = np.std(sub_seq, ddof=1)

                if S > 1e-8:
                    rs_sub.append(R / S)

            if rs_sub:
                rs_values.append(np.mean(rs_sub))
                valid_lags.append(lag)

        if len(valid_lags) < 2:
            return {"hurst": 0.5, "regime": "RANDOM_WALK"}

        # 线性拟合 log(R/S) = Hurst * log(lag) + c
        log_lags = np.log(valid_lags)
        log_rs = np.log(rs_values)

        poly = np.polyfit(log_lags, log_rs, 1)
        hurst_val = round(float(poly[0]), 4)
        # 限制在 [0, 1] 合理物理区间
        hurst_val = max(0.0, min(1.0, hurst_val))

        if hurst_val > 0.55:
            regime = "TRENDING"        # 强趋势跟随
        elif hurst_val < 0.45:
            regime = "MEAN_REVERTING"  # 均值回归 / 震荡套利
        else:
            regime = "RANDOM_WALK"     # 随机游走 / 无明确方向

        return {
            "hurst": hurst_val,
            "regime": regime,
            "interpretation": f"Hurst={hurst_val:.4f} -> {regime} 模式"
        }

    @classmethod
    def detect_outliers(cls, series: List[float], z_threshold: float = 2.5) -> Dict[str, Any]:
        """
        3. 极端插针与异常离群点检测 (Outlier Detection)
        :param series: 价格/赔率序列
        :param z_threshold: Z-Score 判定阈值
        :return: 异常点位置、插针数值
        """
        arr = cls._clean_data(series)
        if len(arr) < 5:
            return {"has_outliers": False, "outliers": []}

        mean = np.mean(arr)
        std = np.std(arr, ddof=1) if len(arr) > 1 else 0

        if std == 0 or np.isnan(std):
            return {"has_outliers": False, "outliers": []}

        z_scores = (arr - mean) / std
        outlier_indices = np.where(np.abs(z_scores) > z_threshold)[0]

        outliers = []
        for idx in outlier_indices:
            outliers.append({
                "index": int(idx),
                "value": float(arr[idx]),
                "z_score": round(float(z_scores[idx]), 2),
                "type": "SPIKE_HIGH" if z_scores[idx] > 0 else "SPIKE_LOW"
            })

        return {
            "has_outliers": len(outliers) > 0,
            "outliers_count": len(outliers),
            "outliers": outliers
        }

    @classmethod
    def calculate_confidence_interval(
        cls, 
        series: List[float], 
        window: int = 10, 
        num_std: float = 2.0
    ) -> Dict[str, Any]:
        """
        4. 概率与赔率置信区间计算 (Confidence Bounds for Polymarket Arbitrage)
        :param series: 时间序列
        :param window: 滚动窗口大小
        :param num_std: 置信度标准差倍数 (2.0 对应 95% 置信区间)
        :return: 当前值的 Upper / Lower 置信边界与偏离度
        """
        arr = cls._clean_data(series)
        if len(arr) == 0:
            return {"signal": "NO_DATA", "current_val": 0.0}

        if len(arr) < window:
            window = len(arr)

        data = arr[-window:]
        current_val = float(data[-1])
        mean_val = float(np.mean(data))
        std_val = float(np.std(data, ddof=1)) if len(data) > 1 else 0.0

        upper_bound = mean_val + num_std * std_val
        lower_bound = mean_val - num_std * std_val

        # 偏离信号
        signal = "NEUTRAL"
        if current_val > upper_bound:
            signal = "OVERBOUGHT_UPPER"  # 超买/高于置信上限
        elif current_val < lower_bound:
            signal = "OVERSOLD_LOWER"    # 超卖/低于置信下限

        return {
            "current_val": round(current_val, 4),
            "mean": round(mean_val, 4),
            "upper_bound": round(upper_bound, 4),
            "lower_bound": round(lower_bound, 4),
            "num_std": num_std,
            "signal": signal,
            "deviation_pct": round(((current_val - mean_val) / mean_val * 100) if mean_val != 0 else 0, 2)
        }

# ================= 单元测试与测试用例 =================
if __name__ == "__main__":
    print("🚀 运行 Meta Kats 顶级量化升级版单元测试...\n")

    # 模拟真实 Polymarket 异动数据 (包含 NaN 噪点测试防崩)
    mock_odds = [0.45, 0.46, np.nan, 0.45, 0.44, 0.45, 0.47, 0.52, 0.61, 0.73, 0.78, 0.76, 0.75, 0.74, 0.76, 0.77]

    # 1. 变盘检测
    cp_res = TimeSeriesQuant.detect_change_points(mock_odds, threshold=2.0)
    print("1. 【变盘/趋势拐点检测 (Log Returns 模式)】:")
    print(json.dumps(cp_res, ensure_ascii=False, indent=2))

    # 2. R/S Hurst 指数
    hurst_res = TimeSeriesQuant.calculate_hurst(mock_odds)
    print("\n2. 【标准 R/S Hurst 趋势/回归状态】:")
    print(json.dumps(hurst_res, ensure_ascii=False, indent=2))

    # 3. 离群插针检测
    outlier_res = TimeSeriesQuant.detect_outliers(mock_odds, z_threshold=2.0)
    print("\n3. 【异常插针/离群点检测 (带 NaN 自动过滤)】:")
    print(json.dumps(outlier_res, ensure_ascii=False, indent=2))

    # 4. 置信区间套利判定
    ci_res = TimeSeriesQuant.calculate_confidence_interval(mock_odds, window=5)
    print("\n4. 【置信区间套利评估】:")
    print(json.dumps(ci_res, ensure_ascii=False, indent=2))
