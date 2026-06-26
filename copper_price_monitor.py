#!/usr/bin/env python3
"""
废铜价格监控脚本 - SMM H5 版本
- 抓取上海有色网 (SMM) 废铜价格
- 对比昨日价格，波动超阈值则推送通知
- 无变化或波动小时保持静默（watchdog 模式）
"""

import json
import os
import sys
import re
from datetime import datetime

try:
    import requests
except ImportError:
    print("ERROR: requests 库未安装", file=sys.stderr)
    sys.exit(1)

# ============ 配置区 ============
THRESHOLD_PERCENT = 1.0  # 价格波动超过 1% 才推送
DATA_FILE = os.path.expanduser("~/.hermes/profiles/life/home/.hermes/copper_price_history.json")

# SMM H5 页面（无需登录，桌面版也返回相同表格）
PRICE_URL = "https://hq.smm.cn/h5/scrap-copper-price"

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# ============ 工具函数 ============

def load_history():
    """加载历史价格数据"""
    if not os.path.exists(DATA_FILE):
        return {"last_data": None, "last_date": None}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"last_data": None, "last_date": None}

def save_history(data):
    """保存历史价格数据"""
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def fetch_copper_prices():
    """
    从 SMM 抓取废铜价格
    返回：{'date': '2026-06-18', 'prices': [...], 'benchmark': {...}}
    """
    try:
        resp = requests.get(PRICE_URL, headers=HTTP_HEADERS, timeout=15)
        resp.raise_for_status()
        html = resp.text
        
        data = {"date": "", "prices": []}
        
        # 解析表格行
        row_pattern = r'<tr[^>]*>(.*?)</tr>'
        rows = re.findall(row_pattern, html, re.DOTALL)
        
        for row in rows:
            if "废铜价格" not in row:
                continue
            
            # 提取单元格
            td_pattern = r'<td[^>]*>(.*?)</td>'
            cells = re.findall(td_pattern, row, re.DOTALL)
            if len(cells) < 6:
                continue
            
            # Cell 0: 名称
            name_match = re.search(r'>([^<]+)</a>', cells[0])
            if not name_match:
                continue
            name = name_match.group(1).strip()
            
            # Cell 1: 范围
            range_match = re.search(r'>([\d\s-]+)<', cells[1])
            price_range = range_match.group(1).replace(' ', '') if range_match else None
            
            # Cell 2: 均价
            avg_match = re.search(r'>(\d+)<', cells[2])
            avg = int(avg_match.group(1)) if avg_match else None
            
            # Cell 3: 涨跌
            change_match = re.search(r'>(-?\d+)<', cells[3])
            change = int(change_match.group(1)) if change_match else 0
            
            # Cell 5: 日期
            date_match = re.search(r'(\d{4}-\d{2}-\d{2})', cells[5])
            date = date_match.group(1) if date_match else ""
            
            if avg:
                data["prices"].append({
                    "name": name,
                    "range": price_range,
                    "avg": avg,
                    "change": change,
                    "date": date
                })
                if not data["date"]:
                    data["date"] = date
        
        # 设置基准价（优先上海）
        if data["prices"]:
            shanghai = next((p for p in data["prices"] if "上海" in p["name"]), None)
            data["benchmark"] = shanghai if shanghai else data["prices"][0]
        
        return data
    
    except requests.RequestException as e:
        print(f"抓取失败：{e}", file=sys.stderr)
        return None

def calculate_change_percent(current, previous):
    """计算价格变化百分比"""
    if previous is None or previous == 0:
        return None
    return round((current - previous) / previous * 100, 2)

def format_message(today_data, history):
    """格式化推送消息"""
    lines = []
    lines.append("🔶 废铜价格日报")
    lines.append(f"日期：{today_data['date']}")
    lines.append("")
    lines.append("主要市场废铜回收价（元/吨）：")
    lines.append("")
    
    # 获取昨日价格
    prev_benchmark = None
    if history.get("last_data"):
        prev_shanghai = next(
            (p for p in history["last_data"].get("prices", []) if "上海" in p["name"]),
            None
        )
        if prev_shanghai:
            prev_benchmark = prev_shanghai.get("avg")
    
    # 展示前 5 个市场
    for p in today_data["prices"][:5]:
        change_str = f" ({p['change']:+d})"
        
        # 如果是上海价且有昨日数据，显示百分比
        if "上海" in p["name"] and prev_benchmark:
            pct = calculate_change_percent(p["avg"], prev_benchmark)
            if pct is not None:
                change_str = f" ({p['change']:+d}, {pct:+.1f}%)"
        
        lines.append(f"  • {p['name']}: {p['avg']}{change_str}")
        if p["range"]:
            lines.append(f"    范围：{p['range']}")
    
    lines.append("")
    lines.append(f"数据来源：上海有色网 (hq.smm.cn)")
    
    return "\n".join(lines)

# ============ 主逻辑 ============

def main():
    # 1. 加载历史数据
    history = load_history()
    
    # 2. 抓取今日价格
    today_data = fetch_copper_prices()
    if not today_data or not today_data.get("prices"):
        print("ERROR: 未能获取今日铜价", file=sys.stderr)
        sys.exit(1)
    
    # 3. 获取基准价格
    benchmark = today_data.get("benchmark")
    if not benchmark:
        print("ERROR: 未找到基准价格", file=sys.stderr)
        sys.exit(1)
    
    # 4. 计算变化
    prev_benchmark = None
    if history.get("last_data"):
        prev_shanghai = next(
            (p for p in history["last_data"].get("prices", []) if "上海" in p["name"]),
            None
        )
        if prev_shanghai:
            prev_benchmark = prev_shanghai.get("avg")
    
    change_pct = calculate_change_percent(benchmark["avg"], prev_benchmark) if prev_benchmark else None
    
    # 5. 判断是否需要推送
    should_notify = False
    if prev_benchmark is None:
        # 首次运行，总是推送
        should_notify = True
        print(f"[首次运行] 上海废铜价格：{benchmark['avg']} 元/吨")
    elif change_pct is not None and abs(change_pct) >= THRESHOLD_PERCENT:
        should_notify = True
        print(f"[价格波动] {change_pct:+.1f}% >= {THRESHOLD_PERCENT}%")
    else:
        # 静默模式
        print(f"[价格平稳] 上海：{benchmark['avg']} (昨日：{prev_benchmark}, 变化：{change_pct:+.2f}%)")
        sys.exit(0)
    
    # 6. 生成并输出消息
    message = format_message(today_data, history)
    print(message)
    
    # 7. 保存历史
    history["last_data"] = today_data
    history["last_date"] = today_data["date"]
    save_history(history)

if __name__ == "__main__":
    main()