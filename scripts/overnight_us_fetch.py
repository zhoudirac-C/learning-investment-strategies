#!/usr/bin/env python
"""隔夜外盘映射股拉取入口（cron 工作日 08:20 调用）。

幂等：当日目标文件已存在则跳过，--force 覆盖重拉。
退出码：0 成功（含部分失败，note 如实标注）；1 拉取失败。

手动: .venv/bin/python scripts/overnight_us_fetch.py [--date 2026-08-11]
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from investment_engine import overnight_us


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="隔夜外盘映射股拉取")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--out-root", default="infra/data/overnight_us")
    parser.add_argument("--config", default=None, help="us_map.yaml 路径（默认 config/stock_monitor/us_map.yaml）")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    target = Path(args.out_root) / f"{args.date}.json"
    if target.exists() and not args.force:
        print(f"[us] 已存在，跳过: {target}")
        return 0
    try:
        data = overnight_us.fetch_overnight(
            Path(args.config) if args.config else None)
    except Exception as e:
        print(f"[us] 拉取失败: {e}", file=sys.stderr)
        return 1
    path = overnight_us.save_overnight(data, Path(args.out_root), args.date)
    total = sum(len(t["stocks"]) for t in data["themes"])
    ok = sum(1 for t in data["themes"] for s in t["stocks"] if "error" not in s)
    tail = f"（{data['note']}）" if data.get("errors") else ""
    print(f"[us] 外盘映射 → {path}  {ok}/{total} 只{tail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
