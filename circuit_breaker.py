#!/usr/bin/env python3
"""
断路器模块
- 异常时自动停止交易
- 连续亏损保护
- 系统健康检查
"""

import json
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from polystrat_logger import log, log_error

# 状态文件
STATE_FILE = Path("/root/.hermes/profiles/life/data/circuit_breaker.json")
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

# 初始资金（从环境变量读取，与主程序保持一致）
INITIAL_BALANCE = float(os.environ.get("POLYSTRAT_BALANCE", "200.0"))

# 断路器配置（优化后：放宽触发条件，避免频繁触发）
BREAKER_CONFIG = {
    "max_consecutive_losses": 10,  # 最大连续亏损次数（放宽到10次）
    "max_daily_loss_pct": -0.20,  # 每日最大亏损比例（20%）
    "max_drawdown_pct": -0.30,  # 最大回撤比例（30%）
    "cooldown_minutes": 60,  # 冷却时间（分钟）（增加到60分钟）
    "auto_reset_hours": 24,  # 自动重置时间（小时）
}


class CircuitBreaker:
    """断路器"""

    def __init__(self):
        # 确保目录存在且权限正确
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.state = self._load_state()

    def _load_state(self):
        """加载状态（带文件锁）"""
        import fcntl

        try:
            if STATE_FILE.exists():
                with open(STATE_FILE, "r") as f:
                    fcntl.flock(f, fcntl.LOCK_SH)  # 共享锁
                    try:
                        return json.load(f)
                    finally:
                        fcntl.flock(f, fcntl.LOCK_UN)
        except:
            pass

        return {
            "status": "closed",  # closed = 正常, open = 断开, half_open = 半开
            "consecutive_losses": 0,
            "daily_pnl": 0.0,
            "total_pnl": 0.0,
            "last_loss_time": None,
            "open_since": None,
            "daily_reset_date": None,
        }

    def _save_state(self):
        """保存状态（原子写入+文件锁）"""
        import fcntl
        import tempfile

        try:
            # 先写入临时文件
            fd, tmp_path = tempfile.mkstemp(
                dir=str(STATE_FILE.parent), prefix=".tmp_", suffix=".json"
            )
            with os.fdopen(fd, "w") as tmp_file:
                json.dump(self.state, tmp_file, indent=2)

            # 原子重命名
            os.rename(tmp_path, str(STATE_FILE))

            # 设置权限
            os.chmod(str(STATE_FILE), 0o600)
        except Exception as e:
            log_error("breaker", e, "保存断路器状态失败")

    def _reset_daily(self):
        """每日重置"""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.state.get("daily_reset_date") != today:
            self.state["daily_pnl"] = 0.0
            self.state["daily_reset_date"] = today
            self._save_state()

    def is_open(self):
        """检查断路器是否断开"""
        self._reset_daily()

        if self.state["status"] == "closed":
            return False

        if self.state["status"] == "open":
            # 检查是否可以进入半开状态
            open_since = self.state.get("open_since")
            if open_since:
                open_time = datetime.fromisoformat(open_since)
                cooldown = timedelta(minutes=BREAKER_CONFIG["cooldown_minutes"])
                if datetime.now(timezone.utc) - open_time > cooldown:
                    self.state["status"] = "half_open"
                    self._save_state()
                    log.info("断路器进入半开状态")
                    return False
            return True

        # half_open 状态允许少量交易
        return False

    def record_trade(self, pnl):
        """记录交易结果"""
        self._reset_daily()

        self.state["daily_pnl"] += pnl
        self.state["total_pnl"] += pnl

        if pnl < 0:
            self.state["consecutive_losses"] += 1
            self.state["last_loss_time"] = datetime.now(timezone.utc).isoformat()
        else:
            self.state["consecutive_losses"] = 0
            # 盈利交易：如果当前是半开状态，恢复为 closed
            if self.state["status"] == "half_open":
                self.state["status"] = "closed"
                log.info("断路器已从 half_open 恢复为 closed（盈利交易）")

        # 检查是否需要断开
        should_trip = False
        reason = ""

        # 连续亏损检查
        if self.state["consecutive_losses"] >= BREAKER_CONFIG["max_consecutive_losses"]:
            should_trip = True
            reason = f"连续亏损 {self.state['consecutive_losses']} 次"

        # 每日亏损比例检查（基于初始资金）
        daily_loss_pct = self.state["daily_pnl"] / INITIAL_BALANCE
        if daily_loss_pct <= BREAKER_CONFIG["max_daily_loss_pct"]:
            should_trip = True
            reason = f"每日亏损 {daily_loss_pct:.1%}"

        # 总回撤比例检查
        total_drawdown_pct = self.state["total_pnl"] / INITIAL_BALANCE
        if total_drawdown_pct <= BREAKER_CONFIG["max_drawdown_pct"]:
            should_trip = True
            reason = f"总回撤 {total_drawdown_pct:.1%}"

        if should_trip:
            self._trip(reason)

        self._save_state()

    def _trip(self, reason):
        """触发断路器"""
        self.state["status"] = "open"
        self.state["open_since"] = datetime.now(timezone.utc).isoformat()
        log.warning(f"🚨 断路器触发: {reason}")

    def reset(self):
        """手动重置断路器（同时清除累计盈亏，防止重置后立即重新触发）"""
        self.state["status"] = "closed"
        self.state["consecutive_losses"] = 0
        self.state["open_since"] = None
        self.state["total_pnl"] = 0.0
        self.state["daily_pnl"] = 0.0
        self.state["daily_reset_date"] = None
        self._save_state()
        log.info("断路器已重置（含PnL清零）")

    def get_status(self):
        """获取状态"""
        self._reset_daily()

        return {
            "status": self.state["status"],
            "consecutive_losses": self.state["consecutive_losses"],
            "daily_pnl": self.state["daily_pnl"],
            "total_pnl": self.state["total_pnl"],
            "is_trading_allowed": not self.is_open(),
        }


