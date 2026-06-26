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
    'retry_helper.py',
    'kalshi_api.py',
    'airdrop_hunter.py',
    'whale_monitor.py',
    'manifold_api.py',
    'arbitrage_module.py',
    'safe_file_ops.py',
    'key_manager.py',
    'input_validator.py',
]

code_summary = []
for fname in core_files:
    path = f'/root/.hermes/profiles/life/scripts/{fname}'
    if os.path.exists(path):
        with open(path, 'r') as f:
            content = f.read()
            lines = content.split('\n')[:50]
            code_summary.append(f"### {fname}\n```python\n" + '\n'.join(lines) + "\n```\n")

review_prompt = """请对 PolyStrat v3.6.1 进行全面评审。

评审维度：
1. **项目完整性** - 功能是否完整，是否有遗漏
2. **代码质量** - 代码结构、可读性、可维护性
3. **方案设计** - 架构设计是否合理，扩展性如何
4. **功能实现** - 各功能是否正确实现，边界处理
5. **安全性** - 密钥管理、输入验证、并发安全
6. **健壮性** - 错误处理、重试机制、容错能力

项目概述：
- Polymarket 预测市场交易机器人
- 多信号融合 (LLM + 情感 + 链上 + ML)
- 多平台支持 (Polymarket + Manifold + Kalshi)
- 空投猎手 (新链检测 + 协议监控)
- 链上监控 (巨鲸追踪 + 大额转账)
- 定时任务 (每4小时交易，每2小时监控)

以下是核心代码：

""" + "\n".join(code_summary) + """

请给出：
1. 各维度评分（0-100）
2. 总分
3. 关键发现（P0/P1/P2）
4. 改进建议
5. 项目整体评价
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
                {"role": "system", "content": "你是一个高级软件工程师和系统架构师，专门进行项目评审。请给出专业、客观、详细的评审意见。"},
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
                {"role": "system", "content": "你是一个高级软件工程师和系统架构师，专门进行项目评审。请给出专业、客观、详细的评审意见。"},
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
    filename = f"/tmp/{model_name.replace(' ', '_').lower()}_review_final.txt"
    with open(filename, 'w') as f:
        f.write(result)

print("\n" + "=" * 60)
print("所有评审完成!")
print("=" * 60)
