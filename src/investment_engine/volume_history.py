"""两市成交额历史序列：TDX 指数日K（上证指数+深证成指 amount 合计）回灌 + 落盘。

用途：盲判包 volume_series 块的长历史段（本地 KPL 情绪序列自 2026-08-12 起才逐日
累积，60 日窗口靠本模块补齐）。
口径校验（2026-08-21 实测）：TDX 两指数 amount 合计与 KPL daban.qscln 逐位一致
（2026-08-19：25110.4 亿；2026-08-20：20793.6 亿）。

实施形态对齐 global_macro/sector_intraday 先例（compute/save/load 三件套 +
scripts/volume_history_fetch.py 幂等落盘）。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

DATA_PATH = Path("infra/data/volume_history.json")

_INDEX_PAIR = ("sh000001", "sz399001")  # 上证指数 + 深证成指
_DEFAULT_COUNT = 70  # 回看根数（≈60 个交易日 + 假期冗余）


def compute_volume_history(count: int = _DEFAULT_COUNT, *, tdx=None) -> dict | None:
    """拉两指数日K，合计成交额（元→亿，1 位小数），时间正序。全败返回 None。

    tdx 可注入 TdxMarket 兼容对象（测试免网络）；None 时自建 TdxMarket。
    """
    if tdx is None:
        from qing_investment.tdx_market.market import TdxMarket
        tdx = TdxMarket()
    sh = tdx.get_index_kline(_INDEX_PAIR[0], category="day", count=count) or []
    sz = {r.get("date"): r for r in
          (tdx.get_index_kline(_INDEX_PAIR[1], category="day", count=count) or [])}
    points = []
    for r in sh:
        d = r.get("date")
        a, b = r.get("amount"), (sz.get(d) or {}).get("amount")
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            points.append({"date": d, "成交额_亿": round((a + b) / 1e8, 1)})
    if not points:
        return None
    return {"points": points,
            "source": "TDX 上证指数+深证成指日K amount 合计（元→亿）",
            "fetched_at": datetime.now().isoformat(timespec="seconds")}


def save_volume_history(data: dict, path: Path | str = DATA_PATH) -> Path:
    """合并落盘：与既有文件按日期去重（新值覆盖旧值），时间正序。"""
    path = Path(path)
    by_date: dict[str, dict] = {}
    old = load_volume_history(path)
    if old:
        by_date.update({p["date"]: p for p in old.get("points") or []})
    by_date.update({p["date"]: p for p in data.get("points") or []})
    merged = {"points": [by_date[d] for d in sorted(by_date)],
              "source": data.get("source", ""),
              "fetched_at": data.get("fetched_at", "")}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def load_volume_history(path: Path | str = DATA_PATH) -> dict | None:
    """读落盘；无文件/坏文件返回 None。"""
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
