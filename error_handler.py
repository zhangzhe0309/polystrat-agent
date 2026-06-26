#!/usr/bin/env python3
"""
统一异常处理模块
- 全局异常捕获
- 错误分类
- 自动恢复
"""
import sys
import traceback
from datetime import datetime, timezone
from functools import wraps
from polystrat_logger import log, log_error

# 错误分类
ERROR_CATEGORIES = {
    "network": ["ConnectionError", "Timeout", "HTTPError"],
    "api": ["APIError", "RateLimitError", "AuthError"],
    "data": ["JSONDecodeError", "KeyError", "ValueError"],
    "system": ["MemoryError", "OSError", "PermissionError"],
}

def categorize_error(error):
    """分类错误"""
    error_type = type(error).__name__
    
    for category, types in ERROR_CATEGORIES.items():
        if error_type in types:
            return category
    
    return "unknown"

def safe_execute(func, *args, default=None, retries=1, **kwargs):
    """
    安全执行函数
    
    Args:
        func: 要执行的函数
        *args: 函数参数
        default: 失败时的默认值
        retries: 重试次数
        **kwargs: 关键字参数
    
    Returns:
        函数返回值或默认值
    """
    last_error = None
    
    for attempt in range(retries):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_error = e
            category = categorize_error(e)
            
            if attempt < retries - 1:
                log.warning(f"[{category}] {func.__name__} 失败 (尝试 {attempt + 1}/{retries}): {e}")
            else:
                log_error(func.__name__, e, f"最终失败 (类别: {category})")
    
    return default

def error_handler(func):
    """
    错误处理装饰器
    
    Usage:
        @error_handler
        def my_function():
            ...
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            category = categorize_error(e)
            log_error(func.__name__, e, f"类别: {category}")
            
            # 根据类别决定是否重新抛出
            if category in ["system", "unknown"]:
                raise
            
            return None
    return wrapper

def async_error_handler(func):
    """
    异步错误处理装饰器
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            category = categorize_error(e)
            log_error(func.__name__, e, f"类别: {category}")
            
            if category in ["system", "unknown"]:
                raise
            
            return None
    return wrapper

class ErrorHandler:
    """错误处理器"""
    
    def __init__(self):
        self.error_counts = {}
        self.last_errors = {}
    
    def handle(self, error, context="", reraise=False):
        """
        处理错误
        
        Args:
            error: 异常对象
            context: 上下文信息
            reraise: 是否重新抛出
        """
        error_type = type(error).__name__
        category = categorize_error(error)
        
        # 统计错误次数
        key = f"{category}:{error_type}"
        self.error_counts[key] = self.error_counts.get(key, 0) + 1
        self.last_errors[key] = {
            "error": str(error),
            "context": context,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
        # 记录日志
        log_error(context, error, f"类别: {category}, 累计: {self.error_counts[key]}")
        
        # 检查是否需要告警
        if self.error_counts[key] >= 10:
            log.warning(f"⚠️ 错误频繁: {key} 已发生 {self.error_counts[key]} 次")
        
        if reraise:
            raise
    
    def get_stats(self):
        """获取错误统计"""
        return {
            "error_counts": self.error_counts,
            "last_errors": self.last_errors,
            "total_errors": sum(self.error_counts.values()),
        }

# 全局错误处理器
error_handler_instance = ErrorHandler()

def handle_error(error, context="", reraise=False):
    """全局错误处理"""
    error_handler_instance.handle(error, context, reraise)

def get_error_stats():
    """获取错误统计"""
    return error_handler_instance.get_stats()

if __name__ == "__main__":
    print("=" * 50)
    print("统一异常处理测试")
    print("=" * 50)
    
    # 测试1: 安全执行
    print("\n1. 安全执行:")
    result = safe_execute(lambda: 1/0, default=0)
    print(f"   除零错误: 结果={result}")
    
    result = safe_execute(lambda: "success", default="fail")
    print(f"   正常执行: 结果={result}")
    
    # 测试2: 错误分类
    print("\n2. 错误分类:")
    errors = [
        ConnectionError("网络断开"),
        ValueError("值错误"),
        KeyError("键不存在"),
        MemoryError("内存不足"),
    ]
    for e in errors:
        category = categorize_error(e)
        print(f"   {type(e).__name__}: {category}")
    
    # 测试3: 错误统计
    print("\n3. 错误统计:")
    for e in errors:
        handle_error(e, "测试")
    
    stats = get_error_stats()
    print(f"   总错误: {stats['total_errors']}")
    for key, count in stats['error_counts'].items():
        print(f"   {key}: {count}")
    
    print("\n✅ 统一异常处理测试完成")
