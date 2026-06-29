#!/usr/bin/env python3
"""
加密空投情报日报 - Agent 调用脚本
- 调用 hermes agent 执行空投研究
- 无_agent=False，使用 agent 推理
"""

import subprocess
import sys
import os

def main():
    # 调用 hermes agent 执行提示词
    # 使用单查询模式
    from config_center import SCRIPTS_DIR; prompt_file = str(SCRIPTS_DIR / "airdrop_daily_prompt.py")
    
    # 读取提示词
    with open(prompt_file, 'r') as f:
        prompt_content = f.read()
    
    # 执行 hermes chat -q
    cmd = [
        "hermes", 
        "chat", 
        "-q", 
        prompt_content.strip()
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=180,  # 3分钟超时
            cwd="/root"
        )
        
        if result.returncode != 0:
            print(f"ERROR: Hermes failed with code {result.returncode}", file=sys.stderr)
            print(result.stderr, file=sys.stderr)
            sys.exit(1)
        
        # 输出结果（Hermes cron 会捕获 stdout）
        print(result.stdout)
        
    except subprocess.TimeoutExpired:
        print("ERROR: Hermes 执行超时（3分钟）", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()