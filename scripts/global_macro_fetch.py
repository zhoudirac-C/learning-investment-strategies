#!/usr/bin/env python
"""全球宏观快照拉取入口（cron 工作日 09:10 盘前 + 16:35 盘后 --force 刷新补亚太收盘）。

Yahoo v8 chart 经 sakura 代理拉取：美股三指数/费半/存储链/亚太股指/美债收益率/
美元指数最近完整 session 收盘（as-of 规则：收盘时刻 ≤ 当日 22:00 北京）。
幂等：当日目标文件已存在则跳过，--force 覆盖重拉。
退出码：0 成功（含部分品种失败，errors 如实标注）；1 全部拉取失败。

手动: .venv/bin/python scripts/global_macro_fetch.py [--date 20260819] [--force]
历史日重算用于回放验收，同一 as-of 规则防泄漏（不混入未来 session）。
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from investment_engine import global_macro


def _parse_day(s: str) -> str:
    s = s.strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="全球宏观快照拉取（Yahoo v8 经代理）")
    parser.add_argument("--date", default=None,
                        help="A股交易日 YYYYMMDD/YYYY-MM-DD（默认今日北京日期）")
    parser.add_argument("--out-root", default=str(global_macro.DATA_ROOT))
    parser.add_argument("--proxy", default=global_macro.DEFAULT_PROXY,
                        help="代理地址（默认 sakura mihomo 127.0.0.1:7890，GLOBAL_MACRO_PROXY 可覆盖）")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    day = _parse_day(args.date) if args.date else datetime.now(
        timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    out_root = Path(args.out_root)
    target = out_root / f"{day.replace('-', '')}.json"
    if target.exists() and not args.force:
        print(f"[global-macro] 已存在，跳过: {target}")
        return 0
    try:
        data = global_macro.compute_global_macro(day, proxy=args.proxy)
    except Exception as e:  # noqa: BLE001 - cron 脚本如实报错退出
        print(f"[global-macro] 拉取异常: {e}", file=sys.stderr)
        return 1
    if data is None:
        print("[global-macro] 全部品种拉取失败（代理不可达/接口异常）", file=sys.stderr)
        return 1
    path = global_macro.save_global_macro(data, root=out_root)
    n = sum(len(v) for k, v in data.items()
            if isinstance(v, dict) and k not in ("errors",))
    tail = f"（{len(data['errors'])} 品种失败: {';'.join(data['errors'])}）" \
        if data.get("errors") else ""
    print(f"[global-macro] 落盘: {path}（品种 {n} 个）{tail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
