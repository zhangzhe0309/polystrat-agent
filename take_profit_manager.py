#!/usr/bin/env python3
"""
阶梯止盈管理器 (Take-Profit Manager)
集成自 KongTradeBot 的 40/40/15/5 阶梯模型 + Whale-Exit 尾随

KongTradeBot 核心洞察:
- Bot 的 Edge 是 Momentum-Capture，不是 Prediction
- Weather/Geopolitik 类别预测率仅 22.7% 但产生 +$2632 PnL
- TP-Exit 在 Resolution 之前退出，锁定利润

阶梯模型:
  TP1: Entry + 10% → 退出 40% 仓位
  TP2: Entry + 25% → 退出 40% 仓位  
  TP3: Entry + 50% → 退出 15% 仓位
  Whale-Exit: 鲸鱼卖出时 → 退出剩余 5%

使用方式:
    tp_manager = TakeProfitManager()
    tp_manager.add_position(position_id, entry_price, size_usdc, source_wallet)
    
    # 定期检查
    exits = tp_manager.check_take_profits(current_prices)
    for exit_signal in exits:
        execute_sell(exit_signal)
"""

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from collections import deque

# ── 阶梯配置 ──────────────────────────────────────────────────────

# 默认阶梯 (KongTradeBot 实际使用的 40/40/15/5 模型)
DEFAULT_TP_LADDER = [
    {"stage": "TP1", "trigger_pct": 0.10, "exit_pct": 0.40, "description": "Entry + 10% → 退出 40%"},
    {"stage": "TP2", "trigger_pct": 0.25, "exit_pct": 0.40, "description": "Entry + 25% → 退出 40%"},
    {"stage": "TP3", "trigger_pct": 0.50, "exit_pct": 0.15, "description": "Entry + 50% → 退出 15%"},
]

# 保守阶梯 (适用于高不确定性市场)
CONSERVATIVE_TP_LADDER = [
    {"stage": "TP1", "trigger_pct": 0.08, "exit_pct": 0.50, "description": "Entry + 8% → 退出 50%"},
    {"stage": "TP2", "trigger_pct": 0.15, "exit_pct": 0.30, "description": "Entry + 15% → 退出 30%"},
    {"stage": "TP3", "trigger_pct": 0.30, "exit_pct": 0.15, "description": "Entry + 30% → 退出 15%"},
]

# 激进阶梯 (适用于高确定性市场)
AGGRESSIVE_TP_LADDER = [
    {"stage": "TP1", "trigger_pct": 0.15, "exit_pct": 0.30, "description": "Entry + 15% → 退出 30%"},
    {"stage": "TP2", "trigger_pct": 0.40, "exit_pct": 0.40, "description": "Entry + 40% → 退出 40%"},
    {"stage": "TP3", "trigger_pct": 0.80, "exit_pct": 0.20, "description": "Entry + 80% → 退出 20%"},
]

# 类别 → 阶梯映射
CATEGORY_LADDER_MAP = {
    "Weather": DEFAULT_TP_LADDER,
    "Geopolitik": CONSERVATIVE_TP_LADDER,
    "Sport": CONSERVATIVE_TP_LADDER,
    "Crypto": AGGRESSIVE_TP_LADDER,
    "Makro": DEFAULT_TP_LADDER,
    "default": DEFAULT_TP_LADDER,
}

# 止损配置
STOP_LOSS_PCT = -0.10      # -10% 止损
TRAILING_STOP_PCT = 0.05   # 5% 追踪止损 (在 TP1 触发后激活)
MAX_HOLD_HOURS = 72        # 最大持仓时间 (KongTradeBot 的 24-72h 策略)


@dataclass
class Position:
    """持仓信息"""
    position_id: str
    market_id: str
    token_id: str
    outcome: str
    market_question: str
    
    entry_price: float
    size_usdc: float
    shares: float
    
    source_wallet: str = ""
    category: str = ""
    opened_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    market_closes_at: Optional[datetime] = None
    
    # 止盈状态
    tp_stage: int = 0         # 当前阶梯 (0=未触发, 1=TP1, 2=TP2, 3=TP3)
    remaining_pct: float = 1.0  # 剩余仓位比例
    highest_price: float = 0.0  # 最高价 (用于追踪止损)
    tp1_triggered: bool = False
    
    # 鲸鱼退出
    whale_exit_detected: bool = False
    
    @property
    def current_value_usdc(self) -> float:
        return self.shares * self.entry_price * self.remaining_pct
    
    @property
    def hours_held(self) -> float:
        return (datetime.now(timezone.utc) - self.opened_at).total_seconds() / 3600
    
    @property
    def time_to_close_hours(self) -> Optional[float]:
        if not self.market_closes_at:
            return None
        delta = self.market_closes_at - datetime.now(timezone.utc)
        return max(0, delta.total_seconds() / 3600)


