#!/usr/bin/env python
"""补拉指数日 K 入 K 线缓存（M1 盲测真值/基准依赖）。

腾讯 _normalize_code 按"6 开头判 sh"会把指数 000300 误判为 sz000300，
这里内联构造 sh 前缀请求绕开；落库用 IDX 别名防与个股裸码混淆。

用法: python scripts/fetch_index_klines.py
"""
from __future__ import annotations

import json
import sys
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from qing_investment.kline_cache import init_db, save_klines

INDEXES = {"IDX000300": "sh000300", "IDX000001": "sh000001"}  # 沪深300 / 上证指数
DAYS = 120


def fetch_index_tencent(full_code: str, days: int = DAYS) -> list[dict]:
    end = datetime.now()
    start = end - timedelta(days=days + 20)
    url = (
        "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param="
        f"{full_code},day,{start:%Y-%m-%d},{end:%Y-%m-%d},{days + 20},qfq"
    )
    with urllib.request.urlopen(url, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    stock_data = data.get("data", {}).get(full_code, {})
    klines = stock_data.get("qfqday", []) or stock_data.get("day", [])
    result = []
    prev_close = None
    for k in klines:
        try:
            close = float(k[2])
            row = {
                "code": full_code, "date": k[0],
                "open": float(k[1]), "close": close,
                "high": float(k[3]), "low": float(k[4]),
                "volume": float(k[5]) if len(k) > 5 else 0.0,
                "turnover": None, "amplitude": None,
                "pct_change": (close / prev_close - 1.0) * 100 if prev_close else None,
            }
            result.append(row)
            prev_close = close
        except (IndexError, TypeError, ValueError):
            continue
    return result


def main() -> int:
    init_db()
    for alias, full_code in INDEXES.items():
        kl = fetch_index_tencent(full_code)
        if not kl:
            print(f"[FAIL] {alias} ({full_code}) 未取到数据")
            return 1
        save_klines(alias, kl)
        last = kl[-1]
        print(f"[OK] {alias}: {len(kl)} 根, {kl[0]['date']} ~ {last['date']}, 最后收盘 {last['close']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
