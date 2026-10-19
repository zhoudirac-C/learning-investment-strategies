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


# ---------------------------------------------------------------------------
# 新浪 fallback（2026-10-19 新增）
# 背景：10-17 起东财 push2/push2his/push2delay/datacenter 对本机 IP 应用层封禁
# （TCP/TLS 握手正常，应用层 Empty reply），脚本重试无法恢复。
# 备用链路：新浪 Market_Center.getHQNodeData，node=hs_a，按 amount 降序分页。
# 口径差异：新浪 hs_a 含北交所（东财 clist fs 不含），n 约多 350 只；
# compute_concentration 用 top_pct 比例截取，头部构成一致，集中度偏差 <1.5pct。
# ---------------------------------------------------------------------------

SINA_URL = ("https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            "Market_Center.getHQNodeData")
SINA_COUNT_URL = ("https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
                  "Market_Center.getHQNodeStockCount")
SINA_PAGE_SLEEP = 1.5   # 新浪接口频率限制：连续请求间隔 >=1.5s，否则 3-5 分钟 IP 限流
SINA_MAX_RETRIES = 3


def _sina_headers() -> dict:
    return {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"}


def fetch_all_sina() -> list[dict]:
    """新浪 hs_a 按成交额降序全量拉取，转换为东财 clist 行格式 [{f12,f6}]。"""
    import requests
    sess = requests.Session()
    sess.headers.update(_sina_headers())

    r = sess.get(SINA_COUNT_URL, params={"node": "hs_a"}, timeout=10)
    total = int(r.json().strip('"'))
    expected_pages = (total + 99) // 100

    rows: list[dict] = []
    for pn in range(1, expected_pages + 1):
        last_exc: Exception | None = None
        for attempt in range(SINA_MAX_RETRIES):
            try:
                resp = sess.get(SINA_URL, params={
                    "page": pn, "num": 100, "sort": "amount", "asc": 0, "node": "hs_a",
                }, timeout=10)
                page = resp.json() if resp.text.strip() else []
                break
            except Exception as exc:
                last_exc = exc
                if attempt < SINA_MAX_RETRIES - 1:
                    wait = 3 * (attempt + 1)
                    print(f"WARN: 新浪第 {pn} 页失败（{type(exc).__name__}），"
                          f"{wait}s 后重试（{attempt + 2}/{SINA_MAX_RETRIES}）", file=sys.stderr)
                    time.sleep(wait)
        else:
            raise RuntimeError(f"新浪分页第 {pn} 页连续 {SINA_MAX_RETRIES} 次失败") from last_exc
        if not page:
            break
        for item in page:
            rows.append({"f12": str(item["code"]), "f6": float(item["amount"])})
        time.sleep(SINA_PAGE_SLEEP)

    if len(rows) < total * 0.98:
        raise RuntimeError(f"新浪覆盖异常：拉到 {len(rows)} / 预期 {total}")
    return rows


def fetch_all_with_fallback() -> tuple[list[dict], str]:
    """东财优先，失败自动切新浪。返回 (rows, source)。"""
    try:
        return fetch_all(), "eastmoney_clist"
    except Exception as exc:
        print(f"WARN: 东财 clist 失败（{type(exc).__name__}: {exc}），切换新浪 hs_a fallback",
              file=sys.stderr)
    return fetch_all_sina(), "sina_hs_a_rank"


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

    rows, source = fetch_all_with_fallback()
    result = compute_concentration(rows, top_pct=0.05)
    if result is None:
        print("ERROR: 无有效成交额数据", file=sys.stderr)
        return 1
    if result["n_stocks"] < 4000:
        print(f"ERROR: 覆盖异常 n={result['n_stocks']}（预期 5300+），拒绝落盘", file=sys.stderr)
        return 1

    payload = {"date": args.date, "source": source, **result}
    out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(f"✅ {args.date}: 集中度 {result['concentration_pct']}% "
          f"(top{result['top_n']}/{result['n_stocks']}, 全市场 {result['total_amount_yi']}亿)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
