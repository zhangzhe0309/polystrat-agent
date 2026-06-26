#!/usr/bin/env python3
"""
PolyStrat v3.4 多模型评审脚本
评审模型: Kimi K2.6, GLM-5.1, DeepSeek v4 Flash, Qwen 3.5
"""
import os
import requests
import sys

# 读取 API Keys
env_file = os.path.expanduser('~/.hermes/profiles/life/.env')
api_keys = {}

with open(env_file) as f:
    for line in f:
        line = line.strip()
        if 'NVIDIA_API_KEY_2=' in line:
            api_keys['nvidia'] = line.split('=', 1)[1]
        elif 'GLM_API_KEY=' in line:
            api_keys['glm'] = line.split('=', 1)[1]

print(f"NVIDIA Key: {api_keys.get('nvidia', '')[:10]}...")
print(f"GLM Key: {api_keys.get('glm', '')[:10]}...")

# 读取评审 prompt
with open('/tmp/review_prompt_v34.txt', 'r') as f:
    review_prompt = f.read()

# 缩短 prompt (取前6000字符)
short_prompt = review_prompt[:6000] + "\n\n... (代码已截断，请基于以上代码评审)"

print(f"\n评审 Prompt 长度: {len(short_prompt)} 字符")

# 评审函数
def call_nvidia_model(model_name, prompt):
    """调用 NVIDIA API 的模型"""
    url = "https://integrate.api.nvidia.com/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_keys.get('nvidia', '')}"
    }
    data = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": "你是一个高级软件工程师，专门进行代码评审。请给出专业、客观、详细的评审意见。评分要严格。"},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7,
        "max_tokens": 2000
    }
    
    try:
        response = requests.post(url, headers=headers, json=data, timeout=90)
        if response.status_code == 200:
            return response.json()['choices'][0]['message']['content']
        else:
            return f"API错误: {response.status_code} - {response.text[:200]}"
    except Exception as e:
        return f"异常: {e}"

def call_glm_model(prompt):
    """调用 GLM API"""
    url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_keys.get('glm', '')}"
    }
    data = {
        "model": "glm-4-plus",
        "messages": [
            {"role": "system", "content": "你是一个高级软件工程师，专门进行代码评审。请给出专业、客观、详细的评审意见。评分要严格。"},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7,
        "max_tokens": 2000
    }
    
    try:
        response = requests.post(url, headers=headers, json=data, timeout=90)
        if response.status_code == 200:
            return response.json()['choices'][0]['message']['content']
        else:
            return f"API错误: {response.status_code} - {response.text[:200]}"
    except Exception as e:
        return f"异常: {e}"

# 评审模型列表
models = [
    ("Kimi K2.6", "nvidia", "moonshotai/kimi-k2.6"),
    ("GLM-5.1", "glm", None),
    ("DeepSeek v4 Flash", "nvidia", "deepseek/deepseek-r1"),
    ("Qwen 3.5", "nvidia", "qwen/qwen3.5-397b-a17b"),
]

# 执行评审
results = {}

for model_name, api_type, model_id in models:
    print("\n" + "=" * 60)
    print(f"正在调用 {model_name} 评审...")
    print("=" * 60)
    
    if api_type == "nvidia":
        result = call_nvidia_model(model_id, short_prompt)
    elif api_type == "glm":
        result = call_glm_model(short_prompt)
    else:
        result = "未知API类型"
    
    print(result[:1500] + "..." if len(result) > 1500 else result)
    results[model_name] = result
    
    # 保存单个结果
    filename = f"/tmp/{model_name.replace(' ', '_').lower()}_review_v34.txt"
    with open(filename, 'w') as f:
        f.write(result)
    print(f"\n结果已保存到: {filename}")

# 保存所有结果
print("\n" + "=" * 60)
print("所有评审完成!")
print("=" * 60)

# 输出总结
print("\n评审结果总结:")
for model_name, result in results.items():
    # 尝试提取分数
    lines = result.split('\n')
    score_line = [l for l in lines if '总分' in l or '总评' in l or '/100' in l]
    if score_line:
        print(f"  {model_name}: {score_line[0].strip()}")
    else:
        print(f"  {model_name}: (未找到明确分数)")
