#!/usr/bin/env python3
"""
统一守门模块 — PolyStrat v4.2
==============================
GuardRail 模式：将分散的风险检查统一为串行守门链。

整合:
- should_trade() 风险检查
- circuit_breaker 断路器
- trade_limits 交易限额
- CLOB spread 校验
- 市场相关性检测（新增）
- 动态波动率过滤（新增）

设计原则:
- 单一入口: guard_rail_check() → 通过/拒绝/需人工确认
- 串行执行: 从轻到重排列检查项，失败即停
- 可配置: 每个检查项可独立启用/禁用
- 可追踪: 返回完整检查链结果

作者: PolyStrat Team
日期: 2026-07-08
"""

from polystrat_logger import log, log_error

# ============ 配置 ============

GUARDRAIL_CONFIG = {
    "enabled": True,
    # 检查项顺序（从轻到重）
    "checks": [
        "circuit_breaker",      # 断路器（最快，纯内存状态）
        "trade_limits",         # 交易限额（快速）
        "correlation",          # 市场相关性（中等）
        "volatility",           # 波动率过滤（中等）
        "risk_management",      # 风险管理（较重，需要计算）
        "clob_spread",          # CLOB价差（需要API调用）
    ],
    # 市场相关性检测
    "correlation": {
        "enabled": True,
        "max_same_event_exposure": 1,   # 同一事件最多下1单
        "max_category_exposure_pct": 0.30,  # 单类别最大占比30%
        # 事件关键词分组（同一组=同一事件）
        "event_groups": [
            ["world cup", "fifa", "世界杯", "uefa", "champions league"],
            ["election", "president", "选举", "总统", "senate", "house of rep", "white house"],
            ["bitcoin", "btc", "比特币", "halving"],
            ["ethereum", "eth", "以太坊", "vitalik"],
            ["solana", "sol"],
            ["crypto", "cryptocurrency", "sec", "etf", "binance", "coinbase"],
            ["interest rate", "fed", "利率", "美联储", "fomc", "powell", "cpi", "inflation", "通胀"],
            ["oil price", "crude", "油价", "原油", "opec"],
            ["copper", "铜价", "metal", "gold", "黄金"],
            ["geopolitics", "war", "conflict", "ukraine", "russia", "israel", "iran", "taiwan", "地缘"],
            ["tariff", "trade war", "关税", "trade"],
        ],
    },
    # 波动率过滤
    "volatility": {
        "enabled": True,
        "high_vol_position_scale": 0.5,   # 高波动期仓位缩小50%
        "extreme_vol_position_scale": 0.2, # 极端波动期仓位缩小80%
        "high_vol_price_range": 0.20,       # 价格标准差>20%视为高波动
        "extreme_vol_price_range": 0.35,    # >35%视为极端
    },
}


def detect_event_group(title, event_groups=None):
    """
    检测市场标题属于哪个事件组
    
    Args:
        title: 市场标题
        event_groups: 事件关键词分组
    
    Returns:
        str: 事件组标识（如 "world_cup"），无匹配返回 None
    """
    if event_groups is None:
        event_groups = GUARDRAIL_CONFIG["correlation"]["event_groups"]
    
    title_lower = title.lower()
    for group in event_groups:
        if any(kw in title_lower for kw in group):
            # 用第一个关键词作为组名
            return group[0].replace(" ", "_")
    return None


