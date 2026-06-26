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
    'arbitrage_enhanced.py',
    'whale_copy.py',
    'polymarket_v2.py',
    'advanced_voting.py',
    'backtest_system.py',
    'config_center.py',
    'alert_system.py',
    'safe_file_ops.py',
    'key_manager.py',
]

code_summary = []
for fname in core_files:
    path = f'/root/.hermes/profiles/life/scripts/{fname}'
    if os.path.exists(path):
        with open(path, 'r') as f:
            content = f.read()
            lines = content.split('\n')[:60]
            code_summary.append(f"### {fname}\n```python\n" + '\n'.join(lines) + "\n```\n")

review_prompt = """请对 PolyStrat v3.11 进行全面深度评审。

评审维度：
1. **系统强大性** - 功能是否完整，策略是否多样化
2. **安全性** - 密钥管理，资金安全，并发安全
3. **设计漏洞** - 架构设计是否有缺陷
4. **方案合理性** - 策略逻辑是否合理，风险控制是否完善
5. **可扩展性** - 是否容易添加新功能
6. **生产就绪度** - 是否可以实盘运行

系统概述：
- Polymarket 预测市场交易机器人
- 多信号融合 (LLM + 情感 + 链上 + ML)
- 高级投票系统（加权+异常值过滤）
- 跨平台套利（Polymarket + Kalshi + Manifold）
- 鲸鱼跟单（KongScore + Multiplier）
- 流动性挖矿（World Cup 2026 奖励）
- 定时任务（交易+监控+空投）

以下是核心代码：

""" + "\n".join(code_summary) + """

请给出：
1. 各维度评分（0-100）
2. 总分
3. 关键发现（P0/P1/P2）
4. 设计漏洞分析
5. 改进建议
6. 是否可以实盘运行的结论
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
                {"role": "system", "content": "你是一个量化交易系统架构师和安全专家，专门评审交易系统。请给出专业、严格、客观的评审意见。"},
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
                {"role": "system", "content": "你是一个量化交易系统架构师和安全专家，专门评审交易系统。请给出专业、严格、客观的评审意见。"},
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
    print(result[:2000] + "..." if len(result) > 2000 else result)
    results[model_name] = result
    
    # 保存结果
    filename = f"/tmp/{model_name.replace(' ', '_').lower()}_review_v311.txt"
    with open(filename, 'w') as f:
        f.write(result)

print("\n" + "=" * 60)
print("所有评审完成!")
