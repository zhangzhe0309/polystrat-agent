import os
import requests

# 读取 API Keys
env_file = os.path.expanduser('~/.hermes/profiles/life/.env')
api_keys = {}

with open(env_file) as f:
    for line in f:
        line = line.strip()
        if 'NVIDIA_API_KEY_2' in line and '=' in line:
            api_keys['nvidia'] = line.strip().split('=', 1)[1]
        elif 'GLM_API_KEY' in line and '=' in line:
            api_keys['glm'] = line.strip().split('=', 1)[1]

# 收集代码摘要
core_files = [
    'polystrat_agent.py',
    'circuit_breaker.py',
    'trade_limits.py',
    'error_handler.py',
    'advanced_voting.py',
    'arbitrage_enhanced.py',
    'whale_copy.py',
    'polymarket_v2.py',
    'backtest_system.py',
    'config_center.py',
]

code_summary = []
for fname in core_files:
    path = f'/root/.hermes/profiles/life/scripts/{fname}'
    if os.path.exists(path):
        with open(path, 'r') as f:
            content = f.read()
            lines = content.split('\n')[:60]
            code_summary.append(f"### {fname}\n```python\n" + '\n'.join(lines) + "\n```\n")

review_prompt = """请对 PolyStrat v3.13 进行最终评审。

评审维度（每项 0-100 分）：
1. **安全性** - 密钥管理、资金安全、断路器、限额
2. **健壮性** - 错误处理、重试机制、并发安全
3. **策略合理性** - 信号融合、投票机制、风险管理
4. **代码质量** - 模块化、可维护性、测试覆盖
5. **生产就绪度** - 监控、告警、回测、文档

v3.13 新增特性：
- 断路器机制（连续亏损保护、每日亏损限制）
- 交易限额（单笔、每日、总仓位）
- LLM 多 API Key 支持（4个模型，2个平台）
- 统一异常处理（错误分类、统计）
- GLM-5.1 作为备用模型

以下是核心代码：

""" + "\n".join(code_summary) + """

请给出：
1. 各维度评分（0-100）
2. 总分
3. 与之前版本对比（v3.11: 62分）
4. 还需要优化的点
5. 是否可以实盘运行的结论
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
                {"role": "system", "content": "你是一个量化交易系统架构师和安全专家。请给出专业、严格、客观的评审意见。"},
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
                {"role": "system", "content": "你是一个量化交易系统架构师和安全专家。请给出专业、严格、客观的评审意见。"},
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
    ("GLM-5.1", "glm", "glm-5.1"),
    ("Qwen 3.5", "nvidia", "qwen/qwen3.5-397b-a17b"),
]

# 执行评审
results = {}

for model_name, api_type, model_id in models:
    print("\n" + "=" * 60)
    print(f"正在调用 {model_name} 评审...")
    print("=" * 60)
    
    result = call_model(api_type, model_id, short_prompt)
    print(result[:2000] + "..." if len(result) > 2000 else result)
    results[model_name] = result
    
    # 保存结果
    filename = f"/tmp/{model_name.replace(' ', '_').lower()}_review_v313.txt"
    with open(filename, 'w') as f:
        f.write(result)

print("\n" + "=" * 60)
print("所有评审完成!")
