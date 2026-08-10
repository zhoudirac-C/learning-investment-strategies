"""龙虎榜游资榜：UserBusiness.GetDay（applhb 子域）拉取 + 落盘。

接口结构见 docs/design/kpl-api-inventory.md 第 5 节（2026-08-10 抓包记录）：
TList=分类列表（顶级/一线/知名/机构/庄股）、List=当日上榜明细、Day/NDay=披露日/上一披露日。
T 日收盘后披露——非披露日或披露未出时 List 为空，属正常：落盘 note 标注，不报错。
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from investment_engine.kpl.client import KplClient


def fetch_lhb(client: KplClient) -> dict:
    """拉取龙虎榜游资榜，返回 {date, fetched_at, disclosure_day, prev_disclosure_day, tlist, list, note}。"""
    resp = client.post("applhb", "UserBusiness", "GetDay")
    items = resp.get("List") or []
    return {
        "date": date.today().isoformat(),
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "disclosure_day": resp.get("Day") or "",
        "prev_disclosure_day": resp.get("NDay") or "",
        "tlist": resp.get("TList") or [],
        "list": items,
        "note": "" if items else "当日上榜明细为空（非披露日或披露未出）",
    }


def save_lhb(data: dict, out_root: Path, day: str) -> Path:
    """写 <out_root>/lhb/<day>.json。"""
    out_dir = Path(out_root) / "lhb"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{day}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path
