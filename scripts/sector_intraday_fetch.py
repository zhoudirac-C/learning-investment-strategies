#!/usr/bin/env python
"""板块分时强度拉取入口（cron 工作日 15:40 前后调用，与 fund_flow 同窗口）。

TDX 880 板块指数 60min K线 → 全日/上午/下午涨跌幅 + 阵营拉升定性。
幂等：当日目标文件已存在则跳过，--force 覆盖重拉。
退出码：0 成功；1 拉取失败（无有效板块数据）。

手动: .venv/bin/python scripts/sector_intraday_fetch.py [--force]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from investment_engine import sector_intraday


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="板块分时强度拉取（TDX 880 板块指数 60min）")
    parser.add_argument("--out-root", default=str(sector_intraday.DATA_ROOT))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    out_root = Path(args.out_root)
    try:
        data = sector_intraday.compute_sector_intraday()
    except Exception as e:  # noqa: BLE001 - cron 脚本如实报错退出
        print(f"[sector-intraday] 拉取异常: {e}")
        return 1
    if data is None:
        print("[sector-intraday] 无有效板块数据（TDX 不可达/非交易日）")
        return 1

    target = out_root / f"{data['date'].replace('-', '')}.json"
    if target.exists() and not args.force:
        print(f"[sector-intraday] 已存在，跳过: {target}")
        return 0
    path = sector_intraday.save_sector_intraday(data, root=out_root)
    lead = data.get("pm_lead_camp")
    n = len(data.get("sectors", []))
    print(f"[sector-intraday] 落盘: {path}（板块 {n} 个，午后主导: {lead}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