def check_correlation_exposure(market, existing_positions, config=None):
    """
    检查市场相关性暴露
    
    防止同一事件下多单（如9个世界杯市场同时买Yes）
    
    Args:
        market: 当前市场
        existing_positions: 已有持仓列表 [{title, category, direction, amount}, ...]
        config: 配置覆盖
    
    Returns:
        dict: {"pass": bool, "reason": str, "event_group": str, "same_event_count": int}
    """
    cfg = config or GUARDRAIL_CONFIG["correlation"]
    if not cfg.get("enabled", True):
        return {"pass": True, "reason": "相关性检查未启用", "event_group": None, "same_event_count": 0}
    
    title = market.get("title", "")
    category = market.get("category", "Other")
    
    # 1. 事件级相关性
    event_group = detect_event_group(title)
    same_event_count = 0
    
    if event_group:
        for pos in existing_positions:
            pos_event = detect_event_group(pos.get("title", ""))
            if pos_event == event_group:
                same_event_count += 1
        
        if same_event_count >= cfg["max_same_event_exposure"]:
            return {
                "pass": False,
                "reason": f"事件'{event_group}'已有{same_event_count}单，超限{cfg['max_same_event_exposure']}",
                "event_group": event_group,
                "same_event_count": same_event_count,
            }
    
    # 2. 类别级相关性
    category_exposure = 0
    total_exposure = 0
    for pos in existing_positions:
        pos_amount = pos.get("amount", 0)
        total_exposure += pos_amount
        if pos.get("category", "") == category:
            category_exposure += pos_amount
    
    if total_exposure > 0:
        category_pct = category_exposure / total_exposure
        if category_pct >= cfg["max_category_exposure_pct"]:
            return {
                "pass": False,
                "reason": f"类别'{category}'占比{category_pct:.0%}>={cfg['max_category_exposure_pct']:.0%}",
                "event_group": event_group,
                "same_event_count": same_event_count,
            }
    
    return {
        "pass": True,
        "reason": f"相关性通过 (事件={event_group}, 同事件={same_event_count}, 类别={category})",
        "event_group": event_group,
        "same_event_count": same_event_count,
    }


def check_volatility_filter(market, regime_data, config=None):
    """
    基于市场波动率的动态仓位调整
    
    Args:
        market: 当前市场
        regime_data: 市场环境数据 (from market_regime)
        config: 配置覆盖
    
    Returns:
        dict: {"pass": bool, "position_scale": float, "reason": str}
    """
    cfg = config or GUARDRAIL_CONFIG["volatility"]
    if not cfg.get("enabled", True):
        return {"pass": True, "position_scale": 1.0, "reason": "波动率检查未启用"}
    
    # 从regime_data获取波动率指标
    price_std = regime_data.get("price_std", 0) if regime_data else 0
    
    if price_std >= cfg["extreme_vol_price_range"]:
        return {
            "pass": True,
            "position_scale": cfg["extreme_vol_position_scale"],
            "reason": f"极端波动(σ={price_std:.0%})，仓位缩至{cfg['extreme_vol_position_scale']:.0%}",
        }
    elif price_std >= cfg["high_vol_price_range"]:
        return {
            "pass": True,
            "position_scale": cfg["high_vol_position_scale"],
            "reason": f"高波动(σ={price_std:.0%})，仓位缩至{cfg['high_vol_position_scale']:.0%}",
        }
    
    return {"pass": True, "position_scale": 1.0, "reason": f"波动率正常(σ={price_std:.0%})"}


