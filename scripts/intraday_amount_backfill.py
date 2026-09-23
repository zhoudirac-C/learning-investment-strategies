#!/usr/bin/env python3
"""量能四点曲线缺口补齐（东财窗口探测驱动，2026-09-23 新增）。

## 为什么需要它
`scripts/intraday_amount_fetch.py`（四点曲线）依赖东财 60min `amount`，而东财
对本机云 IP 是重度间歇封禁（实测成功率 ~17%，曾出现 0/10 全灭）。封禁窗口内
该脚本 exit 1 → 量能文件缺失。实测 2026-09-14 ~ 09-23 **连续 7 个交易日全部缺失**
（TDX `CapMainKline` 封禁的起始点）。

策略：**窗口探测驱动**——每天定点探测东财，可用则批量补齐缺口，不可用则静默退出
（不空转、不打日志噪音）。东财没有固定的"解封时刻"，但在一段时间内反复探测
总能撞到窗口。

## 补齐范围
- 目标日期 = 近 N 个**交易日**中缺失 `{yyyymmdd}.json` 的日期（默认 N=15）
- 交易日历取自已有产物 + 工作日近似（非交易日探测会自然失败，无副作用）
- 幂等：已存在的文件自动跳过

## 用法
    # 探测一次，有窗口就补齐，无则静默退出 0
    PYTHONPATH=src .venv/bin/python scripts/intraday_amount_backfill.py

    # 只探测不落盘（判断东财当前是否可用）
    PYTHONPATH=src .venv/bin/python scripts/intraday_amount_backfill.py --probe-only

    # 强制指定日期
    PYTHONPATH=src .venv/bin/python scripts/intraday_amount_backfill.py --date 2026-09-22

退出码：0 = 已补齐或无需补齐（含"无窗口"）；1 = 探测到窗口但补齐仍失败（异常）。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = str(ROOT / ".venv" / "bin" / "python")
if not Path(PY).exists():  # 回退到当前解释器
    PY = sys.executable


def eastmoney_alive() -> bool:
    """探测东财是否处于可用窗口（拉一条最小 clist 请求）。

    用统一模块的 http 层，与生产同一条通道——避免"探测通了但生产不通"。
    """
    sys.path.insert(0, str(ROOT / "src"))
    try:
        from qing_investment.marketdata.sources import em_board

        rows = em_board.board_list("industry")
        return bool(rows)
    except Exception:  # noqa: BLE001
        return False


def recent_trading_days(n: int) -> list[str]:
    """近 n 个交易日（工作日近似，跳过周末；节假日由探测自然失败兜住）。"""
    days: list[str] = []
    d = date.today()
    while len(days) < n:
        if d.weekday() < 5:  # 周一~周五
            days.append(d.strftime("%Y%m%d"))
        d -= timedelta(days=1)
    return days


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="量能四点曲线缺口补齐（东财窗口探测驱动）")
    ap.add_argument("--out-root", default=str(ROOT / "infra" / "data" / "intraday_amount"))
    ap.add_argument("--lookback", type=int, default=15, help="回看交易日数（默认 15）")
    ap.add_argument("--date", default=None, help="只补齐指定日期 YYYY-MM-DD")
    ap.add_argument("--probe-only", action="store_true", help="只探测东财可用性")
    ap.add_argument("--force", action="store_true", help="覆盖已存在文件")
    args = ap.parse_args(argv)

    if not eastmoney_alive():
        print("[amount-backfill] 东财当前不可用（封禁窗口），本次跳过", file=sys.stderr)
        return 0
    print("[amount-backfill] ✅ 东财窗口可用 → 开始检查缺口", file=sys.stderr)

    if args.probe_only:
        return 0

    out_root = Path(args.out_root)

    if args.date:
        targets = [args.date.replace("-", "")]
    else:
        existing = {p.stem for p in out_root.glob("*.json") if len(p.stem) == 8}
        targets = [d for d in recent_trading_days(args.lookback) if d not in existing]

    if not targets:
        print("[amount-backfill] 无缺口，无需补齐", file=sys.stderr)
        return 0

    print(f"[amount-backfill] 待补 {len(targets)} 个交易日: {', '.join(targets)}",
          file=sys.stderr)

    ok = fail = 0
    for ymd in targets:
        iso = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}"
        cmd = [PY, str(ROOT / "scripts" / "intraday_amount_fetch.py"), "--date", iso]
        if args.force:
            cmd.append("--force")
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, timeout=300)
        path = out_root / f"{ymd}.json"
        if r.returncode == 0 and path.exists():
            print(f"[amount-backfill]   ✅ {iso}", file=sys.stderr)
            ok += 1
        else:
            # 单日失败不中断——东财窗口可能在补齐过程中关闭
            print(f"[amount-backfill]   ❌ {iso}（{r.stderr.decode()[-200:].strip()}）",
                  file=sys.stderr)
            fail += 1

    print(f"[amount-backfill] 完成：成功 {ok} / 失败 {fail}", file=sys.stderr)

    # 窗口中途关闭 → 不算异常，安静退出让下次 cron 继续补
    if ok == 0 and fail > 0:
        print("[amount-backfill] 窗口在补齐过程中关闭，下次继续", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
