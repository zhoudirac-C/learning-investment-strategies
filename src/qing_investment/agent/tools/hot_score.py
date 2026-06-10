"""Hot Score Calculator — 观察池热度分计算。

Phase 4 核心组件：
- 每日开盘前自动计算 watchlist 中各标的的 hot_score
- 综合 claims 时效性、UP 提及频率、技术形态、板块强度
- 输出排序后的观察池，供 Agent 优先关注

Refs: docs/config-cron-architecture-review.md v2.0 Phase 4
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from qing_investment.paths import repo_root

logger = logging.getLogger(__name__)

DEFAULT_WATCHLIST_PATH = repo_root() / "config" / "stock_monitor" / "watchlist.yaml"
DEFAULT_OUTPUT_PATH = repo_root() / "config" / "stock_monitor" / "watchlist_hot_scores.json"


# ── 评分权重 ──
_WEIGHTS = {
    "claim_freshness": 0.20,      # claims 时效性（最近7天加分）
    "up_mention_recency": 0.15,   # UP 最近提及（3天内加分）
    "priority_base": 0.10,        # 基础优先级（P1/P2/P3）
    "technical_setup": 0.10,      # 技术形态完整度（有buy_setup/invalidation）
    "sector_momentum": 0.10,      # 板块动量（claims中方向提及强度）
    "linked_claims_count": 0.10,  # 关联claims数量
    "entry_zone_proximity": 0.15, # 【新增】价格接近介入区间（距离 entry_zone ≤ 3% → 高分）
    "position_status": 0.10,      # 【新增】持仓状态（已持仓 → 永远高分）
}

_PRIORITY_SCORES = {
    "P1-核心": 10,
    "P1": 10,
    "P2-重点": 7,
    "P2": 7,
    "P3-观察": 4,
    "P3": 4,
}


def _parse_date(date_str: str | None) -> datetime | None:
    """解析日期字符串。"""
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


def _days_since(date_str: str | None) -> int | None:
    """计算距今天数。"""
    dt = _parse_date(date_str)
    if not dt:
        return None
    return (datetime.now() - dt).days


def _score_claim_freshness(stock: dict) -> float:
    """claims 时效性评分（0-10）。"""
    linked_claims = stock.get("linked_claims", [])
    if not linked_claims:
        # 回退：检查 source_docs 中的 claim 文件
        source_docs = stock.get("source_docs", [])
        claim_dates = []
        for doc in source_docs:
            if "claim-" in doc:
                # 从 claim 文件名提取日期 claim-YYYYMMDD-xxx
                import re
                match = re.search(r"claim-(\d{8})-", doc)
                if match:
                    date_str = match.group(1)
                    try:
                        dt = datetime.strptime(date_str, "%Y%m%d")
                        claim_dates.append(dt)
                    except ValueError:
                        pass
        
        if not claim_dates:
            return 3.0  # 无 claims，基础分
        
        latest = max(claim_dates)
        days = (datetime.now() - latest).days
    else:
        latest_date = ""
        for lc in linked_claims:
            d = lc.get("claim_date", "")
            if d and (not latest_date or d > latest_date):
                latest_date = d
        days = _days_since(latest_date) if latest_date else 999
    
    if days is None or days > 30:
        return 3.0
    elif days <= 3:
        return 10.0
    elif days <= 7:
        return 8.0
    elif days <= 14:
        return 6.0
    else:
        return 4.0


def _score_up_mention_recency(stock: dict) -> float:
    """UP 提及时效性评分（0-10）。"""
    mention = stock.get("up_mention_status", {})
    last_date = mention.get("last_mentioned_date", "")
    days = _days_since(last_date)
    
    if days is None:
        return 3.0
    if days <= 1:
        return 10.0
    elif days <= 3:
        return 8.0
    elif days <= 7:
        return 6.0
    elif days <= 14:
        return 4.0
    else:
        return 2.0


def _score_priority(stock: dict) -> float:
    """基础优先级评分（0-10）。"""
    priority = stock.get("priority", "")
    return _PRIORITY_SCORES.get(priority, 5.0)


def _score_technical_setup(stock: dict) -> float:
    """技术形态完整度评分（0-10）。"""
    score = 5.0  # 基础分
    
    # 有 buy_setup
    if stock.get("buy_setup"):
        score += 2.0
    
    # 有 invalidation_setup
    if stock.get("invalidation_setup"):
        score += 2.0
    
    # 有 technical_narrative
    tn = stock.get("technical_narrative", {})
    if tn and tn.get("key_levels"):
        score += 1.0
    
    return min(score, 10.0)


def _score_sector_momentum(stock: dict, theme_claims: list[dict]) -> float:
    """板块动量评分（0-10）。基于关联 theme 的 claims 强度。"""
    if not theme_claims:
        return 5.0
    
    # 计算 theme claims 的平均强度
    intensity_scores = []
    for c in theme_claims:
        intensity = c.get("intensity", "medium")
        if intensity == "high":
            intensity_scores.append(10)
        elif intensity == "medium":
            intensity_scores.append(6)
        else:
            intensity_scores.append(3)
    
    avg = sum(intensity_scores) / len(intensity_scores) if intensity_scores else 5.0
    return avg


def _score_linked_claims_count(stock: dict) -> float:
    """关联 claims 数量评分（0-10）。"""
    linked = stock.get("linked_claims", [])
    count = len(linked) if linked else 0
    
    # 回退：source_docs 中的 claim 数量
    if count == 0:
        source_docs = stock.get("source_docs", [])
        count = sum(1 for d in source_docs if "claim-" in d)
    
    if count >= 5:
        return 10.0
    elif count >= 3:
        return 8.0
    elif count >= 2:
        return 6.0
    elif count >= 1:
        return 4.0
    else:
        return 2.0


def _score_entry_zone_proximity(stock: dict) -> float:
    """【新增】价格接近介入区间评分（0-10）。
    
    如果 stock 有 entry_zone 或 buy_setup 中的价格区间，
    且当前价格接近该区间，给予高分。
    当前无实时价格时，基于 buy_setup 文本判断。
    """
    # 检查 buy_setup 中是否有价格区间
    buy_setup = stock.get("buy_setup", "")
    if not buy_setup:
        return 5.0  # 无介入区间，中性分
    
    # 简单判断：buy_setup 越具体（包含数字），分数越高
    import re
    price_matches = re.findall(r"(\d+\.?\d*)", str(buy_setup))
    
    if len(price_matches) >= 2:
        # 有具体价格区间
        return 8.0
    elif len(price_matches) == 1:
        return 6.0
    else:
        return 4.0


def _score_position_status(stock: dict, positions_data: dict | None = None) -> float:
    """【新增】持仓状态评分（0-10）。
    
    已持仓的票永远给高分（确保持仓票始终在关注列表中）。
    """
    code = stock.get("code", "")
    
    # 如果有传入的持仓数据，检查是否持仓
    if positions_data:
        for acc in positions_data.get("accounts", []):
            for pos in acc.get("positions", []):
                if pos.get("code") == code and pos.get("shares", 0) > 0:
                    return 10.0  # 已持仓，最高分
    
    # 检查 stock 本身是否有 position 标记（来自 watchlist 的 lifecycle）
    lifecycle = stock.get("lifecycle", {})
    if lifecycle.get("stage") == "position":
        return 10.0
    
    return 5.0  # 未持仓，中性分


def calculate_hot_score(stock: dict, theme_claims: list[dict] | None = None, positions_data: dict | None = None) -> dict:
    """计算单只标的的热度分。
    
    Returns:
        {
            "code": "000534.SZ",
            "name": "万泽股份",
            "hot_score": 7.5,
            "breakdown": {
                "claim_freshness": 8.0,
                "up_mention_recency": 7.0,
                "priority_base": 10.0,
                "technical_setup": 6.0,
                "sector_momentum": 7.5,
                "linked_claims_count": 6.0,
                "entry_zone_proximity": 8.0,  # 【新增】
                "position_status": 10.0,       # 【新增】
            },
            "ranking_tier": "A",  # A(>=8) / B(6-8) / C(4-6) / D(<4)
        }
    """
    theme_claims = theme_claims or []
    
    scores = {
        "claim_freshness": _score_claim_freshness(stock),
        "up_mention_recency": _score_up_mention_recency(stock),
        "priority_base": _score_priority(stock),
        "technical_setup": _score_technical_setup(stock),
        "sector_momentum": _score_sector_momentum(stock, theme_claims),
        "linked_claims_count": _score_linked_claims_count(stock),
        "entry_zone_proximity": _score_entry_zone_proximity(stock),  # 【新增】
        "position_status": _score_position_status(stock, positions_data),  # 【新增】
    }
    
    # 加权总分
    total = sum(scores[k] * _WEIGHTS[k] for k in scores)
    
    # 分级
    if total >= 8.0:
        tier = "A"
    elif total >= 6.0:
        tier = "B"
    elif total >= 4.0:
        tier = "C"
    else:
        tier = "D"
    
    return {
        "code": stock.get("code", ""),
        "name": stock.get("name", ""),
        "hot_score": round(total, 2),
        "breakdown": {k: round(v, 1) for k, v in scores.items()},
        "ranking_tier": tier,
    }


def load_watchlist(path: Path | None = None) -> dict:
    """加载 watchlist.yaml。"""
    watchlist_path = path or DEFAULT_WATCHLIST_PATH
    with open(watchlist_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def calculate_all_hot_scores(watchlist_data: dict | None = None, positions_data: dict | None = None) -> list[dict]:
    """计算 watchlist 中所有标的的热度分。
    
    Returns:
        按 hot_score 降序排列的列表
    """
    if watchlist_data is None:
        watchlist_data = load_watchlist()
    
    # 【新增】加载持仓数据用于 position_status 评分
    if positions_data is None:
        positions_path = repo_root() / "config" / "stock_monitor" / "positions.yaml"
        if positions_path.exists():
            with open(positions_path, encoding="utf-8") as f:
                positions_data = yaml.safe_load(f) or {}
    
    results = []
    seen_codes = set()
    
    for theme in watchlist_data.get("themes", []):
        theme_claims = []
        # 从 theme 的 source_docs 提取 claims
        for doc in theme.get("source_docs", []):
            if "claim-" in doc:
                theme_claims.append({"intensity": "medium"})  # 简化处理
        
        for stock in theme.get("stocks", []):
            code = stock.get("code", "")
            if code in seen_codes:
                continue  # 去重：同一标的只计算一次（取首次出现的 theme）
            seen_codes.add(code)
            
            score_result = calculate_hot_score(stock, theme_claims, positions_data)
            score_result["theme"] = theme.get("name", "")
            score_result["theme_id"] = theme.get("id", "")
            results.append(score_result)
    
    # 按 hot_score 降序
    results.sort(key=lambda x: -x["hot_score"])
    return results


def save_hot_scores(results: list[dict], path: Path | None = None) -> None:
    """保存热度分结果。"""
    output_path = path or DEFAULT_OUTPUT_PATH
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    data = {
        "calculated_at": datetime.now().isoformat(),
        "total_stocks": len(results),
        "tier_summary": {
            "A": len([r for r in results if r["ranking_tier"] == "A"]),
            "B": len([r for r in results if r["ranking_tier"] == "B"]),
            "C": len([r for r in results if r["ranking_tier"] == "C"]),
            "D": len([r for r in results if r["ranking_tier"] == "D"]),
        },
        "top_20": results[:20],
        "all_scores": results,
    }
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    logger.info("Saved hot scores for %d stocks to %s", len(results), output_path)


def get_top_stocks_by_hot_score(
    tier: str | None = None,
    limit: int = 10,
    path: Path | None = None,
) -> list[dict]:
    """获取按热度分排序的标的列表。"""
    output_path = path or DEFAULT_OUTPUT_PATH
    
    if not output_path.exists():
        logger.warning("Hot scores not calculated yet, running now...")
        results = calculate_all_hot_scores()
        save_hot_scores(results, output_path)
    else:
        with open(output_path, encoding="utf-8") as f:
            data = json.load(f)
        results = data.get("all_scores", [])
    
    if tier:
        results = [r for r in results if r["ranking_tier"] == tier]
    
    return results[:limit]


def format_hot_score_summary(limit: int = 10) -> str:
    """生成 human-readable 的热度分摘要，用于注入 prompt。"""
    top_stocks = get_top_stocks_by_hot_score(limit=limit)
    
    if not top_stocks:
        return "观察池热度分尚未计算。"
    
    lines = ["【观察池热度排行】"]
    for i, s in enumerate(top_stocks, 1):
        lines.append(
            f"{i}. {s['name']}({s['code']}) [{s['theme']}] "
            f"热度{s['hot_score']} 等级{s['ranking_tier']}"
        )
    
    return "\n".join(lines)


if __name__ == "__main__":
    # CLI 入口：每日开盘前运行
    import sys
    
    logging.basicConfig(level=logging.INFO)
    
    watchlist_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    
    results = calculate_all_hot_scores(
        load_watchlist(watchlist_path) if watchlist_path else None
    )
    save_hot_scores(results, output_path)
    
    print(f"Calculated hot scores for {len(results)} stocks")
    print(f"Top 5:")
    for s in results[:5]:
        print(f"  {s['name']}({s['code']}): {s['hot_score']} [{s['ranking_tier']}]")
