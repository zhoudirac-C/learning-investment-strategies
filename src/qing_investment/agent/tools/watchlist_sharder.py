"""Watchlist sharding — 把观察池拆分为可独立分析的小批次。

Phase 2 核心组件：
- 优先把 P1 标的 + 持仓股放入 priority shard
- 其余按 theme 分组，每组不超过 max_items
- 输出 WatchlistShard 列表，供 wrapper 串行/并发调用 Agent
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class WatchlistShard:
    name: str
    items: list[dict]
    is_priority: bool


def _pure_code(code: Any) -> str:
    """提取 6 位数字代码，用于去重与匹配。"""
    if not code:
        return ""
    s = str(code).strip()
    for marker in (".SH", ".SZ", ".BJ"):
        s = s.replace(marker, "").replace(marker.lower(), "")
    for prefix in ("sh", "sz", "bj"):
        if s.lower().startswith(prefix):
            s = s[len(prefix):]
    if "." in s:
        s = s.split(".")[-1]
    return s if s.isdigit() else ""


def _normalize_watchlist(watchlist: dict | list | None) -> list[dict]:
    """统一把 watchlist 转成扁平股票字典列表。"""
    if not watchlist:
        return []

    if isinstance(watchlist, list):
        if all(isinstance(w, dict) and "code" in w for w in watchlist):
            return list(watchlist)
        result: list[dict] = []
        for item in watchlist:
            if not isinstance(item, dict):
                continue
            if "stocks" in item:
                theme_name = item.get("name", "")
                for s in item.get("stocks") or []:
                    if isinstance(s, dict):
                        stock = dict(s)
                        if not stock.get("theme"):
                            stock["theme"] = theme_name
                        result.append(stock)
            elif "code" in item:
                result.append(dict(item))
        return result

    if isinstance(watchlist, dict):
        if "themes" in watchlist:
            result = []
            for theme in watchlist.get("themes") or []:
                if not isinstance(theme, dict):
                    continue
                theme_name = theme.get("name", "")
                for s in theme.get("stocks") or []:
                    if isinstance(s, dict):
                        stock = dict(s)
                        if not stock.get("theme"):
                            stock["theme"] = theme_name
                        result.append(stock)
            return result
        if "stocks" in watchlist:
            return list(watchlist.get("stocks") or [])
        return []

    return []


def _normalize_position_codes(positions: dict | list | None) -> set[str]:
    """从 positions 中提取所有股票代码（支持 dict/accounts 或 list）。"""
    codes: set[str] = set()
    if not positions:
        return codes

    if isinstance(positions, dict):
        for acc in positions.get("accounts", []) or []:
            if not isinstance(acc, dict):
                continue
            for pos in acc.get("positions", []) or []:
                if isinstance(pos, dict):
                    pure = _pure_code(pos.get("code", ""))
                    if pure:
                        codes.add(pure)
        for pos in positions.get("positions", []) or []:
            if isinstance(pos, dict):
                pure = _pure_code(pos.get("code", ""))
                if pure:
                    codes.add(pure)
        return codes

    if isinstance(positions, list):
        for pos in positions:
            if isinstance(pos, dict):
                pure = _pure_code(pos.get("code", ""))
                if pure:
                    codes.add(pure)
        return codes

    return codes


def shard_watchlist(
    watchlist: dict | list | None,
    positions: dict | list | None,
    max_items: int = 8,
) -> list[WatchlistShard]:
    """把 watchlist 拆分为 priority shard + theme-based shards。

    Args:
        watchlist: 观察池，支持 {themes: [...]} / {stocks: [...]} / list
        positions: 持仓，支持 {accounts: [{positions}]} / list
        max_items: 每个非优先 shard 最多包含多少只股票

    Returns:
        WatchlistShard 列表。第一个 shard 是 priority（P1+持仓），
        后续按 theme 分组并继续切分，确保每个 shard.items 长度 <= max_items。
    """
    items = _normalize_watchlist(watchlist)
    position_codes = _normalize_position_codes(positions)

    # 去重：同一只股票只保留一条（以先出现的为准）
    seen: set[str] = set()
    unique_items: list[dict] = []
    for item in items:
        code = _pure_code(item.get("code", ""))
        if not code or code in seen:
            continue
        seen.add(code)
        unique_items.append(item)

    priority_items: list[dict] = []
    other_items: list[dict] = []
    for item in unique_items:
        code = _pure_code(item.get("code", ""))
        priority = str(item.get("priority", "")).strip()
        if priority.startswith("P1") or code in position_codes:
            priority_items.append(item)
        else:
            other_items.append(item)

    shards: list[WatchlistShard] = []
    if priority_items:
        shards.append(WatchlistShard(name="priority", items=priority_items, is_priority=True))

    # 按 theme 分组；无 theme 的放入 uncategorized
    groups: dict[str, list[dict]] = {}
    for item in other_items:
        theme = str(item.get("theme", "") or "uncategorized").strip() or "uncategorized"
        groups.setdefault(theme, []).append(item)

    for theme, group_items in groups.items():
        for idx in range(0, len(group_items), max_items):
            chunk = group_items[idx : idx + max_items]
            shard_name = f"{theme}_{idx // max_items + 1}" if len(group_items) > max_items else theme
            shards.append(WatchlistShard(name=shard_name, items=chunk, is_priority=False))

    return shards


def shard_to_context(shard: WatchlistShard) -> dict:
    """把 WatchlistShard 转成可传入 AgentState / API 的上下文字典。"""
    return {
        "name": shard.name,
        "is_priority": shard.is_priority,
        "items": [
            {
                "code": item.get("code", ""),
                "name": item.get("name", ""),
                "priority": item.get("priority", ""),
                "theme": item.get("theme", ""),
            }
            for item in shard.items
        ],
    }
