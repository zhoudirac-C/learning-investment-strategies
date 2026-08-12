"""盘中异动：akshare stock_changes_em 拉取 + 落盘。

用途：补 KPL 抓不到的盘中事件型异动（火箭发射/封涨停板/大笔买入等 22 种）。
KPL 异动走个推推送+原生通道，用户级代理无解（见 docs/design/kpl-api-inventory.md）；
akshare 封装东财盘口异动接口，免费无 token，结构化输出异动类型/时间/个股。

口径与限制：
- 数据源：东方财富盘口异动（akshare stock_changes_em）
- 只返回最近一个交易日，无 date 参数 → 无法回溯历史，须收盘后 cron 落盘累积
- 22 种异动类型见 CHANGE_TYPES
- 相关信息字段为逗号串（封涨停价,成交量,最新价,涨幅），涨幅在末段
"""
from __future__ import annotations

import json
import time
from pathlib import Path

# 22 种异动类型（akshare stock_changes_em symbol 取值）
CHANGE_TYPES = (
    "火箭发射", "快速反弹", "大笔买入", "封涨停板", "打开跌停板", "有大买盘",
    "竞价上涨", "高开5日线", "向上缺口", "60日新高", "60日大幅上涨",
    "加速下跌", "高台跳水", "大笔卖出", "封跌停板", "打开涨停板", "有大卖盘",
    "竞价下跌", "低开5日线", "向下缺口", "60日新低", "60日大幅下跌",
)

# 盘后落盘时每类保留的明细上限（全量落盘太大，取封单额/涨幅靠前的）
_ITEM_CAP_PER_TYPE = 200
REQUEST_INTERVAL = 0.3


class IntradayChangesError(Exception):
    """盘中异动拉取失败。"""


def _fetch_one(symbol: str) -> list[dict]:
    """拉单个异动类型的当日明细。返回 [{time, code, name, sector, info}]。"""
    import akshare as ak
    df = ak.stock_changes_em(symbol=symbol)
    if df is None or df.empty:
        return []
    rows: list[dict] = []
    for _, r in df.iterrows():
        rows.append({
            "time": str(r.get("时间", "")),
            "code": str(r.get("代码", "")),
            "name": str(r.get("名称", "")),
            "sector": str(r.get("板块", "")),
            "info": str(r.get("相关信息", "")),
        })
    return rows[:_ITEM_CAP_PER_TYPE]


def _parse_pct(info: str) -> str:
    """相关信息 '价,量,最新价,涨幅' → 取末段涨幅。"""
    parts = info.split(",")
    return parts[-1].strip() if parts else ""


def build_intraday_changes(day: str) -> dict:
    """组装当日盘中异动。day 格式 YYYYMMDD。

    遍历 22 种类型拉取；单类失败不阻断，记 error 继续下一类。
    """
    types_out: dict[str, object] = {}
    counts: dict[str, int | None] = {}
    for sym in CHANGE_TYPES:
        try:
            rows = _fetch_one(sym)
        except Exception as e:
            counts[sym] = None
            types_out[sym] = {"error": str(e)}
            time.sleep(REQUEST_INTERVAL)
            continue
        types_out[sym] = rows
        counts[sym] = len(rows)
        time.sleep(REQUEST_INTERVAL)
    total = sum(c for c in counts.values() if isinstance(c, int))
    return {
        "date": f"{day[:4]}-{day[4:6]}-{day[6:]}",
        "types": types_out,
        "counts": counts,
        "total": total,
    }


def save_intraday_changes(data: dict, out_root: Path, day: str) -> Path:
    """写 <out_root>/<day>.json（day 为 YYYYMMDD）。"""
    out_dir = Path(out_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{day}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8")
    return path
