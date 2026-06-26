"""
Tavily API 双 Key 自动切换
当一个 Key 配额用完时自动切换到另一个

环境变量:
  TAVILY_API_KEY_1 - 第一个 Tavily API Key
  TAVILY_API_KEY_2 - 第二个 Tavily API Key
"""
import os

# 两个 Tavily API Key (从环境变量读取)
TAVILY_KEYS = [
    os.environ.get("TAVILY_API_KEY_1", ""),
    os.environ.get("TAVILY_API_KEY_2", ""),
]

def get_working_key():
    """获取可用的 API Key"""
    import requests
    
    for key in TAVILY_KEYS:
        if not key:
            continue
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
        except:
            continue
    
    return TAVILY_KEYS[0] if TAVILY_KEYS[0] else ""

if __name__ == "__main__":
    key = get_working_key()
    if key:
        print(f"可用 Key: {key[:15]}...{key[-4:]}")
    else:
        print("未配置 Tavily API Key，请设置环境变量 TAVILY_API_KEY_1 和 TAVILY_API_KEY_2")
