#!/usr/bin/env python3
"""
并行信号采集器 — PolyStrat v4.2
================================
MapReduce 模式：并行采集多市场信号，串行决策和下单。

架构:
- Stage 1 (Map/并行): 每个市场的新闻搜索、情感分析、链上信号、ML分析并行执行
- Stage 2 (Reduce/串行): 信号融合、Debate辩论、决策、下单 — 需要文件锁和状态一致性

为什么不全并行？
- safe_file_ops 有文件锁，但高频并发写trade_log可能导致锁竞争
- circuit_breaker/trade_limits 是全局状态，并行修改不安全
- 下单是IO密集但有副作用，串行更可控

为什么用ThreadPool而不是ProcessPool？
- 信号采集主要是HTTP API调用，GIL不阻塞
- ThreadPool内存开销更小（~30MB/线程 vs ~100MB/进程）
- VPS 961MB限制，3线程即可

作者: PolyStrat Team
日期: 2026-07-08
"""

import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from polystrat_logger import log, log_error

# ============ 配置 ============

PARALLEL_CONFIG = {
    "enabled": True,
    "max_workers": 3,           # 并行线程数（VPS 961MB限制）
    "timeout_per_market": 60,   # 单市场超时60秒
    "fallback_serial": True,    # 并行失败时回退串行
}


def collect_signals_for_market(market, signal_funcs):
    """
    并行采集单个市场的所有信号
    
    Args:
        market: 市场信息 dict
        signal_funcs: 信号采集函数列表，每个函数签名 fn(market) -> (name, result)
    
    Returns:
        dict: {signal_name: result} 所有信号结果
    """
    results = {}
    errors = []
    
    for func in signal_funcs:
        try:
            name, result = func(market)
            results[name] = result
        except Exception as e:
            name = getattr(func, '__name__', 'unknown')
            errors.append((name, str(e)))
            results[name] = None
    
    if errors:
        log.warning(f"信号采集部分失败: {errors}")
    
    return results


def parallel_signal_collect(markets, analyze_fn, config=None):
    """
    MapReduce: 并行分析多个市场
    
    Args:
        markets: 市场列表
        analyze_fn: 单市场分析函数 fn(market) -> decision_dict
        config: 配置覆盖
    
    Returns:
        list: [decision_dict, ...] 按原始市场顺序排列
    """
    cfg = {**PARALLEL_CONFIG, **(config or {})}
    
    if not cfg["enabled"] or len(markets) <= 1:
        # 单市场或禁用并行 → 串行执行
        return _serial_collect(markets, analyze_fn)
    
    decisions = [None] * len(markets)
    lock = threading.Lock()
    completed = [0]
    
    def _worker(idx, market):
        """单市场分析worker"""
        try:
            result = analyze_fn(market)
            with lock:
                decisions[idx] = result
                completed[0] += 1
                count = completed[0]
            if result:
                title = market.get("title", "?")[:30]
                print(f"   ✅ [{count}/{len(markets)}] {title}...")
            return result
        except Exception as e:
            with lock:
                completed[0] += 1
            log_error("parallel_collect", e, f"市场分析失败: {market.get('title', '?')[:30]}")
            return None
    
    try:
        start = time.time()
        with ThreadPoolExecutor(max_workers=cfg["max_workers"]) as executor:
            futures = {
                executor.submit(_worker, idx, m): idx 
                for idx, m in enumerate(markets)
            }
            
            for future in as_completed(futures, timeout=cfg["timeout_per_market"] * len(markets)):
                try:
                    future.result(timeout=cfg["timeout_per_market"])
                except Exception as e:
                    idx = futures[future]
                    log_error("parallel_collect", e, f"市场{idx}超时")
                    decisions[idx] = None
        
        elapsed = time.time() - start
        valid = sum(1 for d in decisions if d is not None)
        print(f"\n⚡ 并行分析完成: {valid}/{len(markets)} 市场, 耗时 {elapsed:.1f}s")
        
        return [d for d in decisions if d is not None]
        
    except Exception as e:
        log_error("parallel_collect", e, "并行分析失败，回退串行")
        if cfg["fallback_serial"]:
            print(f"⚠️ 并行失败，回退串行模式...")
            return _serial_collect(markets, analyze_fn)
        return []


def _serial_collect(markets, analyze_fn):
    """串行回退模式"""
    decisions = []
    for m in markets:
        try:
            result = analyze_fn(m)
            if result:
                decisions.append(result)
        except Exception as e:
            log_error("serial_collect", e, f"市场分析失败: {m.get('title', '?')[:30]}")
    return decisions


# ============ 自测 ============
if __name__ == "__main__":
    import random
    
    def mock_analyze(market):
        """模拟市场分析（0.5-2秒）"""
        time.sleep(random.uniform(0.5, 2.0))
        return {"title": market["title"], "signal": random.choice(["buy", "sell", "hold"])}
    
    test_markets = [
        {"title": f"Market_{i}", "yes_price": 0.5} 
        for i in range(6)
    ]
    
    print("=== 并行信号采集测试 ===\n")
    
    # 串行
    start = time.time()
    serial_results = _serial_collect(test_markets, mock_analyze)
    serial_time = time.time() - start
    print(f"串行: {len(serial_results)} 市场, {serial_time:.1f}s")
    
    # 并行
    start = time.time()
    parallel_results = parallel_signal_collect(test_markets, mock_analyze)
    parallel_time = time.time() - start
    print(f"并行: {len(parallel_results)} 市场, {parallel_time:.1f}s")
    print(f"加速比: {serial_time/parallel_time:.1f}x")
