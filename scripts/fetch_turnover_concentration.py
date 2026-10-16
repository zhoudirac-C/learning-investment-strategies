#!/usr/bin/env python3
"""拉取全A成交额集中度快照（东财 push2 clist，收盘后跑）。

提案：framework/proposals/2026-10-13-pack-enhancement-turnover-concentration.md
口径：全A按成交额降序 top5% 占比 = UP 004-f「成交额前5%个股集中度」复算。

用法：
    .venv/bin/python scripts/fetch_turnover_concentration.py [--date 2026-10-13]

产物：infra/data/turnover_concentration/YYYY-MM-DD.json
幂等：同日文件已存在则跳过（--force 覆盖）。
注意：必须在收盘后跑（f6 为当日累计成交额，盘中跑会落半截数据）。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from investment_engine.shadow.concentration import compute_concentration  # noqa: E402

OUT_DIR = Path(__file__).resolve().parents[1] / "infra" / "data" / "turnover_concentration"
URL = ("https://push2.eastmoney.com/api/qt/clist/get?pn={pn}&pz=100&po=1&np=1"
       "&fltt=2&invt=2&fid=f6&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
       "&fields=f12,f6")
# fs 口径：沪深主板+创业板+科创板（m:0 t:6/80 深，m:1 t:2/23 沪）；不含北交所(m:0 t:81+)
PAGE_SLEEP = 0.4

# 分页拉取重试：东财 clist 在 56 页连续拉取中途偶发 RemoteDisconnected，
# 2026-10-14 / 10-15 因单页断连导致整体失败（详见 backfill_turnover_concentration.py 背景）。
MAX_RETRIES = 4          # 单页最多尝试次数（含首次）
RETRY_BACKOFF = 1.5      # 指数退避基数（秒）：1.5, 2.25, 3.375 ...


def _fetch_page(pn: int) -> dict:
    """拉单页 clist，带指数退避重试。失败抛最后一次异常。"""
    import requests
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.get(URL.format(pn=pn), timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception as exc:  # RemoteDisconnected / Timeout / HTTPError 等
            last_exc = exc
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF ** (attempt + 1)
                print(f"WARN: 第 {pn} 页请求失败（{type(exc).__name__}: {exc}），"
                      f"{wait:.1f}s 后重试（{attempt + 2}/{MAX_RETRIES}）", file=sys.stderr)
                time.sleep(wait)
    assert last_exc is not None
    raise last_exc


def fetch_all() -> list[dict]:
    rows: list[dict] = []
    pn, total = 1, None
    while True:
        payload = _fetch_page(pn)
        data = payload.get("data") or {}
        if total is None:
            total = data.get("total", 0)
        page = data.get("diff") or []
        if not page:
            break
        rows.extend(page)
        if len(rows) >= total:
            break
        pn += 1
        time.sleep(PAGE_SLEEP)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{args.date}.json"
    if out.exists() and not args.force:
        print(f"已存在，跳过: {out}")
        return 0

    rows = fetch_all()
    result = compute_concentration(rows, top_pct=0.05)
    if result is None:
        print("ERROR: 无有效成交额数据", file=sys.stderr)
        return 1
    if result["n_stocks"] < 4000:
        print(f"ERROR: 覆盖异常 n={result['n_stocks']}（预期 5300+），拒绝落盘", file=sys.stderr)
        return 1

    payload = {"date": args.date, **result}
    out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(f"✅ {args.date}: 集中度 {result['concentration_pct']}% "
          f"(top{result['top_n']}/{result['n_stocks']}, 全市场 {result['total_amount_yi']}亿)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
