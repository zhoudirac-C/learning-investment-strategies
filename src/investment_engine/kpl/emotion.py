"""情绪快照：Index.GetInfo 全量 View 一次拉取 + 落盘。

六个块保留 API 原始结构（不过度归一化）：DaBanList=object、PHBList/ErBanList/
BaceFaceList=数组列表、FKYDSixList=object 列表、CWeatherVaneList={SZ,XD}。
不同 View 组合返回块不同，缺块给空默认值。
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from investment_engine.kpl.client import KplClient

FULL_VIEW = "2,3,4,5,7,8,9,10,11"

# 响应块名 → (落盘 key, 缺块默认值工厂)
BLOCKS = {
    "DaBanList": ("daban", dict),
    "PHBList": ("lianban", list),
    "ErBanList": ("erban", list),
    "FKYDSixList": ("fengkou", list),
    "BaceFaceList": ("bankuai", list),
    "CWeatherVaneList": ("fengxiang", dict),
}


def fetch_snapshot(client: KplClient) -> dict:
    """拉取全量情绪快照，返回 {date, fetched_at, 六个块}。"""
    resp = client.post("apphwhq", "Index", "GetInfo", {"View": FULL_VIEW})
    out = {
        "date": resp.get("Day") or date.today().isoformat(),
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
    }
    for src_key, (dst_key, default_factory) in BLOCKS.items():
        val = resp.get(src_key)
        out[dst_key] = val if val is not None else default_factory()
    return out


def save_snapshot(data: dict, out_root: Path, day: str) -> Path:
    """写 <out_root>/emotion/<day>.json（ensure_ascii=False 便于人工审阅）。"""
    out_dir = Path(out_root) / "emotion"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{day}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path
