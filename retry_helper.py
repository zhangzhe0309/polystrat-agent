#!/usr/bin/env python3
"""
重试机制模块
- 指数退避重试
- 可配置重试次数和延迟
- 详细错误日志
"""
import time
import requests
from polystrat_logger import log, log_error

def retry_request(url, method="GET", params=None, headers=None, data=None, 
                  max_retries=3, base_delay=1, timeout=15, **kwargs):
    """
    带重试的 HTTP 请求
    
    Args:
        url: 请求 URL
        method: 请求方法 (GET/POST)
        params: 查询参数
        headers: 请求头
        data: 请求体
        max_retries: 最大重试次数
        base_delay: 基础延迟（秒）
        timeout: 超时时间
        **kwargs: 其他参数
    
    Returns:
        dict: 响应数据
    """
    last_error = None
    
    for attempt in range(max_retries):
        try:
            if method.upper() == "GET":
                response = requests.get(
                    url, 
                    params=params, 
                    headers=headers, 
                    timeout=timeout,
                    **kwargs
                )
            elif method.upper() == "POST":
                response = requests.post(
                    url, 
                    params=params, 
                    headers=headers, 
                    json=data, 
                    timeout=timeout,
                    **kwargs
                )
            else:
                return {"success": False, "error": f"不支持的方法: {method}"}
            
            # 检查响应状态
            if response.status_code == 200:
                return {"success": True, "data": response.json()}
            elif response.status_code == 429:  # Rate limit
                log.warning(f"API 限流，等待重试: {url}")
                time.sleep(base_delay * (2 ** attempt))
                continue
            else:
                last_error = f"HTTP {response.status_code}"
                log.warning(f"请求失败 (尝试 {attempt + 1}/{max_retries}): {url} - {last_error}")
                
        except requests.exceptions.Timeout:
            last_error = "请求超时"
            log.warning(f"请求超时 (尝试 {attempt + 1}/{max_retries}): {url}")
            
        except requests.exceptions.ConnectionError:
            last_error = "连接失败"
            log.warning(f"连接失败 (尝试 {attempt + 1}/{max_retries}): {url}")
            
        except requests.exceptions.RequestException as e:
            last_error = str(e)
            log.warning(f"请求异常 (尝试 {attempt + 1}/{max_retries}): {url} - {last_error}")
            
        except Exception as e:
            last_error = str(e)
            log_error("retry", e, f"未知错误: {url}")
        
        # 指数退避
        if attempt < max_retries - 1:
            delay = base_delay * (2 ** attempt)
            time.sleep(delay)
    
    # 所有重试失败
    log_error("retry", f"请求最终失败: {url}", f"错误: {last_error}")
    return {"success": False, "error": last_error}

def retry_api_call(func, *args, max_retries=3, base_delay=1, **kwargs):
    """
    带重试的 API 调用
    
    Args:
        func: 调用函数
        *args: 函数参数
        max_retries: 最大重试次数
        base_delay: 基础延迟
        **kwargs: 关键字参数
    
    Returns:
        函数返回值
    """
    last_error = None
    
    for attempt in range(max_retries):
        try:
            result = func(*args, **kwargs)
            return result
            
        except Exception as e:
            last_error = str(e)
            log.warning(f"API 调用失败 (尝试 {attempt + 1}/{max_retries}): {func.__name__} - {last_error}")
            
            # 指数退避
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                time.sleep(delay)
    
    # 所有重试失败
    log_error("retry", f"API 调用最终失败: {func.__name__}", f"错误: {last_error}")
    return None

if __name__ == "__main__":
    print("=" * 50)
    print("重试机制测试")
    print("=" * 50)
    
    # 测试1: 成功请求
    print("\n1. 成功请求:")
    result = retry_request("https://httpbin.org/get")
    print(f"   结果: {result.get('success')}")
    
    # 测试2: 失败请求（重试）
    print("\n2. 失败请求（重试）:")
    result = retry_request("https://httpbin.org/status/500", max_retries=2, base_delay=0.1)
    print(f"   结果: {result.get('success')}, 错误: {result.get('error')}")
    
    # 测试3: 超时请求
    print("\n3. 超时请求:")
    result = retry_request("https://httpbin.org/delay/10", timeout=1, max_retries=2, base_delay=0.1)
    print(f"   结果: {result.get('success')}, 错误: {result.get('error')}")
    
    print("\n✅ 重试机制测试完成")
