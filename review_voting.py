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

# 当前投票机制代码
current_code = """
当前 LLM 投票机制：

```python
# 3个模型：Qwen 3.5, Kimi K2.6, Llama 3.3 70B
probabilities = []
for provider in LLM_PROVIDERS:
    resp = requests.post(...)
    prob = int(match.group(1))
    probabilities.append(prob / 100.0)

# 问题：简单取平均值
avg = sum(probabilities) / len(probabilities)
return avg
```

已知问题：
1. 简单平均值，没有权重
2. 没有处理异常值
3. 分歧大时无特殊处理
4. 没有置信度评估
"""

review_prompt = """请评审 PolyStrat 的 LLM 模型投票机制，并提供优化方案。

当前实现：
- 3个模型（Qwen 3.5, Kimi K2.6, Llama 3.3 70B）
- 每个模型输出概率（0-100）
- 简单取平均值

问题：
1. 模型分歧大时（如 30%, 60%, 90%），平均值可能不准确
2. 没有考虑各模型的历史准确率
3. 没有异常值处理
4. 没有置信度评估

请提供：
1. 更好的投票算法（如加权投票、中位数、异常值过滤）
2. 分歧检测和处理机制
3. 置信度评估方法
4. 具体代码实现建议
"""

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
                {"role": "system", "content": "你是一个量化交易专家和AI工程师，专门优化模型集成和投票机制。请提供专业、实用的优化方案。"},
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
                {"role": "system", "content": "你是一个量化交易专家和AI工程师，专门优化模型集成和投票机制。请提供专业、实用的优化方案。"},
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
]

# 执行评审
results = {}

for model_name, api_type, model_id in models:
    print("\n" + "=" * 60)
    print(f"正在调用 {model_name} 评审投票机制...")
    print("=" * 60)
    
    result = call_model(api_type, model_id, review_prompt)
    print(result)
    results[model_name] = result
    
    # 保存结果
    filename = f"/tmp/{model_name.replace(' ', '_').lower()}_voting_review.txt"
    with open(filename, 'w') as f:
        f.write(result)

print("\n" + "=" * 60)
print("评审完成!")
