"""异动驱动发现规则层（引擎 B 核心，docs/design/chain-momentum-discovery-design.md §4）。

职责：limit_pool（涨停池）+ fund_flow（板块资金流）本地落盘 → 题材热度卡
→ 触发规则 → 阶段初判。全部纯函数/规则，零 LLM；LLM 拆链在触发之后由
discovery 层执行。

数据源：
    infra/data/limit_pool/{yyyymmdd}.json   盘后落盘（zt_items 含 hybk/lbc/fund/fbt）
    infra/data/fund_flow/{yyyymmdd}.json    15:40 落盘（concept 板块涨幅，交叉验证）

与 sector.py 的关系：sector.py 产出"裸板块行"走研报 prompt（实证 100%
no_proposal，见设计文档 §1）；本模块把同一 fund_flow 数据与涨停池聚合为
结构化热度卡，改走专用拆链 prompt（discovery.build_momentum_messages）。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

DEFAULT_MIN_ZT_COUNT = 3       # 板块涨停 >= 3 家触发（zt_burst）
DEFAULT_LADDER_MIN_LBC = 2     # 出现 >= 2 板梯队且涨停 >= 2 家触发（ladder）
DEFAULT_SECTOR_PCT = 3.0       # fund_flow 涨幅 >= 3% 且涨停 >= 2 家（resonance）
BROKEN_RATIO_DIVERGENCE = 0.3  # 炸板占比阈值（分歧期）
ZT_GROWTH_ACCEL = 0.5          # 涨停家数环比增速阈值（加速期）

STAGE_STARTUP = "阶段1-启动期"
STAGE_ACCELERATION = "阶段2-加速期"
STAGE_DIVERGENCE = "阶段3-分歧期"
STAGE_TOP = "阶段4-见顶期"


def default_limit_pool_root() -> Path:
    from qing_investment.paths import repo_root

    return repo_root() / "infra" / "data" / "limit_pool"


def default_fund_flow_root() -> Path:
    from qing_investment.paths import repo_root

    return repo_root() / "infra" / "data" / "fund_flow"


def _load_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def load_limit_pool(date: str, *, root: Path | str | None = None) -> dict | None:
    """读取当日涨停池；缺失/损坏返回 None（数据源缺席不阻断 tick）。"""
    root = Path(root) if root else default_limit_pool_root()
    return _load_json(root / f"{date.replace('-', '')}.json")


def load_fund_flow(date: str, *, root: Path | str | None = None) -> dict | None:
    root = Path(root) if root else default_fund_flow_root()
    return _load_json(root / f"{date.replace('-', '')}.json")


def _fmt_fbt(fbt) -> str | None:
    """'92500' → '09:25'；无法解析返回 None。"""
    s = str(fbt or "").strip().zfill(6)
    if len(s) != 6 or not s.isdigit():
        return None
    return f"{s[:2]}:{s[2:4]}"


def _flow_board_pct(flow: dict | None) -> dict[str, float]:
    """fund_flow concept/industry '即时'窗口 → {板块名: 涨跌幅}。"""
    out: dict[str, float] = {}
    if not flow:
        return out
    for section in ("concept", "industry"):
        for r in (flow.get(section) or {}).get("即时") or []:
            if not isinstance(r, dict):
                continue
            name = str(r.get("行业") or "").strip()
            try:
                pct = float(r.get("行业-涨跌幅"))
            except (TypeError, ValueError):
                continue
            if name:
                out[name] = pct
    return out


def _match_sector_pct(theme: str, board_pct: dict[str, float]) -> float | None:
    """精确名优先，其次互相包含（'通信设备' vs '通信设备概念'）；都不中返回 None。"""
    if theme in board_pct:
        return board_pct[theme]
    for name, pct in board_pct.items():
        if theme in name or name in theme:
            return pct
    return None


def aggregate_theme_cards(date: str | None = None, *,
                          pool: dict | None = None,
                          flow: dict | None = None,
                          prev_pool: dict | None = None,
                          pool_root: Path | str | None = None,
                          flow_root: Path | str | None = None) -> list[dict]:
    """涨停池按 hybk 聚合为题材热度卡；flow/prev_pool 可注入（测试）或按 root 读盘。

    card 字段见设计文档 §4.1；另含 broken_count（同板块炸板数）与
    stocks（涨停明细，供 LLM 拆链）。streak_days 仅回溯一日（1 或 2）。
    """
    if pool is None:
        if date is None:
            raise ValueError("pool 与 date 至少给一个")
        pool = load_limit_pool(date, root=pool_root)
    if not pool:
        return []
    if flow is None and date is not None:
        flow = load_fund_flow(date, root=flow_root)
    if prev_pool is None and date is not None:
        prev_date = (datetime.strptime(date, "%Y-%m-%d")
                     - timedelta(days=1)).date().isoformat()
        prev_pool = load_limit_pool(prev_date, root=pool_root)

    board_pct = _flow_board_pct(flow)
    prev_counts: dict[str, int] = {}
    for it in (prev_pool or {}).get("zt_items") or []:
        name = str(it.get("hybk") or "").strip()
        if name:
            prev_counts[name] = prev_counts.get(name, 0) + 1

    broken_counts: dict[str, int] = {}
    for it in pool.get("zb_items") or []:
        name = str(it.get("hybk") or "").strip()
        if name:
            broken_counts[name] = broken_counts.get(name, 0) + 1

    groups: dict[str, list[dict]] = {}
    for it in pool.get("zt_items") or []:
        if not isinstance(it, dict):
            continue
        name = str(it.get("hybk") or "").strip()
        if name:
            groups.setdefault(name, []).append(it)

    cards: list[dict] = []
    for theme, stocks in groups.items():
        def _lbc(s: dict) -> int:
            try:
                return int(s.get("lbc") or 1)
            except (TypeError, ValueError):
                return 1

        def _fund(s: dict) -> float:
            try:
                return float(s.get("fund") or 0)
            except (TypeError, ValueError):
                return 0.0

        ordered = sorted(stocks, key=lambda s: (-_lbc(s), -_fund(s)))
        seals = [t for t in (_fmt_fbt(s.get("fbt")) for s in stocks) if t]
        cards.append({
            "theme": theme,
            "zt_count": len(stocks),
            "first_board_count": sum(1 for s in stocks if _lbc(s) <= 1),
            "max_lbc": max((_lbc(s) for s in stocks), default=1),
            "seal_fund": sum(_fund(s) for s in stocks),
            "earliest_seal": min(seals) if seals else None,
            "leaders": [str(s.get("name") or "") for s in ordered[:5]],
            "sector_pct": _match_sector_pct(theme, board_pct),
            "streak_days": 2 if prev_counts.get(theme, 0) >= 2 else 1,
            "prev_zt_count": prev_counts.get(theme, 0),
            "broken_count": broken_counts.get(theme, 0),
            "stocks": [{
                "code": s.get("code"), "name": s.get("name"),
                "lbc": _lbc(s), "fund": _fund(s),
                "fbt": _fmt_fbt(s.get("fbt")), "pct": s.get("pct"),
            } for s in ordered],
        })
    cards.sort(key=lambda c: (-c["zt_count"], -c["max_lbc"]))
    return cards


def trigger_themes(cards: list[dict], *,
                   min_zt: int = DEFAULT_MIN_ZT_COUNT,
                   ladder_min_lbc: int = DEFAULT_LADDER_MIN_LBC,
                   sector_pct: float = DEFAULT_SECTOR_PCT) -> list[dict]:
    """触发规则（设计 §4.2）：命中的 card 附 trigger_reasons 返回。"""
    out: list[dict] = []
    for c in cards:
        reasons: list[str] = []
        if c["zt_count"] >= min_zt:
            reasons.append("zt_burst")
        if c["max_lbc"] >= ladder_min_lbc and c["zt_count"] >= 2:
            reasons.append("ladder")
        if (c.get("sector_pct") is not None and c["sector_pct"] >= sector_pct
                and c["zt_count"] >= 2):
            reasons.append("resonance")
        if reasons:
            out.append({**c, "trigger_reasons": reasons})
    return out


def judge_stage(card: dict, prev_card: dict | None = None) -> tuple[str, dict]:
    """阶段初判（设计 §4.3）：返回 (stage, evidence)。评估顺序 4→3→2→1。

    prev_card 通常为昨日同题材卡；没有时退化为当日规则（分歧/见顶无法判）。
    """
    zt = card.get("zt_count") or 0
    first = card.get("first_board_count") or 0
    max_lbc = card.get("max_lbc") or 1
    broken = card.get("broken_count") or 0
    streak = card.get("streak_days") or 1
    prev_zt = (prev_card or {}).get("zt_count") or card.get("prev_zt_count") or 0
    prev_lbc = (prev_card or {}).get("max_lbc") or 0

    first_ratio = first / zt if zt else 0.0
    broken_ratio = broken / (zt + broken) if (zt + broken) else 0.0
    zt_growth = (zt - prev_zt) / prev_zt if prev_zt else 0.0
    evidence = {"first_board_ratio": first_ratio, "broken_ratio": broken_ratio,
                "zt_growth": zt_growth, "max_lbc": max_lbc,
                "prev_max_lbc": prev_lbc, "streak_days": streak}

    # 阶段4-见顶期：高度板断板 + 板块涨停 <= 1 家
    if prev_lbc >= 3 and max_lbc <= 1 and zt <= 1:
        return STAGE_TOP, evidence
    # 阶段3-分歧期：涨停家数环比降 + 炸板占比 > 30%
    if prev_zt and zt < prev_zt and broken_ratio > BROKEN_RATIO_DIVERGENCE:
        return STAGE_DIVERGENCE, evidence
    # 阶段2-加速期：max_lbc >= 3 或涨停环比增 >= 50%
    if max_lbc >= 3 or (prev_zt and zt_growth >= ZT_GROWTH_ACCEL):
        return STAGE_ACCELERATION, evidence
    # 阶段1-启动期：首板占比 > 70% 且 streak <= 2（兜底也归此档）
    return STAGE_STARTUP, evidence
