#!/usr/bin/env python
"""legacy 聚合 md claims → 标准 claim YAML 迁移器。

背景（2026-10-25）：knowledge/claims/ 下 3 个 2025-12~2026-05 的聚合 .md
文件（2025-12-2026-05-历史全量 / 2026-05-14-15-强分歧承接 /
2026-05-17-宏观再通胀与科技拥挤）共 36 条 qing- 前缀 claim，是青枫浦上Q
最早一层观点，但从未进 discover→Neo4j→Qdrant 管线（discover 只扫 *.yaml）。
本脚本把它们转换为标准 claims: 列表 YAML（补 up_id/up_name/school），
并把原 .md 移入 archive/legacy-md-claims/ 防 load_claims 双计。

转换后须跑全流程（docs/neo4j-relation-pipeline.md）：
  discover --all-missing → migrate_claims_to_neo4j → index_claims_to_qdrant

用法:
  .venv/bin/python scripts/migrate_md_claims_to_yaml.py --dry-run   # 只清点
  .venv/bin/python scripts/migrate_md_claims_to_yaml.py             # 转换+归档
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLAIMS_DIR = PROJECT_ROOT / "knowledge" / "claims"
ARCHIVE_DIR = PROJECT_ROOT / "archive" / "legacy-md-claims"

UP_ID = "1420210197"
UP_NAME = "青枫浦上Q"
SCHOOL = "qing"

_HEAD_RE = re.compile(r"^##\s+claim:\s*(?P<id>\S+)\s*$")
_FIELD_RE = re.compile(r"^-\s*(?P<key>[a-z_]+):\s*(?P<val>.*)$")
_LINK_RE = re.compile(r"^\s+-\s*(?P<key>[a-z_]+):\s*(?P<val>.*)$")

# 顶层标量字段（md 聚合格式的 claim 卡片字段全集）
_FIELDS = (
    "id", "source_path", "source_date", "source_type", "extracted",
    "claim_type", "subject", "timeframe", "statement", "evidence_quote",
    "interpretation", "confidence", "status",
)
_FIELD_KEYS = set(_FIELDS) | {"extracted_at"}


def _strip_backticks(val: str) -> str:
    val = val.strip()
    if len(val) >= 2 and val.startswith("`") and val.endswith("`"):
        val = val[1:-1]
    return val.strip()


def _parse_link_value(val: str) -> list:
    """`["a", "b"]` → list；空数组/解析失败返回 []。"""
    val = _strip_backticks(val)
    if not val or val == "[]":
        return []
    try:
        parsed = json.loads(val)
        return list(parsed) if isinstance(parsed, list) else []
    except (json.JSONDecodeError, ValueError):
        return []


def parse_md_blocks(text: str) -> list[dict]:
    """解析聚合 md 的 `## claim:` 块 → 字段 dict（含 links 子块）。"""
    blocks: list[dict] = []
    cur: dict | None = None
    in_links = False
    for line in text.splitlines():
        head = _HEAD_RE.match(line)
        if head:
            cur = {"id": head.group("id"), "links": {}}
            blocks.append(cur)
            in_links = False
            continue
        if cur is None:
            continue
        if line.startswith("## "):  # 下一个非 claim 标题，封块
            cur = None
            in_links = False
            continue
        m = _FIELD_RE.match(line)
        if m and not line.startswith((" ", "\t")):
            key, val = m.group("key"), m.group("val")
            if key == "links":
                in_links = True
                continue
            if key in _FIELD_KEYS and key != "id":
                cur[key] = _strip_backticks(val)
            in_links = False
            continue
        lm = _LINK_RE.match(line)
        if in_links and lm:
            cur["links"][lm.group("key")] = _parse_link_value(lm.group("val"))
    return [b for b in blocks if b.get("id")]


def md_to_claims(text: str) -> list[dict]:
    """md 文本 → 标准 claim dict 列表（补 UP 身份信息，空关系字段不写入）。"""
    claims = []
    for b in parse_md_blocks(text):
        claim = {k: v for k, v in b.items() if k not in ("links",)}
        claim["up_id"] = UP_ID
        claim["up_name"] = UP_NAME
        claim["school"] = SCHOOL
        # 与现行 YAML 保持一致：links 无内容时给空映射
        claim["links"] = {k: v for k, v in (b.get("links") or {}).items() if v}
        claims.append(claim)
    return claims


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="只清点不写入")
    args = parser.parse_args(argv)

    md_files = sorted(p for p in CLAIMS_DIR.glob("*.md")
                      if p.name.lower() not in ("readme.md", "index.md"))
    if not md_files:
        print("无遗留 md claim 文件")
        return 0

    total = 0
    for md in md_files:
        claims = md_to_claims(md.read_text(encoding="utf-8"))
        total += len(claims)
        out = md.with_suffix(".yaml")
        print(f"{md.name}: {len(claims)} 条 → {out.name}")
        if args.dry_run:
            continue
        out.write_text(
            yaml.safe_dump({"claims": claims}, allow_unicode=True,
                           sort_keys=False, width=4096),
            encoding="utf-8")
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        shutil.move(str(md), ARCHIVE_DIR / md.name)
    print(f"{'[dry-run] ' if args.dry_run else ''}共 {total} 条")
    if not args.dry_run:
        print(f"原 md 已移入 {ARCHIVE_DIR.relative_to(PROJECT_ROOT)}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
