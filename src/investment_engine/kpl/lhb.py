"""龙虎榜游资榜：UserBusiness.GetDay（applhb 子域）拉取 + 落盘。

接口结构见 docs/design/kpl-api-inventory.md 第 5 节（2026-08-11 实测修正）：
TList=分类列表（顶级/一线/知名/机构/庄股）、List=按分类 ID 分组的 dict（值为席位明细数组）、
Day/NDay=披露日/上一披露日（Day 参数可回溯历史披露日）。

实测注意：本账号 List 各类恒为空——2026-08-10 抓包样本（Day=2026-08-07）与
08-11 三次实测（含 Day 回溯）一致，疑席位明细走 App 直连通道或需额外权益。
空明细属现状而非异常：落盘 entry_count=0 + note 如实标注，不报错。
个股席位明细可用 Stock.GetNewOneStockInfo（BuyList/SellList 含营业部与金额）。
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from investment_engine.kpl.client import KplClient

EMPTY_NOTE = ("上榜明细为空（本账号 GetDay 不返回席位明细，2026-08-10 抓包与 08-11 实测一致；"
              "个股席位走 Stock.GetNewOneStockInfo）")


def _count_entries(raw: object) -> int:
    """List 真实形态为 {分类ID: [明细...]}（空也带 6 个键）；兼容早期扁平数组假设。"""
    if isinstance(raw, dict):
        return sum(len(v) for v in raw.values())
    if isinstance(raw, list):
        return len(raw)
    return 0


def fetch_lhb(client: KplClient, day: str | None = None) -> dict:
    """拉取龙虎榜游资榜。day 给出时传 Day 参数回溯历史披露日，默认取最新。

    返回 {date, fetched_at, disclosure_day, prev_disclosure_day, tlist, list,
    entry_count, note}。
    """
    params = {"Day": day} if day else None
    resp = client.post("applhb", "UserBusiness", "GetDay", params)
    raw = resp.get("List") or {}
    count = _count_entries(raw)
    return {
        "date": date.today().isoformat(),
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "disclosure_day": resp.get("Day") or "",
        "prev_disclosure_day": resp.get("NDay") or "",
        "tlist": resp.get("TList") or [],
        "list": raw,
        "entry_count": count,
        "note": "" if count else EMPTY_NOTE,
    }


def save_lhb(data: dict, out_root: Path, day: str) -> Path:
    """写 <out_root>/lhb/<day>.json。"""
    out_dir = Path(out_root) / "lhb"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{day}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path
