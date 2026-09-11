#!/usr/bin/env python3
"""增量拉取板块成分股 K 线落库（供盲判方向识别 + 评分使用）。

背景：盲判方向识别已切到 TDX 概念板块（269 个），但评分需要成分股的
历史 K 线算 5 日超额。本地 kline_cache 只覆盖 stock_pool 的 ~200 只，
对 TDX 成分股覆盖率仅 4%。本脚本增量补齐。

数据源（2026-09-11 迁移）：
  TdxMarket 直连 → marketdata.router.get_kline 统一数据源层。
  根因：TDX 公网节点对 get_security_bars 按接口粒度封禁（CapMainKline
  全部 host 返回空，单只失败路径 ~23s），本脚本此前既未走统一层降级链、
  又无进程内熔断，2280 只积压 × 23s 必撞 cron 900s 超时（连败 3 次）。
  迁移后链路 = 腾讯(qfq 前复权) → 东财 → （显式排除 TDX：统一层的 TDX
  适配器同样被封，逐台重试每只多烧 ~23s 无意义；TDX 解封后可加回）。
  口径变化：TDX 为不复权 → 腾讯 qfq 前复权。对 5 日超额评分更优
  （消除除权跳空伪信号），每次整体覆盖写 90 天窗口，口径自迁移日起统一。

策略（避免一次性 5364 只全量拉取）：
  1. 只拉「盲判方向池」实际会用到的板块成分股（默认全部概念板块去重）
  2. 断点续拉：已拉过且最新日期 >= 动态阈值（10 天内）的跳过
  3. 软时限收尾：cron 执行器 900s 超时前安全退出，剩余下轮续拉
  4. 连续多只全链失败 → 判定网络级故障，中止本轮（不逐只空转）

用法:
  .venv/bin/python scripts/fetch_tdx_sector_klines.py [--limit N] [--no-deadline]
产物: 写入 infra/data/kline_cache.db（stocks_kline 表）
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from qing_investment.kline_cache import save_klines, init_db  # noqa: E402
from qing_investment.marketdata import get_kline  # noqa: E402
from qing_investment.marketdata.errors import MarketDataError  # noqa: E402

DAYS = 90  # 每只拉 90 根日 K（覆盖评分 horizon=5 的需求）
DELAY = 0.05  # 单只间隔兜底；主限速由统一层 ratelimit（腾讯 0.25s/次）负责
MAX_RETRIES = 2  # 降级链已内置多源重试，单只重试从 3 降到 2
RETRY_DELAY = 1.0  # 重试间隔基数（指数退避：1s, 2s）

# 统一层降级链显式排除 TDX：CapMainKline 被服务端按接口封禁（9/10 实测），
# 不排除则每只失败路径多烧 ~23s。TDX 解封后把 "tdx" 加回即可。
SOURCES = ["tencent", "eastmoney"]

SOFT_DEADLINE_S = 780  # cron 900s 超时前收尾（留 120s 给在途请求 + 退出）
ABORT_AFTER_CONSECUTIVE_FAILS = 20  # 连续 N 只全链失败 → 疑似网络级故障，中止


def _load_target_codes(sector_json: Path, db_path: Path, only_codes=None) -> list[str]:
    """目标股票码 = sector_members.json 全部成分股去重，排除本地已有最新数据的。"""
    import json
    import sqlite3

    if only_codes:
        codes = sorted(set(only_codes))
    else:
        d = json.loads(sector_json.read_text(encoding="utf-8"))
        codes = sorted({c for v in d.get("concept", {}).values() for c in v})

    # 已有数据且最新交易日足够新的跳过（断点续拉）
    conn = sqlite3.connect(str(db_path))
    existing = {}
    for code, max_date in conn.execute(
        "SELECT code, MAX(trade_date) FROM stocks_kline GROUP BY code"
    ).fetchall():
        existing[code.split(".")[0]] = max_date
    conn.close()

    todo = []
    skipped = 0
    # 断点续拉阈值：动态取「最近 N 个自然日内有数据」即视为最新。
    # 2026-08-27 修复：原先硬编码 "2026-08-01"（注释写最近10天但实现非动态），
    # 8 月过后 4582 只 8-13 停更的代码被永久误判为已最新 → 板块评分静默失明。
    from datetime import date, timedelta
    fresh_threshold = (date.today() - timedelta(days=10)).isoformat()
    for c in codes:
        md = existing.get(c)
        # 最新交易日在最近 10 天内 → 跳过
        if md and md >= fresh_threshold:
            skipped += 1
            continue
        todo.append(c)
    print(f"[tdx-klines] 目标 {len(codes)} 只，已最新 {skipped} 只，待拉 {len(todo)} 只")
    return todo


def _rows_from_bars(bars: list[dict]) -> list[dict]:
    """统一层统一 shape（bar_time）→ stocks_kline 行（date）。

    turnover/amplitude 不映射：统一层不提供，原 TDX 管线同样写 NULL
    （消费方 get_klines_range SELECT 含这两列，历史口径即为 NULL，不变）。
    pct_change 由窗口内相邻 close 自算（对齐原 TdxMarket._map_klines 行为，
    首根无前收盘为 NULL）。
    """
    rows: list[dict] = []
    prev_close: float | None = None
    for b in bars:
        close = b.get("close")
        pct = None
        if close is not None and prev_close:
            pct = round((close / prev_close - 1) * 100, 4)
        if close is not None:
            prev_close = close
        rows.append({
            "date": b.get("bar_time") or b.get("date"),
            "open": b.get("open"),
            "high": b.get("high"),
            "low": b.get("low"),
            "close": close,
            "volume": b.get("volume"),
            "pct_change": pct,
        })
    return rows


def _fetch_bars(code: str) -> tuple[list[dict] | None, str]:
    """统一层拉日线。返回 (rows, source)；失败返回 (None, 错误摘要)。"""
    last_err = ""
    for attempt in range(MAX_RETRIES):
        try:
            bars, source = get_kline(code, 101, DAYS, sources=SOURCES)
            if bars:
                return _rows_from_bars(bars), source
            last_err = "全链空结果"
        except MarketDataError as e:
            last_err = str(e)[:120]
        except Exception as e:  # noqa: BLE001 单只异常不拖垮批次
            last_err = f"{type(e).__name__}: {e}"[:120]
        if attempt < MAX_RETRIES - 1:
            time.sleep(RETRY_DELAY * (attempt + 1))
    return None, last_err


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="本次最多拉取只数（0=全部）")
    ap.add_argument("--only", nargs="*", default=None, help="只拉指定代码（空格分隔）")
    ap.add_argument("--sector-json", type=Path, default=None,
                    help="覆盖 sector_members.json 路径（测试用）")
    ap.add_argument("--db", type=Path, default=None,
                    help="覆盖 kline_cache.db 路径（测试用）")
    ap.add_argument("--no-deadline", action="store_true",
                    help="手动补跑用：不启用软时限，跑完为止")
    args = ap.parse_args(argv)

    repo = Path(__file__).resolve().parent.parent
    sector_json = args.sector_json or (repo / "config" / "stock_monitor" / "sector_members.json")
    db_path = args.db or (repo / "infra" / "data" / "kline_cache.db")

    init_db(db_path=db_path)
    codes = _load_target_codes(sector_json, db_path, args.only)
    if args.limit:
        codes = codes[: args.limit]

    # 2026-08-27 修复：0 待拉 = 幂等无事可做，返回 0（原先 ok=0 → 返回 1，
    # cron/watcher 把「全部已最新」误判为失败）
    if not codes:
        print("[tdx-klines] 无待拉代码（全部已最新），无事可做")
        return 0

    ok = fail = 0
    consecutive_fail = 0
    t0 = time.time()
    stopped_early = ""
    for i, code in enumerate(codes):
        # 软时限：cron 执行器 900s 硬杀之前安全收尾，剩余交给下轮断点续拉
        # （避免「数据写了一半 + cron 记失败」的双输局面）
        if not args.no_deadline and time.time() - t0 > SOFT_DEADLINE_S:
            stopped_early = f"达软时限 {SOFT_DEADLINE_S}s"
            break

        rows, last_err = _fetch_bars(code)

        if rows:
            save_klines(code, rows, db_path=db_path)
            ok += 1
            consecutive_fail = 0
        else:
            fail += 1
            consecutive_fail += 1
            if fail <= 5:
                print(f"  ❌ {code}: {last_err}（可能停牌/退市）")
            if consecutive_fail >= ABORT_AFTER_CONSECUTIVE_FAILS:
                stopped_early = f"连续 {consecutive_fail} 只全链失败，疑似网络级故障"
                break
        if (i + 1) % 100 == 0:
            el = time.time() - t0
            rate = el / (i + 1)
            remain = len(codes) - i - 1
            print(f"  [{i+1}/{len(codes)}] 成功{ok} 失败{fail} "
                  f"耗时{el:.0f}s 均速{rate:.2f}s/只 剩余约{remain*rate:.0f}s")
        time.sleep(DELAY)

    el = time.time() - t0
    if stopped_early:
        remain = len(codes) - ok - fail
        print(f"[tdx-klines] 提前收尾：{stopped_early}；成功 {ok} 失败 {fail} "
              f"剩余 {remain} 只下轮续拉，耗时 {el:.0f}s")
    else:
        print(f"[tdx-klines] 完成: 成功 {ok} 失败 {fail} / 共 {len(codes)}，耗时 {el:.0f}s")
    # 有成功即视为本轮有效（部分失败如停牌是常态）；全部失败才报错
    return 0 if ok > 0 else 1


if __name__ == "__main__":
    import os
    import sys
    # 显式 os._exit 强制退出：数据已 commit 落库，直接 _exit 安全。
    # 2026-08-27 修复：_exit 前必须 flush（os._exit 不清缓冲，管道/cron
    # 场景下 stdout 全空 → 静默失败假象）。
    # （2026-09-11 迁移 pytdx 后已无非 daemon 线程，保留 _exit 属防御性）
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
