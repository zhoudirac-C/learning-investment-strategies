"""分时量能：TDX 60min 四点曲线计算 + 落盘/读取（C1 分时腿）。

逻辑 2026-08-17 原样抽自 blindtest/dataset.py `_load_intraday_amount`（只抽取，
不改原文件；dataset 改优先读盘的接线另行完成）：用 TDX 拉上证+深证 60min 成交额，
构建盘中量能形态（放量/缩量判断），键名与 dataset 现产出完全一致
（prompt 规则 9 引用「形态」字段，一个字都不能改）。
对齐 UP「开盘近3万亿→尾盘2.5万亿=全天缩量」口径：预估全天 = 累计 × (240/已交易分钟)。

与 dataset 版唯一差异：day 不再入参，改由 TDX 返回数据推导（最新一根 60min K 线
所在交易日），便于收盘后 cron 落盘；非交易时段跑得到的是最近交易日的 4 根 K 线。
TDX 不可达/当日数据不足时返回 None（与 dataset 现状一致）。
"""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_DATA_DIR = Path("infra/data/intraday_amount")

_MINUTE_MAP = {"10:30": 60, "11:30": 120, "14:00": 180, "15:00": 240}


def compute_intraday_amount(tdx=None) -> dict | None:
    """用 TDX 拉上证+深证 60min 成交额，构建盘中量能形态。

    tdx 可注入 TdxMarket 兼容对象（测试用）；None 时自建 TdxMarket。
    返回 None（TDX 拉取失败/当日数据不足）或：
    {date, 分时[{时点,累计_亿,预估全天_亿}], 开盘预估全天_亿, 尾盘实际全天_亿, 形态}。
    """
    try:
        mkt = tdx
        if mkt is None:
            from qing_investment.tdx_market import TdxMarket
            mkt = TdxMarket()
        sh = mkt.get_kline("sh000001", "60min", count=16)
        sz = mkt.get_kline("sz399001", "60min", count=16)
    except Exception:
        return None
    if not sh or not sz:
        return None
    day = str(sh[-1].get("datetime", ""))[:10]  # 数据实际交易日（pytdx 时间正序）
    sh_day = [r for r in sh if str(r.get("datetime", ""))[:10] == day]
    sz_day = [r for r in sz if str(r.get("datetime", ""))[:10] == day]
    if len(sh_day) < 4 or len(sz_day) < 4:
        return None
    minute_map = _MINUTE_MAP
    rows = []
    cum = 0.0
    for i in range(4):
        sh_amt = sh_day[i].get("amount") or 0
        sz_amt = sz_day[i].get("amount") or 0
        cum += (sh_amt + sz_amt) / 1e8
        hm = str(sh_day[i].get("datetime", ""))[11:16]
        minutes = minute_map.get(hm, 60 * (i + 1))
        est = cum * (240.0 / minutes)
        rows.append({"时点": hm, "累计_亿": round(cum, 0), "预估全天_亿": round(est, 0)})
    open_est = rows[0]["预估全天_亿"]
    close_actual = rows[-1]["累计_亿"]
    if open_est > close_actual * 1.2:
        shape = "冲量滑落（全天缩量）"
    elif close_actual > open_est * 1.1:
        shape = "逐级放大（健康放量）"
    else:
        shape = "平量"
    return {"date": day, "分时": rows, "开盘预估全天_亿": open_est,
            "尾盘实际全天_亿": round(close_actual, 0), "形态": shape}


def load_intraday_amount(day: str,
                         data_dir: Path = DEFAULT_DATA_DIR) -> dict | None:
    """读 <data_dir>/<yyyymmdd>.json；day 为 YYYY-MM-DD，不存在返回 None。"""
    path = Path(data_dir) / f"{day.replace('-', '')}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_intraday_amount(day: str, payload: dict,
                         data_dir: Path = DEFAULT_DATA_DIR) -> Path:
    """写 <data_dir>/<yyyymmdd>.json；day 为 YYYY-MM-DD。"""
    out_dir = Path(data_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{day.replace('-', '')}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8")
    return path
