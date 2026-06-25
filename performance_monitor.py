#!/usr/bin/env python3
"""
性能监控 + API限流保护模块
- API调用频率限制
- 性能指标收集
- 慢查询告警
"""
import time
import json
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import defaultdict
from polystrat_logger import log

# 性能日志文件
PERF_LOG = Path("/root/.hermes/profiles/life/home/.hermes/polymarket_bot/logs/performance.json")

class RateLimiter:
    """
    API 限流器
    使用令牌桶算法控制请求频率
    """
    
    def __init__(self, max_calls, time_window):
        """
        Args:
            max_calls: 时间窗口内最大调用次数
            time_window: 时间窗口（秒）
        """
        self.max_calls = max_calls
        self.time_window = time_window
        self.calls = []
        self.lock = threading.Lock()
    
    def can_call(self):
        """检查是否可以发起调用"""
        with self.lock:
            now = time.time()
            # 清理过期的调用记录
            self.calls = [t for t in self.calls if now - t < self.time_window]
            return len(self.calls) < self.max_calls
    
    def record_call(self):
        """记录一次调用"""
        with self.lock:
            self.calls.append(time.time())
    
    def wait_if_needed(self):
        """如果需要，等待直到可以调用"""
        while not self.can_call():
            time.sleep(0.1)
        self.record_call()
    
    def get_remaining(self):
        """获取剩余调用次数"""
        with self.lock:
            now = time.time()
            self.calls = [t for t in self.calls if now - t < self.time_window]
            return max(0, self.max_calls - len(self.calls))


# 全局限流器实例
RATE_LIMITERS = {
    "gamma_api": RateLimiter(max_calls=10, time_window=1),      # Gamma API: 10次/秒
    "gnews": RateLimiter(max_calls=10, time_window=1),           # GNews: 10次/秒
    "currents": RateLimiter(max_calls=10, time_window=1),        # Currents: 10次/秒
    "newsdata": RateLimiter(max_calls=5, time_window=1),         # NewsData: 5次/秒
    "nytimes": RateLimiter(max_calls=5, time_window=1),          # NYTimes: 5次/秒
    "serpapi": RateLimiter(max_calls=1, time_window=86400),      # SerpAPI: 1次/天
    "nvidia_llm": RateLimiter(max_calls=3, time_window=1),       # NVIDIA LLM: 3次/秒
}


class PerformanceMonitor:
    """
    性能监控器
    收集和分析性能指标
    """
    
    def __init__(self):
        self.metrics = defaultdict(list)
        self.lock = threading.Lock()
    
    def record(self, operation, duration, success=True, details=None):
        """记录性能指标"""
        with self.lock:
            self.metrics[operation].append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "duration": duration,
                "success": success,
                "details": details
            })
            
            # 慢查询告警
            if duration > 5:
                log.warning(f"[PERF] 慢查询: {operation} 耗时 {duration:.2f}s")
            elif duration > 10:
                log.error(f"[PERF] 超时: {operation} 耗时 {duration:.2f}s")
    
    def get_stats(self, operation=None):
        """获取性能统计"""
        with self.lock:
            if operation:
                ops = [operation] if operation in self.metrics else []
            else:
                ops = list(self.metrics.keys())
            
            stats = {}
            for op in ops:
                data = self.metrics[op]
                if not data:
                    continue
                
                durations = [d["duration"] for d in data]
                successes = [d for d in data if d["success"]]
                failures = [d for d in data if not d["success"]]
                
                stats[op] = {
                    "count": len(data),
                    "success_count": len(successes),
                    "failure_count": len(failures),
                    "avg_duration": sum(durations) / len(durations),
                    "max_duration": max(durations),
                    "min_duration": min(durations),
                    "success_rate": len(successes) / len(data) if data else 0
                }
            
            return stats
    
    def save_metrics(self):
        """保存性能指标到文件"""
        try:
            stats = self.get_stats()
            PERF_LOG.parent.mkdir(parents=True, exist_ok=True)
            PERF_LOG.write_text(json.dumps(stats, indent=2))
        except Exception as e:
            log.error(f"保存性能指标失败: {e}")
    
    def format_report(self):
        """格式化性能报告"""
        stats = self.get_stats()
        
        lines = []
        lines.append("📊 性能监控报告")
        lines.append("=" * 50)
        
        for op, data in sorted(stats.items()):
            lines.append(f"\n{op}:")
            lines.append(f"  调用次数: {data['count']}")
            lines.append(f"  成功率: {data['success_rate']:.1%}")
            lines.append(f"  平均耗时: {data['avg_duration']:.3f}s")
            lines.append(f"  最大耗时: {data['max_duration']:.3f}s")
            
            if data['failure_count'] > 0:
                lines.append(f"  ⚠️ 失败次数: {data['failure_count']}")
        
        return "\n".join(lines)


