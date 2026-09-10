#!/usr/bin/env python3
"""tdx_market 自测脚本：实际连通通达信服务器验证各接口可用性。

运行::

    python scripts/tdx_market_selftest.py
"""
from __future__ import annotations

import logging
import os
import sys
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from qing_investment.tdx_market import TdxMarket  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

OK = 0
FAIL = 0
EMPTY = 0


def _nonempty(result) -> bool:
    """判定「真实取到数据」。

    ⚠️ 2026-09-10 教训：不能只看「是否抛异常」。
    TDX 服务端按接口粒度封禁时，`get_security_bars` 全 host 返回空，
    空列表 `[]` 不抛异常 —— 旧版 `run()` 会把它记成 OK，
    造成 selftest 全绿但实际 0 台 host 能取 K线的假象。
    正确标准：返回**非空**才算 OK。
    """
    if result is None:
        return False
    if isinstance(result, (list, dict, str, tuple, set)):
        return len(result) > 0
    return True


def run(name, fn, expect_nonempty: bool = True):
    """执行一项自测并统计。

    Args:
        expect_nonempty: True 时要求返回非空才算 OK（默认，适用于所有取数接口）。
            仅当「返回空本身是合法结果」时才传 False。
    """
    global OK, FAIL, EMPTY
    try:
        result = fn()
    except Exception as e:  # noqa: BLE001
        FAIL += 1
        print(f"\n[FAIL] {name}: {e!r}")
        traceback.print_exc(limit=2)
        return None

    if expect_nonempty and not _nonempty(result):
        EMPTY += 1
        print(f"\n[EMPTY] {name}: 接口连通但返回空 —— 疑似服务端按接口粒度封禁")
        return result

    OK += 1
    print(f"\n[OK]   {name}")
    return result


def main() -> None:
    mkt = TdxMarket()

    # 1. 批量实时行情
    quotes = run("实时行情(茅台/平安/宁德)", lambda: mkt.get_quotes(["600519", "000001", "300750"]))
    if quotes:
        for q in quotes:
            print(f"   {q.get('code'):>6} {str(q.get('name')):<8} "
                  f"price={q.get('price')} prev={q.get('prev_close')} "
                  f"pct={q.get('pct_change')}% src={q.get('source')}")

    # 2. 单只行情
    q = run("单只行情 600519", lambda: mkt.get_quote("600519"))
    if q:
        print(f"   keys={list(q.keys())}")

    # 3. 日K线
    kl = run("日K线 600519 x5", lambda: mkt.get_kline("600519", count=5))
    if kl:
        for k in kl:
            print(f"   {k.get('date')} O={k.get('open')} C={k.get('close')} "
                  f"H={k.get('high')} L={k.get('low')} V={k.get('volume')}")

    # 4. 指数K线（上证指数）
    ik = run("指数K线 上证999999 x5", lambda: mkt.get_index_kline("999999", count=5))
    if ik:
        for k in ik:
            print(f"   {k.get('date')} C={k.get('close')} V={k.get('volume')}")

    # 5. 分时
    intr = run("分时 600519", lambda: mkt.get_intraday("600519"))
    if intr is not None:
        print(f"   分时点数={len(intr)} 首点={intr[0] if intr else None}")

    # 6. 除权除息
    xdxr = run("除权除息 600519", lambda: mkt.get_xdxr("600519"))
    if xdxr is not None:
        print(f"   xdxr 条数={len(xdxr)}")
        if xdxr:
            print(f"   首条 keys={list(xdxr[0].keys()) if isinstance(xdxr[0], dict) else type(xdxr[0])}")

    # 7. 证券列表（沪市前 5）
    sl = run("证券列表 沪市前5", lambda: mkt.get_security_list(1, 0, 5))
    if sl:
        print(f"   条数={len(sl)}")
        if sl:
            first = sl[0]
            print(f"   首条 keys={list(first.keys()) if isinstance(first, dict) else type(first)}")

    # 8. 板块文件
    bl = run("板块 block_zs.dat", lambda: mkt.get_block_info("block_zs.dat"))
    if bl is not None:
        print(f"   板块条数={len(bl)}")

    print(f"\n========== 汇总: OK={OK}  EMPTY={EMPTY}  FAIL={FAIL} ==========")
    if EMPTY:
        print(f"⚠️  {EMPTY} 项接口连通但返回空 —— TDX 常规 K线/行情接口疑似被封禁，"
              f"请勿据此认为数据正常（2026-09-10 教训）")
    sys.exit(0 if (FAIL == 0 and EMPTY == 0) else 1)


if __name__ == "__main__":
    main()
