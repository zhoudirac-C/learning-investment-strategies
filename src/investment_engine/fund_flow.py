"""板块资金流：akshare 行业/概念资金流四窗口拉取 + 落盘（C1/C4）。

用途（spec: framework/proposals/2026-08-17-fix-blind-shadow-merged.md 批次 P2）：
- 行业（90）+ 概念（约 387）资金流的 即时/3日/5日/10日 四窗口快照，
  回答「换手方向 + 持续性」（A3 量能源头判断、C4 板块间资金迁移的前提数据）
- cron 15:40 前后落盘（与 limit_pool 同窗口），供盘后/盘前数据包使用

接口实测（2026-08-17，akshare 1.18.64）：
- ak.stock_fund_flow_industry(symbol="即时"/"3日排行"/"5日排行"/"10日排行") ✅
  90 行业，字段含 流入资金/流出资金/净额/领涨股
- ak.stock_fund_flow_concept(symbol=...) ✅ 约 387 概念，同构字段
- ❌ ak.stock_sector_fund_flow_rank / ak.stock_main_fund_flow 本机被东财拒连，勿用

限制：两个接口只返回最新快照，无 date 参数 → 无法回溯历史，须每日 cron 落盘累积。
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime
from pathlib import Path

WINDOWS = ("即时", "3日排行", "5日排行", "10日排行")
KINDS = ("industry", "concept")
REQUEST_INTERVAL = 0.3  # 窗口间节流，降低被东财风控概率


def _df_records(df) -> list[dict]:
    """DataFrame → list[dict]；NaN/NaT 统一转 None，numpy 标量转 Python 原生类型。"""
    if df is None or df.empty:
        return []
    out: list[dict] = []
    for row in df.astype(object).where(df.notna(), None).to_dict("records"):
        clean: dict = {}
        for k, v in row.items():
            if hasattr(v, "item"):  # numpy 标量 → Python 原生（JSON 可序列化）
                try:
                    v = v.item()
                except Exception:
                    pass
            clean[str(k)] = v
        out.append(clean)
    return out


def _fetch_window(kind: str, symbol: str) -> list[dict]:
    """拉单个资金流窗口。kind ∈ KINDS，symbol ∈ WINDOWS。"""
    import akshare as ak
    func = {"industry": ak.stock_fund_flow_industry,
            "concept": ak.stock_fund_flow_concept}[kind]
    return _df_records(func(symbol=symbol))


def fetch_fund_flow() -> dict:
    """组装行业+概念四窗口资金流快照。

    单窗口失败不阻断：该窗口记 None，错误信息收进 errors 列表。
    date 为拉取当日（快照实际交易日以数据为准，调用方/cron 保证当日为交易日）。
    """
    payload: dict = {
        "date": date.today().isoformat(),
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "industry": {},
        "concept": {},
        "errors": [],
    }
    for kind in KINDS:
        for symbol in WINDOWS:
            try:
                payload[kind][symbol] = _fetch_window(kind, symbol)
            except Exception as e:
                payload[kind][symbol] = None
                payload["errors"].append(f"{kind}/{symbol}: {e}")
            time.sleep(REQUEST_INTERVAL)
    return payload


def save_fund_flow(payload: dict,
                   data_dir: Path = Path("infra/data/fund_flow")) -> Path:
    """写 <data_dir>/<yyyymmdd>.json，文件名由 payload["date"]（YYYY-MM-DD）推导。"""
    out_dir = Path(data_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{payload['date'].replace('-', '')}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8")
    return path
