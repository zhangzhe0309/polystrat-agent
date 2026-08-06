"""
Tavily API 双 Key 自动切换
当一个 Key 配额用完时自动切换到另一个
"""
import os

# 优先从环境变量读取 Tavily API Key
TAVILY_KEYS = [k for k in [
    os.environ.get("TAVILY_API_KEY"),
    os.environ.get("TAVILY_API_KEY_1"),
    os.environ.get("TAVILY_API_KEY_2"),
] if k]

def get_working_key():
    """获取可用的 API Key"""
    import requests
    
    for key in TAVILY_KEYS:
        try:
            resp = requests.post(
                'https://api.tavily.com/search',
                json={
                    'api_key': key,
                    'query': 'test',
                    'max_results': 1
                },
                timeout=10
            )
            if resp.status_code == 200:
                return key
        except (requests.RequestException, ValueError, KeyError):
            continue
    
    return TAVILY_KEYS[0]  # 默认返回第一个

if __name__ == "__main__":
    key = get_working_key()
    print(f"可用 Key: {key[:15]}...{key[-4:]}")
