#!/usr/bin/env python3
"""
PolyStrat 统一日志模块
- 文件日志 + 控制台输出
- 日志轮转（最大5MB，保留3个备份）
- 分级日志（DEBUG/INFO/WARNING/ERROR）
"""
import logging
import os
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path
from datetime import datetime

# 2026-06-29 修复循环导入：LOG_DIR 在本地直接定义，不引用 config_center
# (原代码从 config_center import LOG_DIR 导致 news_search.py 等模块加载时循环崩溃)
LOG_DIR = Path("/root/.hermes/polymarket_bot/polystrat/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

# 日志文件
LOG_FILE = LOG_DIR / "polystrat.log"

def sanitize_log_message(message):
    """脱敏日志消息中的敏感信息"""
    if not isinstance(message, str):
        message = str(message)
    
    # 脱敏 API Key
    message = re.sub(r'(api_key|apikey|token|secret|password|private_key)\s*[=:]\s*[^\s,;]+', 
                     r'\1=***', message, flags=re.IGNORECASE)
    
    # 脱敏完整的密钥值
    message = re.sub(r'nvapi-[a-zA-Z0-9_-]{20,}', 'nvapi-***', message)
    message = re.sub(r'sk-[a-zA-Z0-9_-]{20,}', 'sk-***', message)
    message = re.sub(r'0x[a-fA-F0-9]{40,}', '0x***', message)
    
    return message

def get_logger(name="polystrat"):
    """
    获取日志器
    
    Args:
        name: 日志器名称
    
    Returns:
        logging.Logger: 配置好的日志器
    """
    logger = logging.getLogger(name)
    
    # 避免重复添加 handler
    if logger.handlers:
        return logger
    
    logger.setLevel(logging.DEBUG)
    
    # 文件 handler（轮转：5MB/文件，保留3个备份）
    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=5 * 1024 * 1024,  # 5MB
        backupCount=3,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    
    # 控制台 handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    # 格式
    file_format = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_format = logging.Formatter(
        '%(levelname)-8s | %(message)s'
    )
    
    # 添加脱敏过滤器
    class SanitizeFilter(logging.Filter):
        def filter(self, record):
            record.msg = sanitize_log_message(record.msg)
            if record.args:
                record.args = tuple(sanitize_log_message(str(a)) if isinstance(a, str) else a for a in record.args)
            return True
    
    sanitize_filter = SanitizeFilter()
    file_handler.addFilter(sanitize_filter)
    console_handler.addFilter(sanitize_filter)
    
    file_handler.setFormatter(file_format)
    console_handler.setFormatter(console_format)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

# 默认日志器
log = get_logger()

def log_trade(trade_info):
    """记录交易到专用日志"""
    trade_logger = get_logger("trade")
    trade_logger.info(f"TRADE: {trade_info}")

def log_error(module, error, context=""):
    """记录错误"""
    log.error(f"[{module}] {error} {context}")

def log_api_call(source, query, status, count=0):
    """记录 API 调用"""
    if status == "success":
        log.info(f"[API] {source}: query='{query[:30]}', results={count}")
    else:
        log.warning(f"[API] {source}: query='{query[:30]}', status={status}")

def log_performance(operation, duration, details=""):
    """记录性能"""
    if duration > 5:
        log.warning(f"[PERF] {operation}: {duration:.2f}s {details}")
    else:
        log.info(f"[PERF] {operation}: {duration:.2f}s {details}")

if __name__ == "__main__":
    # 测试日志系统
    print("=== 日志系统测试 ===")
    
    log.debug("这是 DEBUG 消息（只在文件中）")
    log.info("这是 INFO 消息")
    log.warning("这是 WARNING 消息")
    log.error("这是 ERROR 消息")
    
    log_trade({"market": "Test", "amount": 2.0, "direction": "Yes"})
    log_error("test_module", "测试错误", "context info")
    log_api_call("gnews", "Bitcoin", "success", 5)
    log_performance("search_news", 6.5, "慢查询")
    
    print(f"\n日志文件: {LOG_FILE}")
    print(f"文件大小: {LOG_FILE.stat().st_size} bytes")
    print("\n✅ 日志系统测试通过")
