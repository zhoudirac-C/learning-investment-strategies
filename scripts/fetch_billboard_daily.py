#!/usr/bin/env python3
"""龙虎榜日更 + 散户席位识别（板块情绪温度计的资金腿）。

数据源（东财 datacenter，实测通；push2 系本机被封禁用）：
- RPT_BILLBOARD_DAILYDETAILSBUY：营业部级买卖明细（OPERATEDEPT_NAME/BUY/SELL/NET）

散户席位识别：东财拉萨系营业部是 A 股知名的散户集中营，买方占比高 = 散户在接盘。
聚合到 THS 行业板块（board_members 映射），产出：
infra/data/billboard/YYYY-MM-DD.json =
{板块名: {"retail_buy_ratio": 0-1, "board_hits_20d": int,
          "total_buy": float, "stocks": [代码...]}}

手动: .venv/bin/python scripts/fetch_billboard_daily.py [--date YYYYMMDD]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
OUT_DIR = ROOT / "infra" / "data" / "billboard"
EM_BASE = "https://datacenter-web.eastmoney.com/api/data/v1/get"
EM_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"}
SLEEP_S = 1.5

# 拉萨系散户集中营席位（知名"散户天团"）。
# ⚠️ 匹配口径：席位全称含"股份有限公司"，故用关键词而非前缀匹配（10/11 实测踩坑）：
# 实际席位形如"东方财富证券股份有限公司拉萨团结路第一证券营业部"、
# "东方财富证券股份有限公司拉萨金融城南环路证券营业部"（新网点会持续出现），统一按"拉萨"关键词匹配。
def is_retail_dept(name: str) -> bool:
    return "拉萨" in name or "山南香曲东路" in name


def em_get(report: str, filter_str: str, page_size: int = 500) -> list[dict]:
    rows: list[dict] = []
    page = 1
    while True:
        params = {"reportName": report, "columns": "ALL", "filter": filter_str,
                  "pageNumber": page, "pageSize": page_size,
                  "sortColumns": "BUY", "sortTypes": "-1", "source": "DataCenter"}
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


def out_path(date: str) -> Path:
    return OUT_DIR / f"{date[:4]}-{date[4:6]}-{date[6:]}.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now().strftime("%Y%m%d"))
    args = ap.parse_args()
    date = args.date
    iso = f"{date[:4]}-{date[4:6]}-{date[6:]}"

    from investment_engine.sentiment.board_members import get_stock_board_map
    stock2board = get_stock_board_map()
    print(f"成分映射 {len(stock2board)} 只", file=sys.stderr)

    rows = em_get("RPT_BILLBOARD_DAILYDETAILSBUY", f"(TRADE_DATE='{iso}')")
    print(f"营业部明细 {len(rows)} 条", file=sys.stderr)
    if not rows:
        print(f"WARN 无数据（{iso} 可能非交易日或数据未出）", file=sys.stderr)
        return 1

    # 聚合到板块
    boards: dict[str, dict] = {}
    for r in rows:
        code = r.get("SECURITY_CODE") or ""
        board = stock2board.get(code)
        if not board:
            continue
        b = boards.setdefault(board, {"retail_buy": 0.0, "total_buy": 0.0, "stocks": set()})
        buy = float(r.get("BUY") or 0)
        b["total_buy"] += buy
        name = r.get("OPERATEDEPT_NAME") or ""
        if is_retail_dept(name):
            b["retail_buy"] += buy
        b["stocks"].add(code)

    # 近 20 日上榜频次（读历史文件）
    hits: dict[str, int] = {}
    for i in range(1, 21):
        p = out_path((datetime.strptime(iso, "%Y-%m-%d") - timedelta(days=i)).strftime("%Y%m%d"))
        if p.exists():
            for bn in json.loads(p.read_text(encoding="utf-8")):
                hits[bn] = hits.get(bn, 0) + 1

    out = {}
    for bn, b in boards.items():
        out[bn] = {
            "retail_buy_ratio": round(b["retail_buy"] / b["total_buy"], 3) if b["total_buy"] else 0.0,
            "board_hits_20d": hits.get(bn, 0) + 1,  # 含今日
            "total_buy": round(b["total_buy"], 0),
            "stocks": sorted(b["stocks"]),
        }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path(date).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"落盘 {out_path(date)}: {len(out)} 个板块", file=sys.stderr)
    for bn, v in sorted(out.items(), key=lambda x: -x[1]["retail_buy_ratio"])[:5]:
        print(f"  {bn}: 散户占比 {v['retail_buy_ratio']:.0%} 买入 {v['total_buy'] / 1e8:.1f}亿", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