# 全局断路器实例
breaker = CircuitBreaker()


def check_breaker():
    """检查断路器状态"""
    return not breaker.is_open()


def record_trade_result(pnl):
    """记录交易结果"""
    breaker.record_trade(pnl)


def get_breaker_status():
    """获取断路器状态"""
    return breaker.get_status()


def reset_breaker():
    """重置断路器"""
    breaker.reset()


def format_breaker_report():
    """格式化断路器报告"""
    status = get_breaker_status()

    lines = []
    lines.append("⚡ 断路器状态")
    lines.append("=" * 40)

    status_emoji = {"closed": "🟢 正常", "open": "🔴 断开", "half_open": "🟡 半开"}

    lines.append(f"状态: {status_emoji.get(status['status'], '未知')}")
    lines.append(f"连续亏损: {status['consecutive_losses']}")
    lines.append(f"今日盈亏: ${status['daily_pnl']:+.2f}")
    lines.append(f"总盈亏: ${status['total_pnl']:+.2f}")
    lines.append(f"允许交易: {'是' if status['is_trading_allowed'] else '否'}")

    return "\n".join(lines)


if __name__ == "__main__":
    print("=" * 50)
    print("断路器测试")
    print("=" * 50)

    # 重置断路器
    reset_breaker()

    # 测试1: 正常状态
    print("\n1. 正常状态:")
    print(format_breaker_report())

    # 测试2: 记录亏损
    print("\n2. 记录连续亏损:")
    for i in range(4):
        record_trade_result(-10)
        print(f"   亏损 #{i + 1}: {get_breaker_status()}")

    # 测试3: 触发断路器
    print("\n3. 触发断路器:")
    record_trade_result(-10)
    print(format_breaker_report())

    # 测试4: 重置
    print("\n4. 重置断路器:")
    reset_breaker()
    print(format_breaker_report())

    print("\n✅ 断路器测试完成")
