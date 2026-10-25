#!/usr/bin/env python
"""毕业判分：滚动 8 周窗口对照主计划 10.4 毕业线，写 logs/graduation-<date>.md。

用法: .venv/bin/python scripts/graduation_check.py
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from investment_engine.shadow.graduation import run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="毕业判分（主计划 10.4 口径）")
    parser.add_argument("--pred-dir", default="evals/shadow/predictions")
    parser.add_argument("--weeks", type=int, default=8)
    parser.add_argument("--out-dir", default="logs")
    # 2026-10-25 判据 3：历史基准取自 claims 库 up 桶已结算证伪率
    parser.add_argument("--claims-dir", default="knowledge/claims",
                        help="claims 目录（判据 3 历史基准；传空字符串则跳过）")
    # 2026-10-20 新增：允许指定判定日，便于补跑历史窗口与测试注入固定日期
    parser.add_argument("--today", type=date.fromisoformat, default=None,
                        help="判定基准日 YYYY-MM-DD（默认今天）")
    args = parser.parse_args(argv)

    claims_dir = Path(args.claims_dir) if args.claims_dir else None
    path = run(Path(args.pred_dir), weeks=args.weeks, out_dir=Path(args.out_dir),
               today=args.today, claims_dir=claims_dir)
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("- **verdict"):
            print(line)
    print(f"[report] {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
