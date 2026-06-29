#!/usr/bin/env python3
"""
配置中心模块
- 统一配置管理
- 配置验证
- 动态更新
"""
import os
import json
from pathlib import Path
from polystrat_logger import log, log_error

# ============================================================
# 基础路径常量（统一管理，消除重复定义）
# ============================================================
BASE_DIR = Path("/root/.hermes/profiles/life")
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "home/.hermes/polymarket_bot/logs"
SCRIPTS_DIR = BASE_DIR / "scripts"
ENV_FILE = BASE_DIR / ".env"

# Log files
TRADE_LOG = LOG_DIR / "polystrat_trades.json"
ALERT_LOG = LOG_DIR / "alerts.json"
PERF_LOG = LOG_DIR / "performance.json"
KEY_AUDIT_LOG = LOG_DIR / "key_audit.log"
SEEN_KEYS_FILE = LOG_DIR / "seen_keys.json"
TRADE_HISTORY_FILE = LOG_DIR / "trade_history.json"
SETTLEMENT_LOG = LOG_DIR / "settlement_log.json"
DAILY_REPORT_FILE = LOG_DIR / "daily_pnl_simple.json"

# Config
CONFIG_DIR = DATA_DIR / "config"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = CONFIG_DIR / "polystrat_config.json"

# State files
CIRCUIT_BREAKER_STATE = DATA_DIR / "circuit_breaker.json"
TRADE_LIMITS_STATE = DATA_DIR / "trade_limits.json"
OPTIMIZATION_CONFIG = DATA_DIR / "optimization_config.json"

# Cache directories
MARKET_MICROSTRUCTURE_CACHE = DATA_DIR / "market_microstructure"
VOLUME_CACHE_DIR = DATA_DIR / "volume_cache"
AIRDROP_CACHE_DIR = DATA_DIR / "airdrop_cache"
ARBITRAGE_CACHE_DIR = DATA_DIR / "arbitrage_cache"
KALSHI_CACHE_DIR = DATA_DIR / "kalshi_cache"
MANIFOLD_CACHE_DIR = DATA_DIR / "manifold_cache"
ONCHAIN_CACHE_DIR = DATA_DIR / "onchain_cache"
NEWS_CACHE_DIR = DATA_DIR / "news_cache"
SERPAPI_USAGE_FILE = DATA_DIR / "serpapi_usage.json"

# ML model
ML_MODEL_PATH = DATA_DIR / "ml_model.pkl"

# Kong score
KONG_SCORE_DIR = DATA_DIR / "kong_score"
TP_MANAGER_DIR = DATA_DIR / "tp_manager"
POLYSTRAT_DIR = DATA_DIR / "polystrat"

# Polkadot
WHALE_WATCH_SEEN = DATA_DIR / "whale_watch_seen.json"

# ============================================================
# API 常量（统一管理）
# ============================================================
GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"
CLOB_BASE = CLOB_API

# 创建所有目录
for _dir in [DATA_DIR, LOG_DIR, SCRIPTS_DIR, CONFIG_DIR,
             MARKET_MICROSTRUCTURE_CACHE, VOLUME_CACHE_DIR,
             AIRDROP_CACHE_DIR, ARBITRAGE_CACHE_DIR, KALSHI_CACHE_DIR,
             MANIFOLD_CACHE_DIR, ONCHAIN_CACHE_DIR, NEWS_CACHE_DIR,
             KONG_SCORE_DIR, TP_MANAGER_DIR, POLYSTRAT_DIR]:
    _dir.mkdir(parents=True, exist_ok=True)

# 默认配置
DEFAULT_CONFIG = {
    "version": "3.7",
    "mode": "dry_run",  # dry_run / live
    
    # 交易配置
    "trading": {
        "bet_amount": 2.0,
        "edge_threshold": 0.04,
        "max_trades_per_run": 3,
        "min_liquidity": 5000,
        "dedup_hours": 24
    },
    
    # 信号权重
    "signal_weights": {
        "llm": 0.40,
        "sentiment": 0.20,
        "onchain": 0.20,
        "ml": 0.20
    },
    
    # 风险管理
    "risk": {
        "max_position_pct": 0.05,
        "max_total_position": 0.30,
        "max_same_category": 0.20,
        "stop_loss_threshold": -0.10
    },
    
    # API 配置
    "api": {
        "timeout": 15,
        "max_retries": 3,
        "retry_delay": 1
    },
    
    # 定时任务
    "schedule": {
        "trading_cron": "0 1,5,9,13,17,21 * * *",
        "airdrop_cron": "0 10 * * *",
        "whale_monitor_cron": "0 */2 * * *"
    },
    
    # 通知配置
    "notification": {
        "enabled": True,
        "on_trade": True,
        "on_error": True,
        "on_alert": True
    }
}

