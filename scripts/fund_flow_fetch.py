#!/usr/bin/env python
"""板块资金流拉取入口（cron 工作日 15:40 前后调用，与 limit_pool 同窗口）。

akshare stock_fund_flow_industry / stock_fund_flow_concept 只返回最新快照，
无历史回溯：--date 仅影响落盘文件名与 date 字段，不改数据内容
（非交易时段跑得到的是最近交易日的快照）。
幂等：当日目标文件已存在则跳过，--force 覆盖重拉。
退出码：0 成功（含部分窗口失败，errors 已如实写入文件）；1 拉取失败。

手动: .venv/bin/python scripts/fund_flow_fetch.py [--date 20260817]
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from investment_engine import fund_flow


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="板块资金流拉取（akshare 行业/概念四窗口）")
    parser.add_argument("--date", default=date.today().strftime("%Y%m%d"),
                        help="YYYYMMDD（默认今日；仅影响文件名与 date 字段）")
    parser.add_argument("--out-root", default="infra/data/fund_flow")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    out_root = Path(args.out_root)
    target = out_root / f"{args.date}.json"
    if target.exists() and not args.force:
        print(f"[fund-flow] 已存在，跳过: {target}")
        return 0

    try:
        data = fund_flow.fetch_fund_flow()
    except Exception as e:
        print(f"[fund-flow] 拉取失败: {e}", file=sys.stderr)
        return 1
    data["date"] = f"{args.date[:4]}-{args.date[4:6]}-{args.date[6:]}"
    path = fund_flow.save_fund_flow(data, out_root)
    n_ind = sum(len(v) for v in data["industry"].values() if v)
    n_con = sum(len(v) for v in data["concept"].values() if v)
    tail = f"  errors={len(data['errors'])}" if data["errors"] else ""
    print(f"[fund-flow] 板块资金流 → {path}  行业={n_ind}条 概念={n_con}条{tail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
