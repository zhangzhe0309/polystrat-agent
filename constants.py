#!/usr/bin/env python3
"""
全局常量模块
- 统一管理基础路径
- 消除重复定义
- 避免循环导入
"""
import os
from pathlib import Path

# ============================================================
# 基础路径常量
# ============================================================
BASE_DIR = Path("/root/.hermes/profiles/life")
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "home/.hermes/polymarket_bot/logs"
SCRIPTS_DIR = BASE_DIR / "scripts"
ENV_FILE = BASE_DIR / ".env"

# 确保目录存在（惰性创建，不在导入时执行）
def ensure_dirs():
    """确保必要的目录存在"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================
# 交易相关常量
# ============================================================
DEFAULT_BALANCE = 1000.0

# ============================================================
# 文件路径常量
# ============================================================
TRADE_LOG = LOG_DIR / "polystrat_trades.json"
ALERT_LOG = LOG_DIR / "alerts.json"
PERF_LOG = LOG_DIR / "performance.json"
KEY_AUDIT_LOG = LOG_DIR / "key_audit.log"
SEEN_KEYS_FILE = LOG_DIR / "seen_keys.json"
TRADE_HISTORY_FILE = LOG_DIR / "trade_history.json"
SETTLEMENT_LOG = LOG_DIR / "settlement_log.json"
