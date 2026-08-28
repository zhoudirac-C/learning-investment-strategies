#!/usr/bin/env python
"""10:00 open confirmation: fetch key indices, sector/concept indices, and key stocks."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from qing_investment.monitor.fetchers import DataFetcher

fetcher = DataFetcher()

# 主线板块/概念
sector_targets = {
    "华为概念": "1.BK0503",
    "鸿蒙概念": "1.BK0706",
    "信息安全": "1.BK0582",
    "光模块": "1.BK0518",
    "AI算力": "1.BK0519",
    "半导体": "1.BK0380",
    "存储芯片": "1.BK0514",
    "电子": "1.BK0267",
    "通信": "1.BK0269",
    "计算机": "1.BK0268",
    "银行": "1.BK0288",
    "非银金融": "1.BK0271",
    "家电": "1.BK0283",
    "食品饮料": "1.BK0286",
    "医药": "1.BK0272",
    "新能源汽车": "1.BK0441",
    "光伏": "1.BK0448",
    "国防军工": "1.BK0313",
    "稀土": "1.BK0322",
    "有色金属": "1.BK0279",
    "农业": "1.BK0290",
    "生物育种": "1.BK0795",
    "房地产": "1.BK0291",
    "煤炭": "1.BK0278",
    "石油石化": "1.BK0280",
    "纺织服装": "1.BK0282",
    "造纸": "1.BK0293",
    "旅游": "1.BK0292",
    "汽车": "1.BK0281",
    "电力": "1.BK0295",
}

out = fetcher.fetch(sector_targets)
qs = out.data.get("quotes", [])
rows = sorted(qs, key=lambda x: -(x.get("pct_change") or 0))

print("=== SECTORS (by pct_change desc) ===")
for q in rows:
    print(json.dumps({
        "label": q.get("label"),
        "name": q.get("name"),
        "latest": q.get("latest"),
        "pct_change": q.get("pct_change"),
        "high": q.get("high"),
        "low": q.get("low"),
        "open": q.get("open"),
        "prev_close": q.get("previous_close"),
    }, ensure_ascii=False))

print("---meta---")
print(json.dumps({"source": out.source, "count": out.quotes_count,
                  "latency_ms": out.latency_ms, "error": out.error}))