def load_config():
    """
    加载配置
    
    Returns:
        dict: 配置字典
    """
    try:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
            # 合并默认配置（处理新增字段）
            return merge_config(DEFAULT_CONFIG, config)
        else:
            # 首次运行，保存默认配置
            save_config(DEFAULT_CONFIG)
            return DEFAULT_CONFIG.copy()
    except Exception as e:
        log_error("config", e, "加载配置失败，使用默认配置")
        return DEFAULT_CONFIG.copy()

def save_config(config):
    """
    保存配置
    
    Args:
        config: 配置字典
    """
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        log.info("配置已保存")
    except Exception as e:
        log_error("config", e, "保存配置失败")

def merge_config(default, custom):
    """
    合并配置（保留自定义值，补充默认值）
    
    Args:
        default: 默认配置
        custom: 自定义配置
    
    Returns:
        dict: 合并后的配置
    """
    result = default.copy()
    
    for key, value in custom.items():
        if key in result:
            if isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = merge_config(result[key], value)
            else:
                result[key] = value
        else:
            result[key] = value
    
    return result

def get_config_value(key_path, default=None):
    """
    获取配置值
    
    Args:
        key_path: 键路径，如 "trading.bet_amount"
        default: 默认值
    
    Returns:
        配置值
    """
    config = load_config()
    
    keys = key_path.split(".")
    value = config
    
    for key in keys:
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return default
    
    return value

def update_config_value(key_path, value):
    """
    更新配置值
    
    Args:
        key_path: 键路径
        value: 新值
    """
    config = load_config()
    
    keys = key_path.split(".")
    target = config
    
    for key in keys[:-1]:
        if key not in target:
            target[key] = {}
        target = target[key]
    
    target[keys[-1]] = value
    save_config(config)

def validate_config(config):
    """
    验证配置
    
    Args:
        config: 配置字典
    
    Returns:
        tuple: (是否有效, 错误信息)
    """
    # 检查必需字段
    required = ["version", "mode", "trading", "signal_weights", "risk"]
    for field in required:
        if field not in config:
            return False, f"缺少必需字段: {field}"
    
    # 检查权重总和
    weights = config.get("signal_weights", {})
    total_weight = sum(weights.values())
    if abs(total_weight - 1.0) > 0.01:
        return False, f"信号权重总和应为1.0，实际为{total_weight:.4f}"
    
    # 检查模式
    if config.get("mode") not in ["dry_run", "live"]:
        return False, f"无效模式: {config.get('mode')}"
    
    return True, None

def format_config_report():
    """
    格式化配置报告
    
    Returns:
        str: 报告内容
    """
    config = load_config()
    
    lines = []
    lines.append("⚙️ PolyStrat 配置报告")
    lines.append("=" * 50)
    lines.append(f"版本: {config.get('version')}")
    lines.append(f"模式: {config.get('mode')}")
    lines.append("")
    
    lines.append("💰 交易配置:")
    trading = config.get("trading", {})
    lines.append(f"  下注金额: ${trading.get('bet_amount')}")
    lines.append(f"  优势阈值: {trading.get('edge_threshold'):.1%}")
    lines.append(f"  最大交易数: {trading.get('max_trades_per_run')}")
    lines.append("")
    
    lines.append("⚖️ 信号权重:")
    weights = config.get("signal_weights", {})
    for name, weight in weights.items():
        lines.append(f"  {name}: {weight:.1%}")
    lines.append("")
    
    lines.append("🛡️ 风险管理:")
    risk = config.get("risk", {})
    lines.append(f"  单笔最大: {risk.get('max_position_pct'):.1%}")
    lines.append(f"  总仓位最大: {risk.get('max_total_position'):.1%}")
    lines.append(f"  止损阈值: {risk.get('stop_loss_threshold'):.1%}")
    
    return "\n".join(lines)

if __name__ == "__main__":
    print("=" * 50)
    print("配置中心测试")
    print("=" * 50)
    
    # 加载配置
    config = load_config()
    print(f"\n配置加载成功: {len(config)} 个顶级字段")
    
    # 验证配置
    is_valid, error = validate_config(config)
    print(f"配置验证: {'✅ 有效' if is_valid else f'❌ {error}'}")
    
    # 获取配置值
    bet_amount = get_config_value("trading.bet_amount")
    print(f"下注金额: {bet_amount}")
    
    # 打印报告
    print(f"\n{format_config_report()}")
    
    print("\n✅ 配置中心测试完成")