@dataclass
class ExitSignal:
    """退出信号"""
    position_id: str
    stage: str               # "TP1", "TP2", "TP3", "STOP_LOSS", "TRAILING_STOP", "WHALE_EXIT", "TIME_EXIT"
    exit_pct: float          # 退出比例
    exit_price: float
    exit_size_usdc: float
    pnl_usd: float
    reason: str
    urgency: str = "medium"  # "high", "medium", "low"


class TakeProfitManager:
    """
    阶梯止盈管理器
    
    功能:
    1. 阶梯止盈 (TP1/TP2/TP3)
    2. 追踪止损 (TP1 后激活)
    3. 固定止损 (-10%)
    4. 鲸鱼退出跟随
    5. 时间止损 (超时强制退出)
    """
    
    def __init__(self, data_dir: str = None):
        self.positions: Dict[str, Position] = {}
        self.exit_history: List[dict] = []
        
        # 持久化
        from config_center import TP_MANAGER_DIR; self.data_dir = Path(data_dir) if data_dir else TP_MANAGER_DIR
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._load_state()
    
    def add_position(
        self,
        position_id: str,
        entry_price: float,
        size_usdc: float,
        source_wallet: str = "",
        market_id: str = "",
        token_id: str = "",
        outcome: str = "",
        market_question: str = "",
        category: str = "",
        market_closes_at: Optional[datetime] = None,
    ) -> Position:
        """添加新持仓"""
        position = Position(
            position_id=position_id,
            market_id=market_id,
            token_id=token_id,
            outcome=outcome,
            market_question=market_question,
            entry_price=entry_price,
            size_usdc=size_usdc,
            shares=size_usdc / entry_price if entry_price > 0 else 0,
            source_wallet=source_wallet,
            category=category,
            market_closes_at=market_closes_at,
            highest_price=entry_price,
        )
        self.positions[position_id] = position
        self._save_state()
        return position
    
    def check_take_profits(self, current_prices: Dict[str, float]) -> List[ExitSignal]:
        """
        检查所有持仓的止盈条件
        
        Args:
            current_prices: {position_id: current_price} 或 {token_id: current_price}
        
        Returns:
            退出信号列表
        """
        exit_signals = []
        
        for pos_id, position in list(self.positions.items()):
            # 查找当前价格
            current_price = current_prices.get(pos_id) or current_prices.get(position.token_id)
            if not current_price or current_price <= 0:
                continue
            
            # 更新最高价
            if current_price > position.highest_price:
                position.highest_price = current_price
            
            # 获取适用的阶梯
            ladder = CATEGORY_LADDER_MAP.get(position.category, CATEGORY_LADDER_MAP["default"])
            
            # 检查各阶梯
            for i, step in enumerate(ladder):
                if i < position.tp_stage:
                    continue  # 已触发
                
                trigger_price = position.entry_price * (1 + step["trigger_pct"])
                if current_price >= trigger_price:
                    signal = ExitSignal(
                        position_id=pos_id,
                        stage=step["stage"],
                        exit_pct=step["exit_pct"] * position.remaining_pct,
                        exit_price=current_price,
                        exit_size_usdc=position.size_usdc * step["exit_pct"] * position.remaining_pct,
                        pnl_usd=self._calculate_pnl(position, current_price, step["exit_pct"] * position.remaining_pct),
                        reason=f"{step['description']} @ ${current_price:.4f}",
                        urgency="high" if step["trigger_pct"] >= 0.25 else "medium",
                    )
                    exit_signals.append(signal)
                    
                    # 更新状态
                    position.remaining_pct -= step["exit_pct"] * position.remaining_pct
                    position.tp_stage = i + 1
                    if step["stage"] == "TP1":
                        position.tp1_triggered = True
            
            # 检查止损
            loss_pct = (current_price - position.entry_price) / position.entry_price
            if loss_pct <= STOP_LOSS_PCT:
                signal = ExitSignal(
                    position_id=pos_id,
                    stage="STOP_LOSS",
                    exit_pct=position.remaining_pct,
                    exit_price=current_price,
                    exit_size_usdc=position.size_usdc * position.remaining_pct,
                    pnl_usd=self._calculate_pnl(position, current_price, position.remaining_pct),
                    reason=f"止损触发: {loss_pct:.1%} < {STOP_LOSS_PCT:.0%}",
                    urgency="high",
                )
                exit_signals.append(signal)
                position.remaining_pct = 0
            
            # 追踪止损 (TP1 后激活)
            elif position.tp1_triggered and position.highest_price > position.entry_price:
                trailing_stop_price = position.highest_price * (1 - TRAILING_STOP_PCT)
                if current_price <= trailing_stop_price:
                    signal = ExitSignal(
                        position_id=pos_id,
                        stage="TRAILING_STOP",
                        exit_pct=position.remaining_pct,
                        exit_price=current_price,
                        exit_size_usdc=position.size_usdc * position.remaining_pct,
                        pnl_usd=self._calculate_pnl(position, current_price, position.remaining_pct),
                        reason=f"追踪止损: ${current_price:.4f} <= ${trailing_stop_price:.4f} (最高: ${position.highest_price:.4f})",
                        urgency="high",
                    )
                    exit_signals.append(signal)
                    position.remaining_pct = 0
            
            # 时间止损
            if position.hours_held > MAX_HOLD_HOURS and position.remaining_pct > 0:
                signal = ExitSignal(
                    position_id=pos_id,
                    stage="TIME_EXIT",
                    exit_pct=position.remaining_pct,
                    exit_price=current_price,
                    exit_size_usd=position.size_usdc * position.remaining_pct,
                    pnl_usd=self._calculate_pnl(position, current_price, position.remaining_pct),
                    reason=f"超时退出: {position.hours_held:.1f}h > {MAX_HOLD_HOURS}h",
                    urgency="medium",
                )
                exit_signals.append(signal)
                position.remaining_pct = 0
        
        # 清理已完全退出的仓位
        closed = [pid for pid, pos in self.positions.items() if pos.remaining_pct <= 0.01]
        for pid in closed:
            self._archive_position(pid)
        
        if exit_signals:
            self._save_state()
        
        return exit_signals
    
    def handle_whale_exit(self, source_wallet: str, token_id: str, current_price: float) -> List[ExitSignal]:
        """
        处理鲸鱼退出信号
        
        当检测到源钱包卖出时，尾随退出剩余仓位
        
        Args:
            source_wallet: 鲸鱼钱包地址
            token_id: 卖出的 token
            current_price: 当前价格
        
        Returns:
            退出信号列表
        """
        exit_signals = []
        
        for pos_id, position in self.positions.items():
            if position.source_wallet.lower() != source_wallet.lower():
                continue
            if position.token_id != token_id:
                continue
            if position.remaining_pct <= 0.01:
                continue
            
            position.whale_exit_detected = True
            
            # 鲸鱼退出 → 退出剩余仓位 (5% 保留可忽略)
            signal = ExitSignal(
                position_id=pos_id,
                stage="WHALE_EXIT",
                exit_pct=position.remaining_pct,
                exit_price=current_price,
                exit_size_usdc=position.size_usdc * position.remaining_pct,
                pnl_usd=self._calculate_pnl(position, current_price, position.remaining_pct),
                reason=f"鲸鱼退出跟随: {source_wallet[:10]}... 卖出 {token_id[:12]}...",
                urgency="high",
            )
            exit_signals.append(signal)
            position.remaining_pct = 0
        
        return exit_signals
    
    def get_position_summary(self) -> List[dict]:
        """获取持仓摘要"""
        return [
            {
                "position_id": p.position_id[:12] + "...",
                "market": p.market_question[:50],
                "outcome": p.outcome,
                "entry_price": f"${p.entry_price:.4f}",
                "size_usdc": f"${p.size_usdc:.2f}",
                "remaining": f"{p.remaining_pct:.0%}",
                "tp_stage": p.tp_stage,
                "hours_held": f"{p.hours_held:.1f}h",
                "category": p.category,
            }
            for p in self.positions.values()
            if p.remaining_pct > 0.01
        ]
    
    def _calculate_pnl(self, position: Position, exit_price: float, exit_pct: float) -> float:
        """计算 PnL"""
        shares_to_sell = position.shares * exit_pct
        cost = shares_to_sell * position.entry_price
        revenue = shares_to_sell * exit_price
        return revenue - cost
    
    def _archive_position(self, position_id: str):
        """归档已关闭的仓位"""
        position = self.positions.pop(position_id, None)
        if position:
            self.exit_history.append({
                "position_id": position_id,
                "market": position.market_question[:80],
                "entry_price": position.entry_price,
                "size_usdc": position.size_usdc,
                "tp_stage_reached": position.tp_stage,
                "whale_exit": position.whale_exit_detected,
                "hours_held": position.hours_held,
                "closed_at": datetime.now(timezone.utc).isoformat(),
            })
            # 保留最近 1000 条
            if len(self.exit_history) > 1000:
                self.exit_history = self.exit_history[-1000:]
    
    def _save_state(self):
        """持久化状态"""
        try:
            state = {
                "positions": {
                    pid: {
                        "position_id": p.position_id,
                        "entry_price": p.entry_price,
                        "size_usdc": p.size_usdc,
                        "shares": p.shares,
                        "tp_stage": p.tp_stage,
                        "remaining_pct": p.remaining_pct,
                        "highest_price": p.highest_price,
                        "tp1_triggered": p.tp1_triggered,
                        "source_wallet": p.source_wallet,
                        "token_id": p.token_id,
                        "outcome": p.outcome,
                        "market_question": p.market_question,
                        "category": p.category,
                        "opened_at": p.opened_at.isoformat(),
                    }
                    for pid, p in self.positions.items()
                },
                "exit_history_count": len(self.exit_history),
            }
            filepath = self.data_dir / "tp_state.json"
            with open(filepath, "w") as f:
                json.dump(state, f, indent=2)
        except (OSError, IOError) as e:
            print(f"⚠️ TP状态保存失败: {e}")
    
    def _load_state(self):
        """加载状态"""
        filepath = self.data_dir / "tp_state.json"
        if not filepath.exists():
            return
        
        try:
            with open(filepath) as f:
                state = json.load(f)
            
            for pid, p_data in state.get("positions", {}).items():
                position = Position(
                    position_id=p_data["position_id"],
                    market_id=p_data.get("market_id", ""),
                    token_id=p_data.get("token_id", ""),
                    outcome=p_data.get("outcome", ""),
                    market_question=p_data.get("market_question", ""),
                    entry_price=p_data["entry_price"],
                    size_usdc=p_data["size_usdc"],
                    shares=p_data["shares"],
                    source_wallet=p_data.get("source_wallet", ""),
                    category=p_data.get("category", ""),
                    tp_stage=p_data.get("tp_stage", 0),
                    remaining_pct=p_data.get("remaining_pct", 1.0),
                    highest_price=p_data.get("highest_price", 0.0),
                    tp1_triggered=p_data.get("tp1_triggered", False),
                    opened_at=datetime.fromisoformat(p_data["opened_at"]) if p_data.get("opened_at") else datetime.now(timezone.utc),
                )
                self.positions[pid] = position
        except (json.JSONDecodeError, OSError) as e:
            print(f"⚠️ TP状态加载失败: {e}")


