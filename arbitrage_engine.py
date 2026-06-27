"""
套利引擎模块 (基于 Arbiter 框架策略)
- Binary Dutch Book: 同一市场 YES+NO 价格之和 < 1 时套利
- Mutually-Exclusive Set: negRisk 多结果市场，所有 YES 价格之和 < 1 时套利
- Cross-Platform Signal: 跨平台价格差异检测

来源: github.com/nayrbryanGaming/arbiter (MIT)
适配: PolyStrat 架构 + Polymarket CLOB API
"""

import requests
import json
from datetime import datetime, timezone
from polystrat_logger import log, log_error

# Polymarket API
GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"

# 套利配置
ARBITRAGE_CONFIG = {
    "min_edge_pct": 0.02,       # 最小边际利润 2%（扣除费用后）
    "min_notional_usd": 10.0,   # 最小名义金额 $10
    "max_notional_usd": 100.0,  # 最大名义金额 $100（保守）
    "taker_fee": 0.02,          # Taker 费用 2%
    "min_completeness": 0.90,   # negRisk 组最低完整度
    "scan_limit": 200,          # 扫描市场数量
}


def get_orderbook(token_id):
    """
    获取订单簿数据

    Args:
        token_id: 代币 ID

    Returns:
        dict: {"bids": [...], "asks": [...]} 或 None
    """
    try:
        resp = requests.get(
            f"{CLOB_API}/book",
            params={"token_id": token_id},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        log_error("arbitrage", e, f"获取订单簿失败: {token_id[:20]}")
    return None


def best_ask(orderbook):
    """
    获取最优卖价和数量

    Args:
        orderbook: 订单簿数据

    Returns:
        tuple: (price, size) 或 None
    """
    if not orderbook:
        return None

    asks = orderbook.get("asks", [])
    if not asks:
        return None

    # 按价格排序，取最低卖价
    best = min(asks, key=lambda x: float(x.get("price", 1.0)))
    return float(best.get("price", 0)), float(best.get("size", 0))


def detect_binary_dutch_book(yes_token_id, no_token_id, yes_label="YES", no_label="NO"):
    """
    检测 Binary Dutch Book 套利机会

    原理: 买 1 YES + 1 NO 总是兑付 $1
    如果 ask(YES) + ask(NO) < 1 - 费用 → 锁定利润

    Args:
        yes_token_id: YES 代币 ID
        no_token_id: NO 代币 ID
        yes_label: YES 标签
        no_label: NO 标签

    Returns:
        dict: 套利机会详情 或 None
    """
    yes_book = get_orderbook(yes_token_id)
    no_book = get_orderbook(no_token_id)

    if not yes_book or not no_book:
        return None

    yes_ask = best_ask(yes_book)
    no_ask = best_ask(no_book)

    if not yes_ask or not no_ask:
        return None

    yes_price, yes_size = yes_ask
    no_price, no_size = no_ask

    cost_per_set = yes_price + no_price
    fee = cost_per_set * ARBITRAGE_CONFIG["taker_fee"]
    edge = 1.0 - cost_per_set - fee

    if edge <= ARBITRAGE_CONFIG["min_edge_pct"] * cost_per_set:
        return None

    executable_sets = min(yes_size, no_size)
    executable_sets = min(executable_sets, ARBITRAGE_CONFIG["max_notional_usd"] / cost_per_set)

    if executable_sets * cost_per_set < ARBITRAGE_CONFIG["min_notional_usd"]:
        return None

    return {
        "type": "binary_dutch_book",
        "legs": [
            {"token_id": yes_token_id, "label": yes_label, "side": "buy", "price": yes_price, "size": yes_size},
            {"token_id": no_token_id, "label": no_label, "side": "buy", "price": no_price, "size": no_size},
        ],
        "cost_per_set": round(cost_per_set, 4),
        "edge": round(edge, 4),
        "edge_pct": round(edge / cost_per_set * 100, 2) if cost_per_set > 0 else 0,
        "executable_sets": round(executable_sets, 2),
        "total_profit": round(edge * executable_sets, 2),
        "required_capital": round(cost_per_set * executable_sets, 2),
    }


def detect_mutually_exclusive(outcomes):
    """
    检测 Mutually-Exclusive Set 套利机会 (negRisk)

    原理: 多个互斥结果中恰好一个 resolve YES
    如果所有 YES 价格之和 < 1 - 费用 → 锁定利润

    ⚠️ 完整性守卫: 如果只捕获部分候选，价格之和可能远 < 1（假阳性）
    只有完整集合（价格之和接近 1）才是真正的套利

    Args:
        outcomes: list of {"token_id": str, "label": str, "orderbook": dict}

    Returns:
        dict: 套利机会详情 或 None
    """
    if len(outcomes) < 2:
        return None

    legs = []
    cost_per_set = 0.0
    min_size = float("inf")

    for outcome in outcomes:
        book = outcome.get("orderbook")
        if not book:
            return None

        ask = best_ask(book)
        if not ask:
            return None

        price, size = ask
        cost_per_set += price
        min_size = min(min_size, size)
        legs.append({
            "token_id": outcome["token_id"],
            "label": outcome["label"],
            "side": "buy",
            "price": price,
            "size": size,
        })

    # 完整性守卫: 价格之和太低说明集合不完整
    if cost_per_set < ARBITRAGE_CONFIG["min_completeness"] - 1e-9:
        log.warning(f"negRisk 完整性不足: cost={cost_per_set:.4f} < {ARBITRAGE_CONFIG['min_completeness']}")
        return None

    fee = cost_per_set * ARBITRAGE_CONFIG["taker_fee"]
    edge = 1.0 - cost_per_set - fee

    if edge <= ARBITRAGE_CONFIG["min_edge_pct"] * cost_per_set:
        return None

    executable_sets = min(min_size, ARBITRAGE_CONFIG["max_notional_usd"] / cost_per_set)

    if executable_sets * cost_per_set < ARBITRAGE_CONFIG["min_notional_usd"]:
        return None

    return {
        "type": "mutually_exclusive",
        "legs": legs,
        "cost_per_set": round(cost_per_set, 4),
        "edge": round(edge, 4),
        "edge_pct": round(edge / cost_per_set * 100, 2) if cost_per_set > 0 else 0,
        "executable_sets": round(executable_sets, 2),
        "total_profit": round(edge * executable_sets, 2),
        "required_capital": round(cost_per_set * executable_sets, 2),
        "n_outcomes": len(legs),
    }


def scan_binary_markets(limit=50):
    """
    扫描二元市场寻找 Dutch Book 套利机会

    Args:
        limit: 扫描市场数量

    Returns:
        list: 套利机会列表
    """
    opportunities = []

    try:
        resp = requests.get(
            f"{GAMMA_API}/markets",
            params={"closed": "false", "limit": limit, "active": "true",
                    "order": "liquidityNum", "ascending": "false"},
            timeout=15,
        )
        if resp.status_code != 200:
            return opportunities

        markets = resp.json()

        for market in markets:
            tokens = market.get("clobTokenIds", "")
            outcomes = market.get("outcomes", "")
            title = market.get("question", "")

            try:
                token_list = json.loads(tokens) if isinstance(tokens, str) else tokens
                outcome_list = json.loads(outcomes) if isinstance(outcomes, str) else outcomes
            except Exception:
                continue

            if len(token_list) != 2 or len(outcome_list) != 2:
                continue

            # 过滤极端价格市场
            prices = market.get("outcomePrices", "[0.5]")
            try:
                price_list = json.loads(prices) if isinstance(prices, str) else prices
                yes_price = float(price_list[0])
            except Exception:
                continue

            if yes_price < 0.05 or yes_price > 0.95:
                continue

            opp = detect_binary_dutch_book(
                token_list[0], token_list[1],
                outcome_list[0], outcome_list[1]
            )

            if opp:
                opp["market_title"] = title
                opp["market_slug"] = market.get("slug", "")
                opp["condition_id"] = market.get("conditionId", "")
                opportunities.append(opp)
                log.info(f"🎯 Dutch Book 发现: {title[:50]} | edge={opp['edge_pct']:.1f}%")

    except Exception as e:
        log_error("arbitrage", e, "扫描二元市场失败")

    return opportunities


def scan_negrisk_groups(limit=200):
    """
    扫描 negRisk 多结果市场组寻找套利机会

    Args:
        limit: 扫描市场数量

    Returns:
        list: 套利机会列表
    """
    opportunities = []

    try:
        resp = requests.get(
            f"{GAMMA_API}/markets",
            params={"closed": "false", "limit": limit, "active": "true"},
            timeout=15,
        )
        if resp.status_code != 200:
            return opportunities

        markets = resp.json()

        # 按 group_id 分组
        groups = {}
        for market in markets:
            # negRisk 市场有 groupItemTitle 字段
            group_id = market.get("groupItemTitle", "")
            if not group_id:
                continue

            # 用事件 slug 作为分组键
            event_slug = market.get("slug", "").rsplit("-", 1)[0] if market.get("slug") else ""
            if not event_slug:
                continue

            if event_slug not in groups:
                groups[event_slug] = []
            groups[event_slug].append(market)

        # 检查每组
        for event_slug, group_markets in groups.items():
            if len(group_markets) < 3:  # 至少 3 个结果才有意义
                continue

            outcomes = []
            total_yes = 0

            for market in group_markets:
                tokens = market.get("clobTokenIds", "")
                try:
                    token_list = json.loads(tokens) if isinstance(tokens, str) else tokens
                except Exception:
                    continue

                if not token_list:
                    continue

                yes_token = token_list[0]
                book = get_orderbook(yes_token)
                if not book:
                    continue

                ask = best_ask(book)
                if not ask:
                    continue

                total_yes += ask[0]
                outcomes.append({
                    "token_id": yes_token,
                    "label": market.get("question", "")[:30],
                    "orderbook": book,
                })

            if len(outcomes) < 3:
                continue

            opp = detect_mutually_exclusive(outcomes)
            if opp:
                opp["event_slug"] = event_slug
                opp["event_title"] = group_markets[0].get("question", "").split("?")[0] + "?"
                opportunities.append(opp)
                log.info(f"🎯 negRisk 套利发现: {opp['event_title'][:50]} | "
                         f"edge={opp['edge_pct']:.1f}% | {opp['n_outcomes']} outcomes")

    except Exception as e:
        log_error("arbitrage", e, "扫描 negRisk 市场失败")

    return opportunities


def scan_all_arbitrage():
    """
    扫描所有套利机会

    Returns:
        dict: {"binary": [...], "negrisk": [...], "total": int, "total_profit": float}
    """
    log.info("🔍 开始套利扫描...")

    binary_opps = scan_binary_markets(limit=50)
    negrisk_opps = scan_negrisk_groups(limit=200)

    all_opps = binary_opps + negrisk_opps
    total_profit = sum(opp.get("total_profit", 0) for opp in all_opps)

    result = {
        "binary": binary_opps,
        "negrisk": negrisk_opps,
        "total": len(all_opps),
        "total_profit": round(total_profit, 2),
        "scan_time": datetime.now(timezone.utc).isoformat(),
    }

    log.info(f"📊 套利扫描完成: {len(binary_opps)} binary + {len(negrisk_opps)} negRisk = {len(all_opps)} 总计")

    return result


def format_arbitrage_report(result):
    """
    格式化套利扫描报告

    Args:
        result: scan_all_arbitrage() 的返回值

    Returns:
        str: 格式化的报告
    """
    lines = []
    lines.append("🔄 套利扫描报告")
    lines.append("=" * 50)

    if result["total"] == 0:
        lines.append("💤 当前无套利机会（市场高效）")
        return "\n".join(lines)

    lines.append(f"📊 发现 {result['total']} 个机会 | 预计总利润: ${result['total_profit']:.2f}")
    lines.append("")

    if result["binary"]:
        lines.append("📗 Binary Dutch Book:")
        for opp in result["binary"]:
            lines.append(f"  🎯 {opp.get('market_title', '?')[:50]}")
            lines.append(f"     Edge: {opp['edge_pct']:.1f}% | 利润: ${opp['total_profit']:.2f} | 资金: ${opp['required_capital']:.2f}")
            lines.append(f"     YES@{opp['legs'][0]['price']:.3f} + NO@{opp['legs'][1]['price']:.3f} = {opp['cost_per_set']:.3f}")
        lines.append("")

    if result["negrisk"]:
        lines.append("📕 negRisk Mutually-Exclusive:")
        for opp in result["negrisk"]:
            lines.append(f"  🎯 {opp.get('event_title', '?')[:50]}")
            lines.append(f"     Edge: {opp['edge_pct']:.1f}% | 利润: ${opp['total_profit']:.2f} | {opp['n_outcomes']} outcomes")
            lines.append(f"     总成本: {opp['cost_per_set']:.3f} (应接近 1.0)")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    # 独立运行：扫描套利机会
    result = scan_all_arbitrage()
    print(format_arbitrage_report(result))