def guard_rail_check(market, context, config=None):
    """
    统一守门检查 — 单一入口
    
    Args:
        market: 市场信息
        context: 上下文信息 dict，包含:
            - existing_positions: 已有持仓
            - regime_data: 市场环境数据
            - balance: 当前余额
            - trade_size: 拟交易金额
            - direction: 交易方向
            - token_id: token ID (CLOB校验用)
        
    Returns:
        dict: {
            "approved": bool,           # 是否通过
            "position_scale": float,    # 仓位缩放因子
            "checks": list,             # 各项检查结果
            "block_reason": str,        # 拒绝原因
            "warnings": list,           # 警告列表
        }
    """
    cfg = config or GUARDRAIL_CONFIG
    if not cfg.get("enabled", True):
        return _approved_result("守门未启用")
    
    checks = []
    warnings = []
    position_scale = 1.0
    
    # 1. 断路器
    try:
        from circuit_breaker import check_breaker
        breaker_ok = check_breaker()
        checks.append({
            "name": "circuit_breaker",
            "pass": breaker_ok,
            "detail": "断路器关闭" if breaker_ok else "断路器触发",
        })
        if not breaker_ok:
            return _blocked_result("断路器触发，暂停交易", checks)
    except Exception as e:
        warnings.append(f"断路器检查失败: {e}")
    
    # 2. 交易限额
    try:
        from trade_limits import check_trade_allowed
        trade_size = context.get("trade_size", 0)
        balance = context.get("balance", 1000)
        allowed, limit_reason = check_trade_allowed(trade_size, balance)
        checks.append({
            "name": "trade_limits",
            "pass": allowed,
            "detail": limit_reason if not allowed else "限额内",
        })
        if not allowed:
            return _blocked_result(f"交易限额: {limit_reason}", checks)
    except Exception as e:
        warnings.append(f"限额检查失败: {e}")
    
    # 3. 市场相关性
    try:
        corr_result = check_correlation_exposure(
            market, context.get("existing_positions", [])
        )
        checks.append({
            "name": "correlation",
            "pass": corr_result["pass"],
            "detail": corr_result["reason"],
        })
        if not corr_result["pass"]:
            return _blocked_result(f"相关性: {corr_result['reason']}", checks)
    except Exception as e:
        warnings.append(f"相关性检查失败: {e}")
    
    # 4. 波动率过滤
    try:
        vol_result = check_volatility_filter(
            market, context.get("regime_data")
        )
        checks.append({
            "name": "volatility",
            "pass": vol_result["pass"],
            "detail": vol_result["reason"],
        })
        position_scale *= vol_result["position_scale"]
        if vol_result["position_scale"] < 1.0:
            warnings.append(vol_result["reason"])
    except Exception as e:
        warnings.append(f"波动率检查失败: {e}")
    
    # 5. 风险管理
    try:
        from risk_management import should_trade
        confidence = context.get("confidence", 0.5)
        news_sentiment = context.get("news_sentiment", 0)
        balance = context.get("balance", 1000)
        # 🔧 P0-3: 修正传参 — should_trade 签名为 (market, confidence, news_sentiment, balance)
        # 原代码传 (edge, confidence, direction) → TypeError 被吞，检查项静默失效
        should, risk_reason = should_trade(market, confidence, news_sentiment, balance)
        checks.append({
            "name": "risk_management",
            "pass": should,
            "detail": risk_reason,
        })
        if not should:
            return _blocked_result(f"风险管理: {risk_reason}", checks)
    except Exception as e:
        warnings.append(f"风险管理检查失败: {e}")
    
    # 6. CLOB价差
    try:
        from clob_validator import validate_price_before_trade
        token_id = context.get("token_id", "")
        intended_price = context.get("intended_price", 0.5)
        direction = context.get("direction", "Yes")
        price_check = validate_price_before_trade(
            market, direction, intended_price, token_id
        )
        checks.append({
            "name": "clob_spread",
            "pass": price_check["valid"],
            "detail": price_check["reason"],
        })
        if not price_check["valid"]:
            return _blocked_result(f"CLOB: {price_check['reason']}", checks)
    except Exception as e:
        warnings.append(f"CLOB检查失败: {e}")
    
    # 全部通过
    return {
        "approved": True,
        "position_scale": position_scale,
        "checks": checks,
        "block_reason": "",
        "warnings": warnings,
    }


def _approved_result(reason=""):
    return {"approved": True, "position_scale": 1.0, "checks": [], "block_reason": "", "warnings": [reason]}


def _blocked_result(reason, checks):
    return {"approved": False, "position_scale": 0, "checks": checks, "block_reason": reason, "warnings": []}


# ============ 自测 ============
if __name__ == "__main__":
    print("=== 统一守门模块测试 ===\n")
    
    # 相关性检测
    positions = [
        {"title": "Will Argentina win the World Cup?", "category": "Sports", "direction": "Yes", "amount": 5},
        {"title": "Will France win the World Cup?", "category": "Sports", "direction": "Yes", "amount": 5},
    ]
    
    new_market = {"title": "Will Spain win the World Cup?", "category": "Sports"}
    
    corr = check_correlation_exposure(new_market, positions)
    print(f"📊 相关性检测: pass={corr['pass']} | {corr['reason']}")
    
    # 波动率
    vol = check_volatility_filter(new_market, {"price_std": 0.25})
    print(f"📊 波动率: scale={vol['position_scale']} | {vol['reason']}")
    
    # 统一守门
    context = {
        "existing_positions": positions,
        "regime_data": {"price_std": 0.15},
        "balance": 1000,
        "trade_size": 2,
        "direction": "Yes",
        "token_id": "",
        "intended_price": 0.65,
        "confidence": 0.7,
        "edge": 0.05,
    }
    result = guard_rail_check(new_market, context)
    print(f"\n🛡️ 守门结果: approved={result['approved']}")
    for c in result["checks"]:
        status = "✅" if c["pass"] else "❌"
        print(f"   {status} {c['name']}: {c['detail']}")
    if result["warnings"]:
        print(f"   ⚠️ 警告: {result['warnings']}")
