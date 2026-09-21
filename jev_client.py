#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JEV System 1 统一客户端
========================

职责（且仅此三件）：
1. 传输：封装 typesafe.ai systemone 单次调用。不重试、不缓存（缓存是调用方的语义职责）
2. 健康熔断：连续失败后开放冷却期，防止 API 故障拖垮主循环 220s 扫描预算
3. 统计：调用/失败计数，供运行报告输出可观测性

语义判断（score 归一化、阻断阈值等）留在调用方。
所有调用方对 JevUnavailableError 统一 fail-open，不重试。

日期: 2026-09-21
"""

import os
import time
import threading
import requests

# ============ 配置 ============

JEV_API_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL = "jev-latest"

_FAILURE_THRESHOLD = 3      # 连续失败 N 次后熔断
_COOLDOWN_SECONDS = 300.0   # 熔断开放时长（秒）
ENV_FILE = "/root/.hermes/.env"

# ============ 异常 ============


class JevUnavailableError(Exception):
    """JEV 不可用。调用方统一 fail-open。

    reason ∈ {"no_key", "circuit_open", "http_error", "network", "bad_response"}
    """

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}")


# ============ key 管理 ============

_env_file_key_cache = None  # ENV_FILE 解析结果缓存；env 变量不缓存，保证测试可控


def _get_api_key() -> str:
    """env 优先（每次读），否则解析 ENV_FILE（结果缓存）。"""
    global _env_file_key_cache
    k = os.environ.get("TYPESAFE_API_KEY", "")
    if k:
        return k
    if _env_file_key_cache is not None:
        return _env_file_key_cache
    _env_file_key_cache = ""
    if os.path.exists(ENV_FILE):
        try:
            with open(ENV_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("TYPESAFE_API_KEY="):
                        _env_file_key_cache = line.strip().split("=", 1)[1]
                        break
        except Exception:
            pass
    return _env_file_key_cache


# ============ 熔断与统计状态（模块级单例，进程生命周期内有效） ============

_LOCK = threading.Lock()
_state = {
    "consecutive_failures": 0,
    "open_until": 0.0,  # time.monotonic() 时基，免疫墙钟跳变
    "calls": 0,
    "successes": 0,
    "failures": 0,
    "failures_by_reason": {},
    "last_error": "",
}


def _record_failure(reason: str, detail: str) -> None:
    """调用方已持有 _LOCK。"""
    _state["failures"] += 1
    _state["consecutive_failures"] += 1
    _state["failures_by_reason"][reason] = _state["failures_by_reason"].get(reason, 0) + 1
    _state["last_error"] = f"{reason}: {detail}"[:200]
    if _state["consecutive_failures"] >= _FAILURE_THRESHOLD:
        _state["open_until"] = time.monotonic() + _COOLDOWN_SECONDS


# ============ 对外接口 ============


def jev_ask(state: str, questions: dict, timeout: float = 3.0) -> dict:
    """单次询问 JEV。

    成功: HTTP 200 且 JSON 可解析 → 返回 answers dict；
          answers 缺失/非 dict → 返回 {}（传输层健康，语义默认值由调用方兜底，
          不计失败、不触发熔断——熔断防的是"API 挂了拖垮循环"，不防"模型答非所问"）
    失败: 抛 JevUnavailableError，不重试。

    计数规则:
      - circuit_open / no_key: 零网络开销，不计 calls
      - no_key 是确定性配置态，不计失败、不触发熔断（只记 last_error）
      - http_error / network / bad_response: 计 calls + 失败，驱动熔断
    """
    with _LOCK:
        if _state["open_until"] > time.monotonic():
            remaining = _state["open_until"] - time.monotonic()
            raise JevUnavailableError("circuit_open", f"熔断冷却中，剩余 {remaining:.0f}s")

    api_key = _get_api_key()
    if not api_key:
        with _LOCK:
            _state["last_error"] = "no_key: TYPESAFE_API_KEY 未配置"
        raise JevUnavailableError("no_key", "TYPESAFE_API_KEY 未配置")

    with _LOCK:
        _state["calls"] += 1

    payload = {"model": JEV_MODEL, "state": state, "questions": questions}
    try:
        resp = requests.post(
            JEV_API_ENDPOINT,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=timeout,
        )
    except Exception as e:
        detail = type(e).__name__
        with _LOCK:
            _record_failure("network", detail)
        raise JevUnavailableError("network", detail)

    if resp.status_code != 200:
        detail = f"HTTP {resp.status_code}"
        with _LOCK:
            _record_failure("http_error", detail)
        raise JevUnavailableError("http_error", detail)

    try:
        data = resp.json()
    except Exception as e:
        detail = f"JSON解析失败: {type(e).__name__}"
        with _LOCK:
            _record_failure("bad_response", detail)
        raise JevUnavailableError("bad_response", detail)

    answers = data.get("answers", {})
    if not isinstance(answers, dict):
        answers = {}

    with _LOCK:
        _state["successes"] += 1
        _state["consecutive_failures"] = 0
    return answers


def get_stats() -> dict:
    """健康统计快照（供运行报告输出）。"""
    with _LOCK:
        remaining = max(0.0, _state["open_until"] - time.monotonic())
        return {
            "calls": _state["calls"],
            "successes": _state["successes"],
            "failures": _state["failures"],
            "failures_by_reason": dict(_state["failures_by_reason"]),
            "consecutive_failures": _state["consecutive_failures"],
            "circuit_open": remaining > 0,
            "cooldown_remaining": round(remaining, 1),
            "last_error": _state["last_error"],
        }


def reset() -> None:
    """清零熔断与统计。测试隔离专用。"""
    global _env_file_key_cache
    with _LOCK:
        _state.update({
            "consecutive_failures": 0,
            "open_until": 0.0,
            "calls": 0,
            "successes": 0,
            "failures": 0,
            "failures_by_reason": {},
            "last_error": "",
        })
    _env_file_key_cache = None
