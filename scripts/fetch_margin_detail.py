#!/usr/bin/env python3
"""个股融资余额日更（板块情绪温度计的融资腿）。

数据源：东财 datacenter RPTA_WEB_RZRQ_GGMX（实测通；字段 SCODE/SECNAME/RZYE/RZMRE/DATE）。
产出 infra/data/margin/YYYY-MM-DD.json = {6位代码: {"rzye": 融资余额, "rzmre": 融资买入额}}。
板块聚合由 board_sentiment_daily.py 编排层按 board_members 映射汇总。

手动: .venv/bin/python scripts/fetch_margin_detail.py [--date YYYYMMDD]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "infra" / "data" / "margin"
EM_BASE = "https://datacenter-web.eastmoney.com/api/data/v1/get"
EM_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"}
SLEEP_S = 1.5


def em_get(report: str, filter_str: str, page_size: int = 500) -> list[dict]:
    rows: list[dict] = []
    page = 1
    while True:
        params = {"reportName": report, "columns": "ALL", "filter": filter_str,
                  "pageNumber": page, "pageSize": page_size,
                  "sortColumns": "RZYE", "sortTypes": "-1", "source": "WEB"}
        url = f"{EM_BASE}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers=EM_HEADERS)
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read().decode())
        result = d.get("result") or {}
        data = result.get("data") or []
        rows.extend(data)
        if page >= (result.get("pages") or 1):
            break
        page += 1
        time.sleep(SLEEP_S)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now().strftime("%Y%m%d"))
    args = ap.parse_args()
    date = args.date
    iso = f"{date[:4]}-{date[4:6]}-{date[6:]}"

    rows = em_get("RPTA_WEB_RZRQ_GGMX", f"(DATE='{iso}')")
    print(f"融资明细 {len(rows)} 条", file=sys.stderr)
    if not rows:
        print(f"WARN 无数据（{iso} 可能非交易日/数据未出）", file=sys.stderr)
        return 1

    out = {}
    for r in rows:
        code = str(r.get("SCODE") or "").zfill(6)
        if not code.strip():
            continue
        out[code] = {"rzye": float(r.get("RZYE") or 0),
                     "rzmre": float(r.get("RZMRE") or 0)}

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    p = OUT_DIR / f"{iso}.json"
    p.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"落盘 {p}: {len(out)} 只", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
