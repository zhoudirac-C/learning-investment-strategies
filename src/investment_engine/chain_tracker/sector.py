"""板块异动触发器：fund_flow 本地落盘 → 发现候选（任务书 §3.3 第三触发源）。

任务书原计划用东财板块 API 实时涨幅，本机不可达（Phase 2 实测 push2 断连）。
替代数据源：infra/data/fund_flow/{yyyymmdd}.json（每日 15:40 cron 落盘，
akshare 东财资金流），concept.即时 覆盖 387 个概念板块，粒度贴合产业链环节；
sector_intraday 只有 11 个硬编码板块，覆盖面不足，不用。

注意：fund_flow 是每日一次快照（akshare 只返回最新值），所以板块异动是
日级触发源——当日 15:40 后的发现 tick 首次读到该日文件时生效。
"""
from __future__ import annotations

import json
from pathlib import Path

DEFAULT_SECTOR_THRESHOLD_PCT = 3.0


def default_fund_flow_root() -> Path:
    from qing_investment.paths import repo_root

    return repo_root() / "infra" / "data" / "fund_flow"


def _to_float(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _iter_boards(data: dict):
    """产出 (board_type, name, pct, leader, leader_pct)；只取'即时'窗口（当日涨跌幅）。"""
    for board_type in ("concept", "industry"):
        section = data.get(board_type) or {}
        rows = section.get("即时") or []
        for r in rows:
            if not isinstance(r, dict):
                continue
            name = str(r.get("行业") or "").strip()
            pct = _to_float(r.get("行业-涨跌幅"))
            if not name or pct is None:
                continue
            yield (board_type, name, pct,
                   str(r.get("领涨股") or "").strip(),
                   _to_float(r.get("领涨股-涨跌幅")))


def load_sector_anomalies(date: str, *, root: Path | str | None = None,
                          threshold_pct: float = DEFAULT_SECTOR_THRESHOLD_PCT
                          ) -> list[dict]:
    """读取当日 fund_flow 落盘，筛 |涨跌幅| >= threshold 的板块 → InfoItem 列表。

    info_id = sector:{date}:{board_type}:{name}（日级去重键）。
    文件缺失/损坏 → 返回 []（触发源缺席不阻断 tick）。
    """
    root = Path(root) if root else default_fund_flow_root()
    path = root / f"{date.replace('-', '')}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict):
        return []

    items: list[dict] = []
    for board_type, name, pct, leader, leader_pct in _iter_boards(data):
        if abs(pct) < threshold_pct:
            continue
        direction = "涨" if pct >= 0 else "跌"
        leader_txt = (f"（领涨 {leader} {leader_pct:+.1f}%）"
                      if leader and leader_pct is not None else "")
        items.append({
            "info_id": f"sector:{date}:{board_type}:{name}",
            "source": "sector",
            "title": f"{name}板块{direction} {abs(pct):.1f}%{leader_txt}",
            "published_at": date,
            "stock_code": None,
            "stock_name": None,
            "industry_name": name,
            "org": "东财资金流",
            "url": None,
            "chain_ids": [],
        })
    return items
