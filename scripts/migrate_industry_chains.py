#!/usr/bin/env python
"""把 docs/标的深度研究 的存量报告迁移为产业链知识库（v2.1 M0）。

用法: python scripts/migrate_industry_chains.py [--dry-run]
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from investment_engine.industry_chain.migrate import parse_research_md
from investment_engine.industry_chain.store import default_base_dir, save_chain

RESEARCH_DIR = Path(__file__).resolve().parent.parent / "docs" / "标的深度研究"

# (chain_id, name, 源文件名, last_verified)
SOURCES = [
    ("changxin-dram", "长鑫存储产业链", "方向一：长鑫存储产业链全景梳理-20260518.md", "2026-05-18"),
    ("domestic-compute", "国产算力产业链", "方向二：国产算力产业链与Token经济学深度梳理-20260518.md", "2026-05-18"),
    ("ai-infra-energy", "AI基础设施与能源转型产业链", "方向三：AI基础设施与能源转型产业链梳理-20260518.md", "2026-05-18"),
]


def main(argv: list[str] | None = None) -> int:
    dry_run = "--dry-run" in (argv or sys.argv[1:])
    base = default_base_dir()
    for chain_id, name, filename, verified in SOURCES:
        src = RESEARCH_DIR / filename
        text = src.read_text(encoding="utf-8")
        chain = parse_research_md(text, chain_id=chain_id, name=name, verified=verified)
        n_seg, n_map = len(chain["segments"]), len(chain["mappings"])
        print(f"[{chain_id}] segments={n_seg} mappings={n_map} thesis={chain['thesis'][:40]}...")
        if n_map == 0:
            print(f"  !! 警告: {filename} 未解析到任何标的，检查解析规则")
            continue
        if dry_run:
            continue
        save_chain(chain, base_dir=base, expect_id=chain_id)
        shutil.copy2(src, base / chain_id / "research.md")
        print(f"  -> 已写入 {base / chain_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
