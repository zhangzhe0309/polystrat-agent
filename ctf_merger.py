"""
Polymarket Conditional Tokens Framework (CTF) 合并赎回模块
功能：当系统同时持有某 Condition ID 的 YES 与 NO 代币时，调用 CTF 合约 mergePositions 1:1 无损合并为 USDC 现金，释放被冻结资金池。
"""

import logging
import os
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# Polygon 主网 CTF 与 USDC 合约地址
CTF_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # USDC.e on Polygon

# 简化的 CTF mergePositions 最小 ABI
CTF_MINIMAL_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "collateralToken", "type": "address"},
            {"name": "parentCollectionId", "type": "bytes32"},
            {"name": "conditionId", "type": "bytes32"},
            {"name": "partition", "type": "uint256[]"},
            {"name": "amount", "type": "uint256"},
        ],
        "name": "mergePositions",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function",
    }
]


def detect_mergeable_positions(positions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    检测持仓列表中是否存在可无损合并的对冲持仓 (同 condition_id 同时持有 YES 和 NO)
    """
    grouped: Dict[str, Dict[str, float]] = {}
    for pos in positions:
        cid = pos.get("condition_id") or pos.get("market_id")
        side = str(pos.get("direction") or pos.get("side") or "").upper()
        shares = float(pos.get("shares") or pos.get("token_count") or pos.get("amount") or 0.0)

        if not cid or not side or shares <= 0:
            continue

        if cid not in grouped:
            grouped[cid] = {"YES": 0.0, "NO": 0.0}

        if side in ["YES", "BUY_YES"]:
            grouped[cid]["YES"] += shares
        elif side in ["NO", "BUY_NO"]:
            grouped[cid]["NO"] += shares

    mergeable = []
    for cid, counts in grouped.items():
        yes_amt = counts.get("YES", 0.0)
        no_amt = counts.get("NO", 0.0)
        common_shares = min(yes_amt, no_amt)
        if common_shares >= 0.01:  # 最小合并门槛 0.01 股
            mergeable.append({
                "condition_id": cid,
                "yes_shares": yes_amt,
                "no_shares": no_amt,
                "mergeable_shares": common_shares,
                "estimated_usdc_recovered": round(common_shares, 2)
            })

    return mergeable


def execute_ctf_merge(
    condition_id: str,
    amount_shares: float,
    private_key: Optional[str] = None,
    dry_run: bool = True
) -> Dict[str, Any]:
    """
    执行 CTF 1 YES + 1 NO -> 1 USDC 赎回
    :param condition_id: 市场的 Condition ID (bytes32 hex)
    :param amount_shares: 拟合并赎回的股数 (USDC)
    :param private_key: 私钥 (可选)
    :param dry_run: 模拟测试模式
    """
    if dry_run or not private_key:
        log.info(f"🧪 [CTF Merge Sim] 模拟无损合并: condition={condition_id[:12]}... 股数={amount_shares} -> 赎回 ${amount_shares:.2f} USDC")
        return {
            "success": True,
            "simulated": True,
            "condition_id": condition_id,
            "merged_shares": amount_shares,
            "usdc_received": amount_shares,
            "tx_hash": "0x_simulated_ctf_merge_hash"
        }

    try:
        from web3 import Web3
        rpc_url = os.getenv("POLYGON_RPC_URL", "https://polygon-rpc.com")
        w3 = Web3(Web3.HTTPProvider(rpc_url))

        if not w3.is_connected():
            return {"success": False, "reason": "RPC connection failed"}

        account = w3.eth.account.from_key(private_key)
        contract = w3.eth.contract(address=Web3.to_checksum_address(CTF_ADDRESS), abi=CTF_MINIMAL_ABI)

        # 6 decimal places for USDC collateral on Polygon
        amount_wei = int(amount_shares * 1e6)
        parent_collection_id = b"\x00" * 32
        cid_bytes = bytes.fromhex(condition_id.replace("0x", ""))

        tx = contract.functions.mergePositions(
            Web3.to_checksum_address(USDC_ADDRESS),
            parent_collection_id,
            cid_bytes,
            [1, 2],  # YES index=1, NO index=2
            amount_wei
        ).build_transaction({
            'from': account.address,
            'nonce': w3.eth.get_transaction_count(account.address),
            'gasPrice': w3.eth.gas_price
        })

        signed_tx = w3.eth.account.sign_transaction(tx, private_key)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        
        log.info(f"✅ [CTF Merge Success] 合并已提交: tx={w3.to_hex(tx_hash)}")
        return {
            "success": True,
            "simulated": False,
            "condition_id": condition_id,
            "merged_shares": amount_shares,
            "usdc_received": amount_shares,
            "tx_hash": w3.to_hex(tx_hash)
        }

    except Exception as e:
        log.error(f"❌ [CTF Merge Error] 合并失败: {str(e)}")
        return {"success": False, "reason": str(e)}


def auto_merge_portfolio(positions: List[Dict[str, Any]], dry_run: bool = True) -> Dict[str, Any]:
    """
    全自动检测并合并持仓组合中的匹配对冲单
    """
    mergeables = detect_mergeable_positions(positions)
    if not mergeables:
        return {"merged_count": 0, "total_usdc_recovered": 0.0, "details": []}

    pk = os.getenv("POLYMARKET_PRIVATE_KEY", "")
    total_recovered = 0.0
    results = []

    for item in mergeables:
        res = execute_ctf_merge(
            condition_id=item["condition_id"],
            amount_shares=item["mergeable_shares"],
            private_key=pk,
            dry_run=dry_run
        )
        if res.get("success"):
            total_recovered += item["mergeable_shares"]
            results.append(res)

    return {
        "merged_count": len(results),
        "total_usdc_recovered": round(total_recovered, 2),
        "details": results
    }