if __name__ == "__main__":
    print("=" * 60)
    print("阶梯止盈管理器测试")
    print("=" * 60)
    
    tp = TakeProfitManager()
    
    # 添加测试仓位
    pos = tp.add_position(
        position_id="test_001",
        entry_price=0.40,
        size_usdc=100.0,
        source_wallet="0x019782cab5d844f02bafb71f512758be78579f3c",
        market_question="Will it rain in NYC tomorrow?",
        category="Weather",
    )
    print(f"\n📊 添加仓位: {pos.market_question}")
    print(f"   Entry: ${pos.entry_price:.2f}, Size: ${pos.size_usdc:.2f}")
    
    # 模拟价格变动
    price_scenarios = [
        ("0.42", 0.42, "小幅上涨"),
        ("0.44", 0.44, "TP1 触发 (+10%)"),
        ("0.50", 0.50, "TP2 触发 (+25%)"),
        ("0.60", 0.60, "TP3 触发 (+50%)"),
    ]
    
    for label, price, desc in price_scenarios:
        exits = tp.check_take_profits({"test_001": price})
        print(f"\n💰 价格: ${price} ({desc})")
        for ex in exits:
            print(f"   {ex.stage}: 退出 {ex.exit_pct:.0%} @ ${ex.exit_price:.4f}, PnL: ${ex.pnl_usd:+.2f}")
    
    print(f"\n📊 剩余仓位: {pos.remaining_pct:.0%}")
    print("\n✅ 阶梯止盈管理器测试完成")
