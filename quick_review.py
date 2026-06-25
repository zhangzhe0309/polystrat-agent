#!/usr/bin/env python3
"""
PolyStrat 快速评审脚本
用于快速检查代码质量和潜在问题
"""
import os
import sys
import json
from pathlib import Path
from datetime import datetime

# 代码目录
SCRIPT_DIR = Path(__file__).parent

def check_file_exists(file_path):
    """检查文件是否存在"""
    return Path(file_path).exists()

def count_lines(file_path):
    """统计文件行数"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return len(f.readlines())
    except:
        return 0

def check_imports(file_path):
    """检查导入语句"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            imports = []
            for line in content.split('\n'):
                if line.strip().startswith('import ') or line.strip().startswith('from '):
                    imports.append(line.strip())
            return imports
    except:
        return []

def check_bare_except(file_path):
    """检查裸 except 语句"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            count = content.count('except:')
            return count
    except:
        return 0

def check_hardcoded_keys(file_path):
    """检查硬编码密钥"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            # 检查常见的硬编码模式
            patterns = ['_KEY = "***', '_SECRET = "***', '_TOKEN = "***']
            found = []
            for pattern in patterns:
                if pattern in content:
                    found.append(pattern)
            return found
    except:
        return []

def run_review():
    """运行评审"""
    print("=" * 60)
    print("PolyStrat 快速评审")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    # 核心文件列表
    core_files = [
        'polystrat_agent.py',
        'news_search.py',
        'sentiment_analysis.py',
        'risk_management.py',
        'ml_optimizer.py',
        'adaptive_weights.py',
        'dynamic_optimizer.py',
        'onchain_monitor.py',
        'multi_platform.py',
        'smart_keywords.py',
        'polystrat_logger.py',
    ]
    
    results = {
        'timestamp': datetime.now().isoformat(),
        'files': {},
        'summary': {
            'total_files': len(core_files),
            'existing_files': 0,
            'total_lines': 0,
            'bare_except_count': 0,
            'hardcoded_keys': [],
        }
    }
    
    print("\n📁 文件检查:")
    for file_name in core_files:
        file_path = SCRIPT_DIR / file_name
        exists = check_file_exists(file_path)
        
        if exists:
            results['summary']['existing_files'] += 1
            lines = count_lines(file_path)
            bare_except = check_bare_except(file_path)
            hardcoded = check_hardcoded_keys(file_path)
            
            results['files'][file_name] = {
                'exists': True,
                'lines': lines,
                'bare_except': bare_except,
                'hardcoded_keys': hardcoded,
            }
            
            results['summary']['total_lines'] += lines
            results['summary']['bare_except_count'] += bare_except
            results['summary']['hardcoded_keys'].extend(hardcoded)
            
            status = '✅'
            details = f"{lines} 行"
            if bare_except > 0:
                details += f", {bare_except} 个裸except"
            if hardcoded:
                details += ", ⚠️ 硬编码密钥"
        else:
            results['files'][file_name] = {'exists': False}
            status = '❌'
            details = '文件不存在'
        
        print(f"  {status} {file_name}: {details}")
    
    # 总结
    print("\n📊 总结:")
    print(f"  文件: {results['summary']['existing_files']}/{results['summary']['total_files']}")
    print(f"  总行数: {results['summary']['total_lines']}")
    print(f"  裸except: {results['summary']['bare_except_count']}")
    print(f"  硬编码密钥: {len(results['summary']['hardcoded_keys'])}")
    
    # 评分
    score = 100
    issues = []
    
    # 文件完整性
    if results['summary']['existing_files'] < results['summary']['total_files']:
        missing = results['summary']['total_files'] - results['summary']['existing_files']
        score -= missing * 10
        issues.append(f"缺少 {missing} 个核心文件")
    
    # 裸except
    if results['summary']['bare_except_count'] > 20:
        score -= 10
        issues.append(f"裸except过多 ({results['summary']['bare_except_count']})")
    elif results['summary']['bare_except_count'] > 10:
        score -= 5
    
    # 硬编码密钥
    if results['summary']['hardcoded_keys']:
        score -= 20
        issues.append("存在硬编码密钥")
    
    # 日志系统
    if not check_file_exists(SCRIPT_DIR / 'polystrat_logger.py'):
        score -= 15
        issues.append("缺少日志系统")
    
    print(f"\n🎯 快速评分: {score}/100")
    
    if issues:
        print("\n⚠️ 主要问题:")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print("\n✅ 未发现严重问题")
    
    # 保存结果
    report_file = SCRIPT_DIR / 'review_report.json'
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    print(f"\n📄 详细报告: {report_file}")
    
    return score

if __name__ == "__main__":
    score = run_review()
    sys.exit(0 if score >= 70 else 1)
