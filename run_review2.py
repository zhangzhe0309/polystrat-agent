#!/usr/bin/env python3
"""DeepSeek v4 Flash + Kimi K2.6 Review"""
import os
import requests

# Read API Key
env_file = os.path.expanduser('~/.hermes/profiles/life/.env')
api_key = ''
with open(env_file) as f:
    for line in f:
        if 'NVIDIA_API_KEY_2' in line and '=' in line:
            api_key = line.strip().split('=', 1)[1]
            break

# Read review prompt
with open('/tmp/review_prompt_v34.txt', 'r') as f:
    review_prompt = f.read()

# Shorten prompt
short_prompt = review_prompt[:6000] + '\n\n... (code truncated, review based on above)'

def call_model(model_name, prompt):
    url = "https://integrate.api.nvidia.com/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    data = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": "You are a senior software engineer doing code review. Give professional, objective, detailed feedback. Be strict with scoring."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7,
        "max_tokens": 2000
    }
    
    try:
        response = requests.post(url, headers=headers, json=data, timeout=120)
        if response.status_code == 200:
            return response.json()['choices'][0]['message']['content']
        else:
            return f"API error: {response.status_code}"
    except Exception as e:
        return f"Exception: {e}"

# Call DeepSeek v4 Flash
print("=" * 60)
print("Calling DeepSeek v4 Flash...")
print("=" * 60)
deepseek_result = call_model("deepseek-ai/deepseek-v4-flash", short_prompt)
print(deepseek_result)
with open('/tmp/deepseek_v4_flash_review.txt', 'w') as f:
    f.write(deepseek_result)

print("\n" + "=" * 60)
print("Calling Kimi K2.6...")
print("=" * 60)
kimi_result = call_model("moonshotai/kimi-k2.6", short_prompt)
print(kimi_result)
with open('/tmp/kimi_k26_review.txt', 'w') as f:
    f.write(kimi_result)

print("\n" + "=" * 60)
print("Review complete!")
