"""Claims → Entry Points 半自动桥接。

Phase 4 核心组件：
- 扫描 Neo4j/Qdrant 中的 operation 类型 claims
- 提取介入建议（股票代码、介入区间、仓位、止损）
- 生成 entry_points 建议 YAML，人工确认后写入 strategy_pack

Refs: docs/config-cron-architecture-review.md v2.0 Phase 4
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from qing_investment.paths import repo_root

logger = logging.getLogger(__name__)

DEFAULT_STRATEGY_PACK_PATH = repo_root() / "config" / "stock_monitor" / "strategy_pack.yaml"
DEFAULT_OUTPUT_DIR = repo_root() / "config" / "stock_monitor" / "entry_suggestions"


# ── 介入建议正则提取 ──
_ENTRY_ZONE_PATTERNS = [
    r"(\d+\.?\d*)\s*[-~至到]\s*(\d+\.?\d*)",  # 30.5-31.0
    r"(\d+\.?\d*)\s*附近",  # 30.5附近
    r"回踩\s*(\d+\.?\d*)",  # 回踩30.5
    r"回调到\s*(\d+\.?\d*)",  # 回调到30.5
]

_POSITION_RATIO_PATTERNS = [
    r"(\d+\.?\d*)\s*成(?:仓|层)?",  # 0.5成、1成仓
    r"(\d+\.?\d*)%\s*仓位",  # 50%仓位
    r"半(?:成|层)?仓",  # 半仓 → 0.5
    r"全(?:成|层)?仓",  # 全仓 → 1.0
]

_STOP_LOSS_PATTERNS = [
    r"跌破\s*(\d+\.?\d*)\s*且?\s*(\d+)\s*分钟",  # 跌破30且30分钟
    r"止损\s*(\d+\.?\d*)",  # 止损30
    r"跌破\s*(\d+\.?\d*)",  # 跌破30
]


def _extract_entry_zone(statement: str) -> str | None:
    """从 claim statement 提取介入区间。"""
    for pattern in _ENTRY_ZONE_PATTERNS:
        match = re.search(pattern, statement)
        if match:
            if len(match.groups()) >= 2:
                return f"{match.group(1)}-{match.group(2)}"
            else:
                return match.group(1)
    return None


def _extract_position_ratio(statement: str) -> str | None:
    """从 claim statement 提取仓位建议。"""
    for pattern in _POSITION_RATIO_PATTERNS:
        match = re.search(pattern, statement)
        if match:
            val = match.group(1) if match.groups() else None
            if val:
                return f"{val}成"
            if "半" in match.group(0):
                return "0.5成"
            if "全" in match.group(0):
                return "1成"
    return None


def _extract_stop_loss(statement: str) -> str | None:
    """从 claim statement 提取止损条件。"""
    for pattern in _STOP_LOSS_PATTERNS:
        match = re.search(pattern, statement)
        if match:
            if len(match.groups()) >= 2:
                return f"跌破{match.group(1)}且{match.group(2)}分钟不能收回"
            else:
                return f"跌破{match.group(1)}"
    return None


def _extract_stock_codes(statement: str) -> list[str]:
    """从 claim statement 提取股票代码（6位数字）。"""
    codes = re.findall(r"\b(\d{6})\b", statement)
    return list(set(codes))


def parse_operation_claim(claim: dict) -> list[dict]:
    """解析 operation 类型 claim，提取 entry point 建议。

    Returns:
        [{"code": "000534", "name": "万泽股份", "entry_zone": "30.5-31.0",
          "position_ratio": "0.5成", "stop_loss": "跌破30", "claim_id": "...",
          "claim_statement": "...", "confidence": "high"}]
    """
    stmt = claim.get("statement", "")
    claim_id = claim.get("id", "")
    source_date = claim.get("source_date", "")

    codes = _extract_stock_codes(stmt)
    if not codes:
        return []

    entry_zone = _extract_entry_zone(stmt)
    position_ratio = _extract_position_ratio(stmt)
    stop_loss = _extract_stop_loss(stmt)

    # 如果没有介入区间，可能不是 entry point 类型
    if not entry_zone:
        return []

    results = []
    for code in codes:
        # 简单名称映射（实际应从 watchlist 查找）
        results.append({
            "code": code,
            "name": "",  # 后续从 watchlist 回填
            "entry_zone": entry_zone,
            "position_ratio": position_ratio or "未指定",
            "stop_loss": stop_loss or "未指定",
            "claim_id": claim_id,
            "claim_statement": stmt[:100] + "..." if len(stmt) > 100 else stmt,
            "source_date": source_date,
            "confidence": claim.get("intensity", "medium"),
        })

    return results


def scan_claims_for_entries(
    neo4j_client: Any,
    days_back: int = 7,
) -> list[dict]:
    """扫描最近 N 天的 operation 类型 claims，提取 entry point 建议。

    Returns:
        去重后的 entry point 建议列表
    """
    from qing_investment.agent.tools.neo4j_client import Neo4jClient

    entries = []
    seen_codes: set[str] = set()

    try:
        if isinstance(neo4j_client, Neo4jClient):
            # 获取最近 N 天的 operation claims
            claims = neo4j_client.get_recent_claims(
                claim_type="operation",
                days=days_back,
                limit=50,
            )

            for claim in claims:
                parsed = parse_operation_claim(claim)
                for entry in parsed:
                    code = entry["code"]
                    if code not in seen_codes:
                        seen_codes.add(code)
                        entries.append(entry)
    except Exception as e:
        logger.warning("Failed to scan claims for entries: %s", e)

    return entries


def generate_entry_suggestions(
    entries: list[dict],
    watchlist_data: dict | None = None,
) -> list[dict]:
    """生成 entry point 建议，回填股票名称和主题信息。

    Returns:
        完整的 entry point 建议列表
    """
    if watchlist_data is None:
        from qing_investment.agent.tools.hot_score import load_watchlist
        watchlist_data = load_watchlist()

    # 构建 code -> name/theme 映射
    code_info: dict[str, dict] = {}
    for theme in watchlist_data.get("themes", []):
        for stock in theme.get("stocks", []):
            code = stock.get("code", "").replace(".SH", "").replace(".SZ", "")
            code_info[code] = {
                "name": stock.get("name", ""),
                "theme": theme.get("name", ""),
                "priority": stock.get("priority", ""),
            }

    for entry in entries:
        code = entry["code"]
        info = code_info.get(code, {})
        entry["name"] = info.get("name", entry["name"])
        entry["theme"] = info.get("theme", "")
        entry["priority"] = info.get("priority", "")

    return entries


def update_watchlist_linked_claims(
    entries: list[dict],
    watchlist_data: dict | None = None,
) -> dict:
    """【新增】将 claims 关联回写到 watchlist.yaml 的 linked_claims 字段。
    
    对于每个 entry 中的 code，在对应的 watchlist stock 中追加 linked_claims 记录。
    
    Returns:
        更新后的 watchlist_data
    """
    if watchlist_data is None:
        from qing_investment.agent.tools.hot_score import load_watchlist
        watchlist_data = load_watchlist()
    
    # 构建 code -> stock 引用映射
    code_to_stock: dict[str, dict] = {}
    for theme in watchlist_data.get("themes", []):
        for stock in theme.get("stocks", []):
            code = stock.get("code", "").replace(".SH", "").replace(".SZ", "")
            code_to_stock[code] = stock
    
    updated_count = 0
    for entry in entries:
        code = entry["code"]
        stock = code_to_stock.get(code)
        if not stock:
            continue
        
        # 确保 linked_claims 字段存在
        if "linked_claims" not in stock:
            stock["linked_claims"] = []
        
        # 检查是否已存在相同 claim_id
        existing_ids = {lc.get("claim_id") for lc in stock["linked_claims"]}
        claim_id = entry.get("claim_id", "")
        
        if claim_id and claim_id not in existing_ids:
            stock["linked_claims"].append({
                "claim_id": claim_id,
                "relevance": "direct",
                "claim_type": "operation",
                "added_at": datetime.now().isoformat(),
            })
            updated_count += 1
            
            # 同时刷新 lifecycle.last_activity
            if "lifecycle" in stock:
                stock["lifecycle"]["last_activity"] = datetime.now().strftime("%Y-%m-%d")
    
    logger.info("Updated linked_claims for %d stocks in watchlist", updated_count)
    return watchlist_data


def save_watchlist(watchlist_data: dict, path: Path | None = None) -> None:
    """【新增】保存 watchlist.yaml。"""
    watchlist_path = path or (repo_root() / "config" / "stock_monitor" / "watchlist.yaml")
    with open(watchlist_path, "w", encoding="utf-8") as f:
        yaml.dump(watchlist_data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
    logger.info("Saved watchlist to %s", watchlist_path)


def merge_with_existing_entries(
    suggestions: list[dict],
    existing_entries: list[dict],
) -> list[dict]:
    """将新建议与现有 entry_points 合并，避免重复。

    策略：
    - 如果 code 已存在且 status=active：更新 claim_basis，保留原 entry_zone
    - 如果 code 不存在：添加为新 entry_point
    - 如果 code 存在但 status=triggered/executed：不覆盖
    """
    existing_map = {e["code"].replace(".SH", "").replace(".SZ", ""): e for e in existing_entries}
    merged = list(existing_entries)

    for sug in suggestions:
        code = sug["code"]
        if code in existing_map:
            existing = existing_map[code]
            if existing.get("status") == "active":
                # 更新 claim_basis
                existing["claim_basis"] = f"{sug['claim_id']}: {sug['claim_statement'][:50]}"
                existing["last_updated"] = datetime.now().isoformat()
                logger.info("Updated existing entry for %s", code)
        else:
            # 新增
            new_entry = {
                "code": f"{code}.SZ" if code.startswith("0") else f"{code}.SH",
                "name": sug["name"],
                "status": "suggested",  # 需要人工确认
                "entry_zone": sug["entry_zone"],
                "position_ratio": sug["position_ratio"],
                "trigger": f"回踩{sug['entry_zone']}企稳",
                "invalidation": sug["stop_loss"] or "未指定",
                "opportunity_pattern": "技术支撑确认",  # 默认，需人工调整
                "odds_analysis": {
                    "upside_pct": 15,
                    "downside_pct": 5,
                    "odds_ratio": "3:1",
                    "estimated_probability_up": 45,
                    "expected_value": 4.0,
                    "updated_at": datetime.now().isoformat(),
                },
                "claim_basis": f"{sug['claim_id']}: {sug['claim_statement'][:80]}",
                "note": f"从 claim 自动提取，需人工确认 | 主题: {sug.get('theme', '')}",
                "suggested_at": datetime.now().isoformat(),
            }
            merged.append(new_entry)
            logger.info("Added new suggested entry for %s", code)

    return merged


def save_entry_suggestions(
    suggestions: list[dict],
    output_dir: Path | None = None,
) -> Path:
    """保存 entry point 建议到待确认文件。"""
    output_dir = output_dir or DEFAULT_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"entry_suggestions_{timestamp}.yaml"

    data = {
        "generated_at": datetime.now().isoformat(),
        "total_suggestions": len(suggestions),
        "instructions": "请人工审核以下建议，确认后复制到 strategy_pack.yaml 的 entry_points 中",
        "suggestions": suggestions,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False)

    logger.info("Saved %d entry suggestions to %s", len(suggestions), output_path)
    return output_path


def load_strategy_pack(path: Path | None = None) -> dict:
    """加载 strategy_pack.yaml。"""
    pack_path = path or DEFAULT_STRATEGY_PACK_PATH
    with open(pack_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def run_claims_to_entry_bridge(
    neo4j_client: Any,
    days_back: int = 7,
    auto_merge: bool = False,
    update_watchlist: bool = True,  # 【新增】默认回写 linked_claims
) -> Path | None:
    """运行 Claims → Entry 桥接流程。

    Args:
        neo4j_client: Neo4j 客户端
        days_back: 扫描最近 N 天的 claims
        auto_merge: 是否自动合并到 strategy_pack（默认 False，生成建议文件）
        update_watchlist: 是否回写 linked_claims 到 watchlist.yaml（默认 True）

    Returns:
        生成的建议文件路径
    """
    logger.info("Running claims-to-entry bridge (days_back=%d)...", days_back)

    # 1. 扫描 claims
    entries = scan_claims_for_entries(neo4j_client, days_back)
    logger.info("Found %d raw entry suggestions from claims", len(entries))

    if not entries:
        logger.info("No new entry points found")
        return None

    # 2. 回填信息
    suggestions = generate_entry_suggestions(entries)

    # 3. 【新增】回写 linked_claims 到 watchlist.yaml
    if update_watchlist:
        from qing_investment.agent.tools.hot_score import load_watchlist
        watchlist_data = load_watchlist()
        updated_watchlist = update_watchlist_linked_claims(suggestions, watchlist_data)
        save_watchlist(updated_watchlist)
        logger.info("Updated watchlist linked_claims")

    # 4. 与现有 entry_points 合并（或生成建议文件）
    if auto_merge:
        strategy_pack = load_strategy_pack()
        existing = strategy_pack.get("entry_points", [])
        merged = merge_with_existing_entries(suggestions, existing)
        strategy_pack["entry_points"] = merged

        with open(DEFAULT_STRATEGY_PACK_PATH, "w", encoding="utf-8") as f:
            yaml.dump(strategy_pack, f, allow_unicode=True, sort_keys=False)
        logger.info("Auto-merged %d suggestions into strategy_pack", len(suggestions))
        return DEFAULT_STRATEGY_PACK_PATH
    else:
        # 生成待确认文件
        return save_entry_suggestions(suggestions)


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)

    # 简化测试：从命令行读取 claim 文件
    if len(sys.argv) > 1:
        claim_file = Path(sys.argv[1])
        with open(claim_file, encoding="utf-8") as f:
            claim = yaml.safe_load(f)
        parsed = parse_operation_claim(claim)
        print(json.dumps(parsed, ensure_ascii=False, indent=2))
    else:
        print("Usage: python claims_to_entry.py <claim_file.yaml>")
