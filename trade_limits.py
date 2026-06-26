#!/usr/bin/env python3
"""
交易限额模块
- 单笔交易限额
- 每日交易限额
- 总仓位限制
- 余额预检查
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from polystrat_logger import log, log_error

# 限额配置
LIMITS_CONFIG = {
    "max_single_trade": 10.0,       # 单笔最大交易
    "max_daily_trades": 10,         # 每日最大交易次数
    "max_daily_volume": 100.0,      # 每日最大交易量
    "max_total_exposure": 200.0,    # 最大总仓位
    "min_balance_required": 10.0,   # 最低余额要求
    "max_position_pct": 0.05,       # 单笔最大仓位比例
}

# 状态文件
STATE_FILE = Path("/root/.hermes/profiles/life/data/trade_limits.json")
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

class TradeLimiter:
    """交易限额管理器"""
    
    def __init__(self):
        self.state = self._load_state()
    
    def _load_state(self):
        """加载状态"""
        try:
            if STATE_FILE.exists():
                return json.loads(STATE_FILE.read_text())
        except:
            pass
        
        return {
            "daily_trades": 0,
            "daily_volume": 0.0,
            "total_exposure": 0.0,
            "last_reset_date": None,
        }
    
    def _save_state(self):
        """保存状态"""
        try:
            STATE_FILE.write_text(json.dumps(self.state, indent=2))
        except Exception as e:
            log_error("limits", e, "保存交易限额状态失败")
    
    def _reset_daily(self):
        """每日重置"""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.state.get("last_reset_date") != today:
            self.state["daily_trades"] = 0
            self.state["daily_volume"] = 0.0
            self.state["last_reset_date"] = today
            self._save_state()
    
    def can_trade(self, amount, balance=None):
        """
        检查是否可以交易
        
        Args:
            amount: 交易金额
            balance: 当前余额（可选）
        
        Returns:
            tuple: (是否允许, 原因)
        """
        self._reset_daily()
        
        # 检查单笔限额
        if amount > LIMITS_CONFIG["max_single_trade"]:
            return False, f"超过单笔限额 ${LIMITS_CONFIG['max_single_trade']:.2f}"
        
        # 检查每日交易次数
        if self.state["daily_trades"] >= LIMITS_CONFIG["max_daily_trades"]:
            return False, f"超过每日交易次数 {LIMITS_CONFIG['max_daily_trades']}"
        
        # 检查每日交易量
        if self.state["daily_volume"] + amount > LIMITS_CONFIG["max_daily_volume"]:
            return False, f"超过每日交易量 ${LIMITS_CONFIG['max_daily_volume']:.2f}"
        
        # 检查总仓位
        if self.state["total_exposure"] + amount > LIMITS_CONFIG["max_total_exposure"]:
            return False, f"超过总仓位限制 ${LIMITS_CONFIG['max_total_exposure']:.2f}"
        
        # 检查余额
        if balance is not None:
            if balance < LIMITS_CONFIG["min_balance_required"]:
                return False, f"余额不足 ${LIMITS_CONFIG['min_balance_required']:.2f}"
            if amount > balance * LIMITS_CONFIG["max_position_pct"]:
                return False, f"超过仓位比例 {LIMITS_CONFIG['max_position_pct']:.0%}"
        
        return True, "允许交易"
    
    def record_trade(self, amount):
        """记录交易"""
        self._reset_daily()
        
        self.state["daily_trades"] += 1
        self.state["daily_volume"] += amount
        self.state["total_exposure"] += amount
        
        self._save_state()
    
    def record_close(self, amount):
        """记录平仓"""
        self.state["total_exposure"] = max(0, self.state["total_exposure"] - amount)
        self._save_state()
    
    def get_status(self):
        """获取状态"""
        self._reset_daily()
        
        return {
            "daily_trades": self.state["daily_trades"],
            "daily_volume": self.state["daily_volume"],
            "total_exposure": self.state["total_exposure"],
            "max_daily_trades": LIMITS_CONFIG["max_daily_trades"],
            "max_daily_volume": LIMITS_CONFIG["max_daily_volume"],
            "max_total_exposure": LIMITS_CONFIG["max_total_exposure"],
        }

# 全局实例
limiter = TradeLimiter()

def check_trade_allowed(amount, balance=None):
    """检查是否允许交易"""
    return limiter.can_trade(amount, balance)

def record_trade(amount):
    """记录交易"""
    limiter.record_trade(amount)

def record_close(amount):
    """记录平仓"""
    limiter.record_close(amount)

def get_limits_status():
    """获取限额状态"""
    return limiter.get_status()

def format_limits_report():
    """格式化限额报告"""
    status = get_limits_status()
    
    lines = []
    lines.append("📊 交易限额状态")
    lines.append("=" * 40)
    lines.append(f"今日交易: {status['daily_trades']}/{status['max_daily_trades']}")
    lines.append(f"今日交易量: ${status['daily_volume']:.2f}/${status['max_daily_volume']:.2f}")
    lines.append(f"总仓位: ${status['total_exposure']:.2f}/${status['max_total_exposure']:.2f}")
    
    return "\n".join(lines)

if __name__ == "__main__":
    print("=" * 50)
    print("交易限额测试")
    print("=" * 50)
    
    # 测试1: 正常交易
    print("\n1. 正常交易检查:")
    allowed, reason = check_trade_allowed(5.0, 100.0)
    print(f"   $5.00 交易: {'允许' if allowed else '拒绝'} - {reason}")
    
    # 测试2: 超过单笔限额
    print("\n2. 超过单笔限额:")
    allowed, reason = check_trade_allowed(15.0, 100.0)
    print(f"   $15.00 交易: {'允许' if allowed else '拒绝'} - {reason}")
    
    # 测试3: 记录交易
    print("\n3. 记录交易:")
    for i in range(3):
        record_trade(5.0)
        print(f"   交易 #{i+1} 已记录")
    
    print(f"\n{format_limits_report()}")
    
    print("\n✅ 交易限额测试完成")
