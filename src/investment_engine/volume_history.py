"""两市成交额历史序列：指数日K（上证指数+深证成指 amount 合计）回灌 + 落盘。

用途：盲判包 volume_series 块的长历史段（本地 KPL 情绪序列自 2026-08-12 起才逐日
累积，60 日窗口靠本模块补齐）。
口径校验（2026-08-21 实测）：TDX 两指数 amount 合计与 KPL daban.qscln 逐位一致
（2026-08-19：25110.4 亿；2026-08-20：20793.6 亿）。
2026-09-23 复核：迁移统一模块后东财源 9/22 合计 21356 亿，与 KPL 口径一致。

实施形态对齐 global_macro/sector_intraday 先例（compute/save/load 三件套 +
scripts/volume_history_fetch.py 幂等落盘）。

数据源（2026-09-23 迁移）：**统一收口模块 `qing_investment.marketdata`**。
- 原实现直连 `TdxMarket.get_index_kline`，TDX `CapMainKline` 已被服务端按接口
  粒度封禁 → 死链。
- **日K 链必须含 eastmoney**：腾讯/新浪日 bar 的 amount 恒为 0.0
  （2026-09-23 实测：腾讯 [date,open,close,high,low,volume] 仅 6 段、无额字段）。
  且注意东财 klt=101 在本环境经 urllib 会 `Remote end closed`——统一模块
  http 层已带重试，间歇窗口内可成功。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

DATA_PATH = Path("infra/data/volume_history.json")

_INDEX_PAIR = ("sh000001", "sz399001")  # 上证指数 + 深证成指
_DEFAULT_COUNT = 70  # 回看根数（≈60 个交易日 + 假期冗余）

#: 日K 成交额源优先级——**必须含 eastmoney**（腾讯/新浪日 bar amount 恒 0）。
_AMOUNT_SOURCES = ["eastmoney", "tencent"]


def _fetch_daily(code: str, count: int):
    """拉指数日K（统一模块）。返回 (bars, source)；失败返回 ([], err)。"""
    from qing_investment import marketdata as md

    try:
        return md.get_index_kline(code, klt=101, count=count,
                                  sources=_AMOUNT_SOURCES)
    except Exception as e:  # noqa: BLE001
        return [], f"{type(e).__name__}: {str(e)[:120]}"


def compute_volume_history(count: int = _DEFAULT_COUNT, *, tdx=None) -> dict | None:
    """拉两指数日K，合计成交额（元→亿，1 位小数），时间正序。全败返回 None。

    tdx: **兼容保留**——历史测试注入 TdxMarket 兼容对象（须实现
        ``get_index_kline(code, category="day", count=N)``）；None 时走统一模块
        （2026-09-23 迁移）。
    """
    source_note = ""
    if tdx is not None:
        sh = tdx.get_index_kline(_INDEX_PAIR[0], category="day", count=count) or []
        sz_raw = tdx.get_index_kline(_INDEX_PAIR[1], category="day", count=count) or []
        source_note = "injected"
    else:
        sh, s1 = _fetch_daily(_INDEX_PAIR[0], count)
        sz_raw, s2 = _fetch_daily(_INDEX_PAIR[1], count)
        source_note = f"{s1}/{s2}"
        if not sh or not sz_raw:
            return None
    # 日期键兼容：TdxMarket 用 date，统一模块用 bar_time
    sz = {str(r.get("date") or r.get("bar_time")): r for r in sz_raw}
    points = []
    for r in sh:
        d = str(r.get("date") or r.get("bar_time") or "")
        a = r.get("amount")
        b = (sz.get(d) or {}).get("amount")
        if d and isinstance(a, (int, float)) and isinstance(b, (int, float)) and (a or b):
            points.append({"date": d, "成交额_亿": round((a + b) / 1e8, 1)})
    if not points:
        return None
    return {"points": points,
            "source": f"marketdata 上证指数+深证成指日K amount 合计（元→亿） [{source_note}]",
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
