#!/usr/bin/env python3
"""从 TDX 拉取板块成分股并落盘（概念 + 行业），供盲判/agent 方向识别使用。

用法:
    PYTHONPATH=src .venv/bin/python scripts/fetch_tdx_sector_members.py

产物:
    config/stock_monitor/sector_members.json  →  {_built_at, _source, concept: {板块名:[裸码,...]}, industry: {...}}

数据源: 通达信 block_gn.dat（概念板块，269个）、tdxhy.cfg（个股→行业分类）。
修复了 pytdx get_and_parse_block_info 的下载拼接 bug（见 tdx_market.market.get_block_members）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from qing_investment.tdx_market import TdxMarket  # noqa: E402


def main() -> int:
    mkt = TdxMarket()
    concept = mkt.get_block_members("block_gn.dat")
    if not concept:
        print("[tdx-sector] 概念板块拉取为空", file=sys.stderr)
        return 1

    out = {
        "_built_at": __import__("time").time(),
        "_source": "tdx_block_gn",
        "concept": concept,
        "industry": {},  # tdxhy.cfg 行业分类后续补充（非方向识别核心）
    }

    out_path = Path("config/stock_monitor/sector_members.json")
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    total = sum(len(v) for v in concept.values())
    print(f"[tdx-sector] 概念板块 {len(concept)} 个 / 成分股映射 {total} 条 → {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