# 全局性能监控器
perf_monitor = PerformanceMonitor()


def rate_limited_call(api_name, func, *args, **kwargs):
    """
    带限流的 API 调用
    
    Args:
        api_name: API 名称（用于限流器）
        func: 调用函数
        *args, **kwargs: 函数参数
    
    Returns:
        函数返回值
    """
    # 获取限流器
    limiter = RATE_LIMITERS.get(api_name)
    
    if limiter:
        # 等待直到可以调用
        limiter.wait_if_needed()
    
    # 记录开始时间
    start_time = time.time()
    
    try:
        result = func(*args, **kwargs)
        duration = time.time() - start_time
        
        # 记录成功
        perf_monitor.record(api_name, duration, success=True)
        
        return result
        
    except Exception as e:
        duration = time.time() - start_time
        
        # 记录失败
        perf_monitor.record(api_name, duration, success=False, details=str(e))
        
        raise


def get_rate_limiter_status():
    """获取所有限流器状态"""
    status = {}
    for name, limiter in RATE_LIMITERS.items():
        status[name] = {
            "remaining": limiter.get_remaining(),
            "max_calls": limiter.max_calls,
            "time_window": limiter.time_window
        }
    return status


def format_rate_limiter_report():
    """格式化限流器状态报告"""
    status = get_rate_limiter_status()
    
    lines = []
    lines.append("⏱️ API 限流状态")
    lines.append("=" * 40)
    
    for name, data in status.items():
        remaining = data["remaining"]
        max_calls = data["max_calls"]
        
        # 状态指示
        if remaining == 0:
            indicator = "🔴"
        elif remaining < max_calls * 0.3:
            indicator = "🟡"
        else:
            indicator = "🟢"
        
        lines.append(f"{indicator} {name}: {remaining}/{max_calls} 可用")
    
    return "\n".join(lines)


if __name__ == "__main__":
    print("=" * 50)
    print("性能监控 + API限流 测试")
    print("=" * 50)
    
    # 测试限流器
    print("\n1. 限流器测试:")
    limiter = RateLimiter(max_calls=5, time_window=1)
    
    for i in range(7):
        can = limiter.can_call()
        remaining = limiter.get_remaining()
        print(f"  调用 {i+1}: can_call={can}, remaining={remaining}")
        if can:
            limiter.record_call()
        time.sleep(0.2)
    
    # 测试性能监控
    print("\n2. 性能监控测试:")
    
    # 模拟一些调用
    for i in range(5):
        start = time.time()
        time.sleep(0.1)  # 模拟耗时
        duration = time.time() - start
        perf_monitor.record("test_api", duration, success=True)
    
    # 模拟一个失败
    perf_monitor.record("test_api", 0.5, success=False, details="Timeout")
    
    # 打印统计
    stats = perf_monitor.get_stats("test_api")
    print(f"  test_api 统计:")
    print(f"    调用: {stats['test_api']['count']}")
    print(f"    成功率: {stats['test_api']['success_rate']:.1%}")
    print(f"    平均耗时: {stats['test_api']['avg_duration']:.3f}s")
    
    # 打印限流状态
    print(f"\n{format_rate_limiter_report()}")
    
    print("\n✅ 性能监控测试完成")
