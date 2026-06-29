import os
import requests

# 读取 API Keys
env_file = os.path.expanduser('~/.hermes/profiles/life/.env')
api_keys = {}

with open(env_file) as f:
    for line in f:
        line = line.strip()
        if 'NVIDIA_API_KEY_2' in line and '=' in line:
            api_keys['nvidia'] = line.split('=', 1)[1]
        elif 'GLM_API_KEY' in line and '=' in line:
            api_keys['glm'] = line.split('=', 1)[1]

# 收集代码摘要
core_files = [
    'polystrat_agent.py',
    'kalshi_api.py',
    'airdrop_hunter.py',
    'whale_monitor.py',
    'manifold_api.py',
]

code_summary = []
for fname in core_files:
    from config_center import SCRIPTS_DIR; path = str(SCRIPTS_DIR / fname)
    if os.path.exists(path):
        with open(path, 'r') as f:
            content = f.read()
            lines = content.split('\n')[:60]
            code_summary.append(f"### {fname}\n```python\n" + '\n'.join(lines) + "\n```\n")

review_prompt = """请评审 PolyStrat v3.6 升级。

重点检查：
1. 新增模块（Kalshi API、空投猎手、链上监控）的质量
2. 定时任务配置是否合理
3. 代码是否符合生产标准
4. 安全性和健壮性

以下是新增模块代码：

""" + "\n".join(code_summary) + """

请给出：
1. 各模块评分（0-100）
2. 总分
3. 关键发现
4. 改进建议
"""

# 缩短 prompt
short_prompt = review_prompt[:6000] + "\n\n... (代码已截断)"

# 评审函数
def call_model(api_type, model_name, prompt):
    if api_type == 'nvidia':
        url = "https://integrate.api.nvidia.com/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_keys.get('nvidia', '')}"
        }
        data = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": "你是一个高级软件工程师，专门进行代码评审。请给出专业、客观、详细的评审意见。"},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "max_tokens": 2000
        }
    elif api_type == 'glm':
        url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_keys.get('glm', '')}"
        }
        data = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": "你是一个高级软件工程师，专门进行代码评审。请给出专业、客观、详细的评审意见。"},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "max_tokens": 2000
        }
    else:
        return "未知API类型"
    
    try:
        response = requests.post(url, headers=headers, json=data, timeout=90)
        if response.status_code == 200:
            return response.json()['choices'][0]['message']['content']
        else:
            return f"API错误: {response.status_code}"
    except Exception as e:
        return f"异常: {e}"

# 评审模型列表
models = [
    ("GLM-5.1", "glm", "glm-4-plus"),
    ("Qwen 3.5", "nvidia", "qwen/qwen3.5-397b-a17b"),
    ("Kimi K2.6", "nvidia", "moonshotai/kimi-k2.6"),
    ("DeepSeek v4 Flash", "nvidia", "deepseek-ai/deepseek-v4-flash"),
]

# 执行评审
results = {}

for model_name, api_type, model_id in models:
    print("\n" + "=" * 60)
    print(f"正在调用 {model_name} 评审...")
    print("=" * 60)
    
    result = call_model(api_type, model_id, short_prompt)
    print(result[:1500] + "..." if len(result) > 1500 else result)
    results[model_name] = result
    
    # 保存结果
    filename = f"/tmp/{model_name.replace(' ', '_').lower()}_review_v36.txt"
    with open(filename, 'w') as f:
        f.write(result)

print("\n" + "=" * 60)
print("所有评审完成!")
print("=" * 60)
