#!/usr/bin/env python3
"""UP 命中率画像报告（M3 交付物②）。

读取全部 claims 的 direction/outcome，聚合 UP × claim_type（× 月），
渲染 markdown 到 logs/claims-vs-market-YYYYMMDD.md。
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import yaml  # noqa: E402

from investment_engine.up_hit_profile import aggregate_profile, render_markdown  # noqa: E402

CLAIMS_DIR = PROJECT_ROOT / "knowledge" / "claims"


def iter_claims():
    for yf in sorted(CLAIMS_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(yf.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data is None:
            continue
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = data.get("claims") if "claims" in data else [data]
            if not isinstance(items, list):
                items = [items]
        else:
            continue
        yield from (c for c in items if isinstance(c, dict) and c.get("id"))


def main() -> int:
    ap = argparse.ArgumentParser(description="UP 命中率画像")
    ap.add_argument("--out", default="", help="输出路径（默认 logs/claims-vs-market-<今天>.md）")
    args = ap.parse_args()

    claims = list(iter_claims())
    stats = aggregate_profile(claims)
    md = render_markdown(stats, generated_on=date.today().isoformat())

    out = Path(args.out) if args.out else \
        PROJECT_ROOT / "logs" / f"claims-vs-market-{date.today().isoformat()}.md"
    out.write_text(md, encoding="utf-8")
    settled = sum(v["total"]["hit"] + v["total"]["miss"]
                  for k, v in stats.items() if len(k) == 2)
    print(f"✅ 画像已写入 {out}（claims {len(claims)}，可计样本 UP×类型 组 {settled} 条）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
