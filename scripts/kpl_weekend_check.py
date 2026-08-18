#!/usr/bin/env python
"""KPL 周末可拉性一次性验证（C2 后段）：拉指定日（默认上一个周六）的资讯列表。

用法: set -a && source .env && set +a && .venv/bin/python scripts/kpl_weekend_check.py [YYYY-MM-DD]
退出码: 0=有数据；1=无数据或失败。下周末手动跑一次即可。
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from investment_engine.kpl import news
from investment_engine.kpl.client import KplClient


def main() -> int:
    if len(sys.argv) > 1:
        day = date.fromisoformat(sys.argv[1])
    else:  # 上一个周六（周六当天取上周六）
        today = date.today()
        day = today - timedelta(days=(today.weekday() - 5) % 7 or 7)
    try:
        items = news.fetch_list(KplClient.from_env(), day)
    except Exception as e:
        print(f"[kpl-weekend] 拉取失败({day}): {e}", file=sys.stderr)
        return 1
    print(f"[kpl-weekend] {day} 资讯 {len(items)} 条")
    for it in items[:3]:
        print(f"  - {it.get('Title', '')}")
    return 0 if items else 1


if __name__ == "__main__":
    sys.exit(main())
