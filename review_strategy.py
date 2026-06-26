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

# 策略描述
strategy_prompt = """请评审 PolyStrat v3.13 的交易策略合理性。

## 策略概述

### 1. 信号融合策略
- LLM 信号 (40%): 4个模型投票（Qwen 3.5, Kimi K2.6, Llama 3.3, GLM-5.1）
- 情感信号 (20%): 新闻情感分析
- 链上信号 (20%): 巨鲸动向
- ML 信号 (20%): 机器学习预测

### 2. 投票机制
- 加权投票（基于历史准确率）
- 异常值过滤（MAD 检测）
- 分歧检测（标准差阈值 20%）
- 置信度评估

### 3. 风险管理
- 断路器：连续亏损 5 次/每日亏损 $50/总回撤 $100
- 交易限额：单笔 $10/每日 10 次/每日 $100/总仓位 $200
- Fractional Kelly 仓位管理

### 4. 套利策略
- 跨平台套利（Polymarket + Kalshi + Manifold）
- 鲸鱼跟单（KongScore 筛选）
- 流动性挖矿（World Cup 2026 奖励）

### 5. 定时任务
- 交易：每 4 小时
- 监控：每 2 小时
- 空投：每天

请从以下维度评审：
1. **信号融合合理性** - 权重分配是否科学？是否有更好的融合方式？
2. **投票机制有效性** - 加权投票是否能提高准确率？异常值过滤是否合理？
3. **风险管理充分性** - 断路器和限额是否足够？是否需要其他风控？
4. **套利策略可行性** - 跨平台套利是否真的可行？滑点和执行风险如何？
5. **整体策略评估** - 策略是否自洽？是否有逻辑漏洞？

请给出：
1. 各维度评分（0-100）
2. 策略总分
3. 关键问题
4. 改进建议
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
                {"role": "system", "content": "你是一个量化交易策略专家，专门评审交易策略的合理性和有效性。请给出专业、严格、客观的评审意见。"},
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
                {"role": "system", "content": "你是一个量化交易策略专家，专门评审交易策略的合理性和有效性。请给出专业、严格、客观的评审意见。"},
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
    print(f"正在调用 {model_name} 评审策略合理性...")
    print("=" * 60)
    
    result = call_model(api_type, model_id, strategy_prompt)
    print(result[:2000] + "..." if len(result) > 2000 else result)
    results[model_name] = result
    
    # 保存结果
    filename = f"/tmp/{model_name.replace(' ', '_').lower()}_strategy_review.txt"
    with open(filename, 'w') as f:
        f.write(result)

print("\n" + "=" * 60)
print("所有策略评审完成!")
