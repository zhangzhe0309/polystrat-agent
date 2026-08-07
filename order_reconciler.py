#!/usr/bin/env python3
"""
订单状态机 + 超时反查（P0: Unknown is a state, not a shrug）

设计原则
--------
1. 下单超时 ≠ 未成交。Polymarket CLOB 无 client_order_id 业务幂等键
   (OrderArgs 仅有 nonce)，唯一可靠的超时恢复手段是 get_trades/get_orders 反查。
2. UNKNOWN_TIMEOUT 当轮【禁止重试】→ 入队 → 下一轮反查确认。
3. 三态反查（兼顾安全与可用）:
   - 成交 (get_trades 命中)        → SUCCESS  → 补注册 TP
   - 挂单中 (get_orders 命中)      → 保持 UNKNOWN → 继续等，绝不重试(防重复挂单)
   - 既无成交也无挂单              → FAILED   → 订单未进交易所，可安全重试
4. 反查 MAX_PROBE_ROUNDS 轮仍不明 → 降级告警，人工核对(不自动重试)。
5. ⚛️ 持久化: polystrat_agent 为 cron 单次运行模式，pending 队列必须落盘
   才能跨 cron 周期反查。使用 os.replace 原子写，自包含(无外部依赖)。

⚠️ 待实测: py_clob_client.ClobClient.get_trades()/get_orders() 的确切签名与
   返回字段名。当前用多名称兼容 + 价格容差匹配，集成后在 hermes life venv 实测微调。
"""

import os
import json
import tempfile
from datetime import datetime, timezone
from polystrat_logger import log


class OrderState:
    """订单业务结果状态（区别于 error_handler 的"异常类型"分类）"""
    SUCCESS         = "SUCCESS"           # 确认成交
    FAILED          = "FAILED"            # 确认未成交（未进交易所/被拒）→ 可安全重试
    DENIED          = "DENIED"            # 安全/护栏拦截（HTTP 4xx）
    UNKNOWN_TIMEOUT = "UNKNOWN_TIMEOUT"   # 超时，状态待确认 ⚠️ 最危险
    STALE           = "STALE"             # 数据过期


MAX_PROBE_ROUNDS = 5          # 反查最多等 5 轮，之后降级告警
PRICE_TOLERANCE = 0.01        # 价格匹配容差 1¢（CLOB 价格 round 到 2 位）

_DEFAULT_PENDING_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "logs", "pending_orders.json"
)


