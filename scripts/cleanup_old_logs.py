#!/usr/bin/env python3
"""
清理指定日志目录下超过 N 天的旧日志文件。

Usage:
    python3 scripts/cleanup_old_logs.py
    python3 scripts/cleanup_old_logs.py --days 15 --dirs /path/one /path/two
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


DEFAULT_DAYS = 15
DEFAULT_LOG_DIRS = [
    "/home/ubuntu/learning-investment-strategies/logs",
    "/home/ubuntu/.kimi-code-im-bot/logs",
    "/home/ubuntu/.hermes/logs",
]
LOG_SUFFIXES = {".log"}


def _default_log_dirs() -> list[Path]:
    """返回存在的默认日志目录。"""
    dirs: list[Path] = []
    for d in DEFAULT_LOG_DIRS:
        p = Path(d)
        if p.exists() and p.is_dir():
            dirs.append(p)
    return dirs


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="清理超过 N 天的日志文件")
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_DAYS,
        help=f"超过多少天的日志会被删除 (default: {DEFAULT_DAYS})",
    )
    parser.add_argument(
        "--dirs",
        nargs="+",
        default=None,
        help="日志目录列表（默认使用项目常见日志目录）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印将要删除的文件，不实际删除",
    )
    parser.add_argument(
        "--suffixes",
        nargs="+",
        default=None,
        help=f"要清理的文件后缀 (default: {LOG_SUFFIXES})",
    )
    return parser.parse_args()


def cleanup_old_logs(
    dirs: list[Path],
    days: int,
    suffixes: set[str],
    dry_run: bool = False,
) -> tuple[list[Path], list[Path]]:
    """删除指定目录下修改时间超过 days 天的、匹配后缀的文件。

    返回 (deleted_or_would_delete, skipped) 元组。
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    to_delete: list[Path] = []
    skipped: list[Path] = []

    for directory in dirs:
        if not directory.exists():
            print(f"[cleanup] 目录不存在，跳过: {directory}", file=sys.stderr)
            continue
        for entry in directory.iterdir():
            if not entry.is_file():
                continue
            if entry.suffix.lower() not in suffixes:
                continue
            try:
                mtime = datetime.fromtimestamp(entry.stat().st_mtime, tz=timezone.utc)
            except OSError as e:
                print(f"[cleanup] 无法读取 {entry}: {e}", file=sys.stderr)
                skipped.append(entry)
                continue
            if mtime < cutoff:
                to_delete.append(entry)

    for path in to_delete:
        try:
            if dry_run:
                print(f"[cleanup] [DRY-RUN] 将删除: {path} (mtime={path.stat().st_mtime})")
            else:
                path.unlink()
                print(f"[cleanup] 已删除: {path}")
        except OSError as e:
            print(f"[cleanup] 删除失败 {path}: {e}", file=sys.stderr)
            skipped.append(path)

    return to_delete, skipped


def main() -> int:
    args = _parse_args()
    dirs = [Path(d) for d in args.dirs] if args.dirs else _default_log_dirs()
    suffixes = {s.lower() if s.startswith(".") else f".{s.lower()}" for s in (args.suffixes or LOG_SUFFIXES)}

    if not dirs:
        print("[cleanup] 没有可用的日志目录", file=sys.stderr)
        return 0

    print(
        f"[cleanup] 开始清理，目录={', '.join(str(d) for d in dirs)}，"
        f"超过 {args.days} 天，后缀={suffixes}"
    )
    to_delete, skipped = cleanup_old_logs(
        dirs=dirs,
        days=args.days,
        suffixes=suffixes,
        dry_run=args.dry_run,
    )
    action = "将删除" if args.dry_run else "已删除"
    print(
        f"[cleanup] 完成: {action} {len(to_delete)} 个文件，"
        f"跳过/失败 {len(skipped)} 个文件"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
