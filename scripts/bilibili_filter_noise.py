#!/usr/bin/env python3
"""B站动态 claim 提取前置过滤：识别并排除与投资无关的动态（抽奖/福利/生活）。

用法:
    # 扫描候选（只报告，不修改）
    python3 scripts/bilibili_filter_noise.py --scan

    # 列出可送入 claim 提取管线的白名单（排除 config/bilibili_exclude.yaml 中的）
    python3 scripts/bilibili_filter_noise.py --list --up 卢本圆复盘

    # 列出所有 UP 的可提取文件
    python3 scripts/bilibili_filter_noise.py --list

设计:
    - 落盘文件全部保留（原文存档），本脚本只决定"哪些进 claim 提取"
    - 排除依据 = config/bilibili_exclude.yaml 的 exclude 清单（人工确认）
    - --scan 用关键词自动找候选，但标题含词≠排除（需人工核对正文）
"""

from __future__ import annotations

import argparse
import glob
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG = REPO_ROOT / "config" / "bilibili_exclude.yaml"
RAW_DIR = REPO_ROOT / "sources" / "original" / "bilibili"


def load_exclude() -> tuple[set[str], list[str]]:
    """返回 (排除的 dynamic_id 集合, 关键词列表)。"""
    if not CONFIG.exists():
        return set(), []
    try:
        import yaml
        d = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        print(f"WARN: 解析 {CONFIG} 失败: {exc}", file=sys.stderr)
        return set(), []
    ids = {str(e.get("dynamic_id")) for e in (d.get("exclude") or []) if e.get("dynamic_id")}
    kws = list(d.get("auto_detect_keywords") or [])
    return ids, kws


def parse_meta(path: Path) -> dict:
    """解析 frontmatter + 正文。"""
    c = path.read_text(encoding="utf-8")
    meta = {"path": path, "dynamic_id": "", "up_uid": "", "up_name": "",
            "dynamic_type": "", "pub_time": "", "body": "", "comment": ""}
    m = re.search(r"^---\n(.*?)\n---", c, re.S | re.M)
    fm = m.group(1) if m else ""
    for key in ("dynamic_id", "up_uid", "up_name", "dynamic_type", "pub_time"):
        mm = re.search(rf'{key}: "(.*?)"', fm)
        if mm:
            meta[key] = mm.group(1)

    # 正文（原文段），排除原始 API JSON
    head = c.split("<!--")[0]
    ts = head.find("## 原文")
    if ts >= 0:
        rest = head[ts + 5:]
        for marker in ("## 图片 OCR", "## 图片", "## 视频封面", "## 互动数据", "## 置顶评论"):
            idx = rest.find(marker)
            if idx > 0:
                rest = rest[:idx]
        meta["body"] = re.sub(r"\s+", " ", rest).strip()
    # 置顶评论
    cs = head.find("## 置顶评论")
    if cs >= 0:
        meta["comment"] = re.sub(r"\s+", " ", head[cs:])[:300]
    return meta


def scan(records: list[dict], kws: list[str]) -> None:
    """扫描噪音候选（关键词命中）。"""
    print("=== 噪音候选扫描（需人工核对正文，标题含词≠排除）===\n")
    hits = 0
    for r in records:
        text = f'{r["body"]} {r["comment"]}'
        matched = [k for k in kws if k in text]
        if matched:
            hits += 1
            print(f'[{r["up_name"]}] {r["pub_time"]}  {r["path"].name[:50]}')
            print(f'   命中={matched}')
            print(f'   正文={r["body"][:120]}')
            print()
    print(f"合计 {hits} 条候选。确认与投资无关后，把 dynamic_id 加入 {CONFIG.name} 的 exclude 清单。")


def main() -> int:
    ap = argparse.ArgumentParser(description="B站动态 claim 提取前置过滤")
    ap.add_argument("--scan", action="store_true", help="扫描噪音候选")
    ap.add_argument("--list", action="store_true", help="列出可提取的白名单")
    ap.add_argument("--up", help="只看指定 UP（按 up_name 匹配）")
    args = ap.parse_args()

    excluded, kws = load_exclude()
    files = sorted(glob.glob(str(RAW_DIR / "*.md")))
    records = [parse_meta(Path(f)) for f in files]
    records = [r for r in records if r["dynamic_id"]]
    if args.up:
        records = [r for r in records if r["up_name"] == args.up]

    if args.scan:
        scan(records, kws)
        return 0

    if args.list:
        keep = [r for r in records if r["dynamic_id"] not in excluded]
        dropped = [r for r in records if r["dynamic_id"] in excluded]
        print(f"可提取: {len(keep)} 条 | 已排除: {len(dropped)} 条\n")
        if dropped:
            print("已排除（不提取）:")
            for r in dropped:
                print(f'  ✗ [{r["up_name"]}] {r["pub_time"]}  {r["path"].name[:45]}')
            print()
        print("可提取清单:")
        for r in keep:
            print(f'  ✓ [{r["up_name"]}] {r["pub_time"]}  {r["path"].name[:45]}')
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
