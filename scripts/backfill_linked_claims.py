#!/usr/bin/env python3
"""从 claims YAML 文件回填 watchlist.yaml 的 linked_claims。"""

import yaml
from pathlib import Path
from collections import defaultdict

repo = Path("/home/ubuntu/learning-investment-strategies")
claims_dir = repo / "knowledge" / "claims"

# 收集所有 claim 的 related_stocks
code_claims: dict[str, list[dict]] = defaultdict(list)

for f in sorted(claims_dir.glob("claim-*.yaml")):
    try:
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
    except Exception:
        continue
    if isinstance(data, list):
        claims = data
    elif isinstance(data, dict) and "claims" in data:
        claims = data["claims"]
    else:
        claims = [data] if isinstance(data, dict) else []
    if not isinstance(claims, list):
        claims = [claims]
    for c in claims:
        if not isinstance(c, dict):
            continue
        cid = c.get("id", "")
        stocks = c.get("related_stocks", [])
        if not stocks:
            continue
        for s in stocks:
            if isinstance(s, dict):
                raw = str(s.get("code", s.get("name", "")))
            else:
                raw = str(s)
            # 从 "协创数据(300857)" 提取 300857
            import re
            match = re.search(r'\(?(\d{6})\)?', raw)
            code = match.group(1) if match else raw if raw.isdigit() and len(raw) == 6 else ""
            if len(code) == 6 and code.isdigit():
                code_claims[code].append({
                    "claim_id": cid,
                    "claim_type": c.get("claim_type", ""),
                    "relevance": "direct",
                })

print(f"Claims scanned, {len(code_claims)} unique stock codes found")

# 加载 watchlist
with open(repo / "config" / "stock_monitor" / "watchlist.yaml") as f:
    wl = yaml.safe_load(f)

# 回填
updated = 0
for theme in wl.get("themes", []):
    for stock in theme.get("stocks", []):
        code = stock.get("code", "")
        if not code:
            continue
        num_code = code.replace(".SZ", "").replace(".SH", "")
        if num_code in code_claims:
            stock["linked_claims"] = code_claims[num_code][:5]
            updated += 1
        elif not stock.get("linked_claims"):
            stock["linked_claims"] = []

print(f"Updated {updated} stocks")

# 保存
with open(repo / "config" / "stock_monitor" / "watchlist.yaml", "w") as f:
    yaml.dump(wl, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

print("Saved.")