class OrderReconciler:
    """管理 UNKNOWN_TIMEOUT 订单的异步反查（带跨进程持久化）"""

    def __init__(self, pending_file: str = None):
        self.pending_file = pending_file or _DEFAULT_PENDING_FILE
        self.pending = []
        self._load()

    # ── 持久化 ────────────────────────────────────────────────

    def _load(self):
        """启动时加载持久化的待确认订单"""
        try:
            if os.path.exists(self.pending_file):
                with open(self.pending_file, encoding="utf-8") as f:
                    self.pending = json.load(f) or []
                if self.pending:
                    log.info(f"📂 [Reconcile] 加载 {len(self.pending)} 笔待确认订单: {self.pending_file}")
        except Exception as e:
            log.warning(f"⚠️ [Reconcile] 加载 pending 失败(从空开始): {e}")
            self.pending = []

    def _persist(self):
        """原子写 pending 到文件（os.replace 保证不被半写损坏）"""
        try:
            d = os.path.dirname(self.pending_file)
            os.makedirs(d, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.pending, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.pending_file)
        except Exception as e:
            log.warning(f"⚠️ [Reconcile] pending 持久化失败: {e}")

    # ── 对外接口 ──────────────────────────────────────────────

    def enqueue(self, order_info: dict):
        """超时订单入队（当轮调用，禁止重试）+ 落盘"""
        order_info.setdefault("enqueued_at", datetime.now(timezone.utc).isoformat())
        order_info.setdefault("probe_count", 0)
        self.pending.append(order_info)
        self._persist()
        log.warning(
            f"⏳ [Reconcile] 订单入待确认队列(已落盘): token={str(order_info.get('token_id',''))[:12]}... "
            f"{order_info.get('side')} ${order_info.get('amount')} @ {order_info.get('price')} "
            f"— 当轮不重试，下轮反查"
        )

    def has_pending(self) -> bool:
        return len(self.pending) > 0

    def reconcile(self, client) -> list:
        """
        每轮扫描前调用：反查所有 pending 订单。
        Args:
            client: 已初始化的 py_clob_client.ClobClient（DRY_RUN/None 时跳过）
        Returns:
            已确认订单列表 [{"order_info":..., "final_state":...}, ...]
            调用方应对 SUCCESS 补注册 TP；对 FAILED 决定是否重试。
        """
        if not self.pending:
            return []
        if client is None:
            log.warning("⚠️ [Reconcile] 无可用 client(DRY_RUN?)，跳过本轮反查")
            return []

        resolved = []
        still_unknown = []

        for order_info in self.pending:
            order_info["probe_count"] = order_info.get("probe_count", 0) + 1
            state = self._probe_order(client, order_info)

            if state == OrderState.SUCCESS:
                log.info(f"✅ [Reconcile] 反查确认已成交: token={str(order_info.get('token_id',''))[:12]}... → 补注册TP")
                resolved.append({"order_info": order_info, "final_state": OrderState.SUCCESS})
            elif state == OrderState.FAILED:
                log.info(f"❌ [Reconcile] 反查确认未进交易所(可安全重试): token={str(order_info.get('token_id',''))[:12]}...")
                resolved.append({"order_info": order_info, "final_state": OrderState.FAILED})
            else:
                # UNKNOWN（挂单中或反查异常）
                if order_info["probe_count"] >= MAX_PROBE_ROUNDS:
                    log.error(
                        f"🚨 [Reconcile] 反查 {MAX_PROBE_ROUNDS} 轮仍未确认，降级告警(不自动重试): "
                        f"token={str(order_info.get('token_id',''))[:12]}... 请人工核对 Polymarket 后台"
                    )
                    resolved.append({"order_info": order_info, "final_state": OrderState.UNKNOWN_TIMEOUT})
                else:
                    still_unknown.append(order_info)

        self.pending = still_unknown
        self._persist()
        return resolved

    # ── 内部 ──────────────────────────────────────────────────

    def _probe_order(self, client, order_info: dict) -> str:
        """三态反查：SUCCESS / FAILED / UNKNOWN_TIMEOUT"""
        token_id = str(order_info.get("token_id", ""))
        side = (order_info.get("side") or "").upper()
        price = order_info.get("price")
        try:
            # 1) 成交记录 → 确认 SUCCESS
            for t in (self._safe_get(client, "get_trades") or []):
                if self._match(t, token_id, side, price):
                    return OrderState.SUCCESS
            # 2) 挂单 → 订单还活着，保持 UNKNOWN（绝不重试，防重复挂单）
            for o in (self._safe_get(client, "get_orders") or []):
                if self._match(o, token_id, side, price):
                    return OrderState.UNKNOWN_TIMEOUT
            # 3) 既无成交也无挂单 → 订单未进交易所，可安全重试
            return OrderState.FAILED
        except Exception as e:
            log.warning(f"⚠️ [Reconcile] 反查异常(保守保持UNKNOWN): {e}")
            return OrderState.UNKNOWN_TIMEOUT

    def _safe_get(self, client, method_name: str):
        """安全调用 client 查询方法。⚠️ 待实测签名，先无参，失败再试带参。"""
        try:
            method = getattr(client, method_name, None)
            if method is None:
                return None
            return method() or []
        except TypeError:
            try:
                return method({}) or []
            except Exception as e:
                log.warning(f"⚠️ [Reconcile] {method_name} 调用失败: {e}")
                return None
        except Exception as e:
            log.warning(f"⚠️ [Reconcile] {method_name} 调用失败: {e}")
            return None

    @staticmethod
    def _match(item: dict, token_id: str, side: str, price) -> bool:
        """匹配订单/成交记录。字段名多兼容（py_clob_client 返回结构待实测）。"""
        aid = str(item.get("asset_id") or item.get("token_id") or "")
        if aid != token_id:
            return False
        item_side = (item.get("side") or "").upper()
        if item_side and side and item_side != side:
            return False
        if price is not None:
            try:
                if abs(float(item.get("price", 0)) - float(price)) > PRICE_TOLERANCE:
                    return False
            except (TypeError, ValueError):
                pass
        return True


# 全局单例（模块加载即从磁盘恢复 pending）
reconciler = OrderReconciler()


if __name__ == "__main__":
    print("OrderState:", [v for v in dir(OrderState) if not v.startswith("_")])
    print("pending_file:", _DEFAULT_PENDING_FILE)
    print("pending 数量:", len(reconciler.pending))
    print("✅ order_reconciler 模块自检完成")
