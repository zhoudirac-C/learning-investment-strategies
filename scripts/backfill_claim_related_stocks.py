#!/usr/bin/env python3
"""Backfill `related_stocks` field for claims that mention stocks but have empty field.

Target claims:
1. stock-view (17 claims) — subject/statement mentions specific stocks
2. sector-theme (24 claims) — statement contains stock codes but related_stocks is empty

Strategy:
- Build stock name→code mapping from watchlist + strategy_pack + existing claims
- For each target claim, parse statement/evidence/interpretation for known names/codes
- Extract unique stocks and write back to YAML

Usage:
    python scripts/backfill_claim_related_stocks.py [--dry-run]
"""

from __future__ import annotations

import argparse
import glob
import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent


def build_stock_map() -> tuple[dict[str, str], dict[str, str]]:
    """Build name→code and code→name mappings from all available sources."""
    name_to_code: dict[str, str] = {}
    code_to_name: dict[str, str] = {}

    # Source 1: watchlist.yaml
    wl_path = REPO / "config" / "stock_monitor" / "watchlist.yaml"
    if wl_path.exists():
        wl = yaml.safe_load(wl_path.read_text(encoding="utf-8"))
        for theme in wl.get("themes", []):
            for s in theme.get("stocks", []):
                code = s.get("code", "")
                name = s.get("name", "")
                if code and name:
                    num = re.sub(r"[^\d]", "", code)
                    if len(num) == 6:
                        name_to_code[name] = num
                        code_to_name[num] = name

    # Source 2: strategy_pack.yaml entry_points
    sp_path = REPO / "config" / "stock_monitor" / "strategy_pack.yaml"
    if sp_path.exists():
        sp = yaml.safe_load(sp_path.read_text(encoding="utf-8"))
        for ep in sp.get("entry_points", []):
            code = ep.get("code", "")
            name = ep.get("name", "")
            if code and name:
                num = re.sub(r"[^\d]", "", code)
                if len(num) == 6:
                    name_to_code[name] = num
                    code_to_name[num] = name

    # Source 3: existing claims with related_stocks
    claims_dir = REPO / "knowledge" / "claims"
    for f in sorted(claims_dir.glob("claim-*.yaml")):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        items = data.get("claims", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        for c in items:
            if not isinstance(c, dict):
                continue
            for s in c.get("related_stocks", []):
                if isinstance(s, dict):
                    code = str(s.get("code", ""))
                    name = s.get("name", "")
                    if code and name:
                        num = re.sub(r"[^\d]", "", code)
                        if len(num) == 6:
                            name_to_code[name] = num
                            code_to_name[num] = name

    # Add manual entries for stock-view claims where subject IS the stock name
    manual: dict[str, str] = {
        "澜起科技": "688008",
        "利仁科技": "001259",
        "拓普集团": "601689",
        "纬达光电": "873783",  # 北交所
        "盛剑科技": "603324",
        "扬杰科技": "300373",
        "金盘科技": "688676",
        "亨通光电": "600487",
        "禾盛新材": "002290",
        "盛美上海": "688082",
        "环旭电子": "601231",
        "源杰科技": "688498",
        "诚意药业": "603811",
        "海王生物": "000078",
        "东方海洋": "002086",
        "金禄电子": "301282",
        "天准科技": "688003",
        "能科科技": "603859",
        "达实智能": "002421",
        "绿的谐波": "688017",
        "润泽科技": "300442",
        "豫能控股": "001896",
        "金安国纪": "002636",
        "电科芯片": "600877",
        "铖昌科技": "001270",
        "鸿远电子": "603267",
        "振华科技": "000733",
        "思科瑞": "688053",
    }
    for name, code in manual.items():
        if name not in name_to_code:
            name_to_code[name] = code
            code_to_name[code] = name

    return name_to_code, code_to_name


def extract_stocks_from_text(text: str, name_to_code: dict[str, str],
                              code_to_name: dict[str, str]) -> list[dict]:
    """Extract unique stock mentions from text, return related_stocks format."""
    found: dict[str, str] = {}  # code → name

    # 1. Extract 6-digit stock codes (exclude dates: 2025MM, 2026MM etc.)
    for m in re.finditer(r"(\d{6})", text):
        code = m.group(1)
        is_year = int(code[:4]) in range(2018, 2030)
        is_month = 1 <= int(code[4:6]) <= 12
        if is_year and is_month:
            continue  # Date, not stock code
        name = code_to_name.get(code, "")
        if code not in found:
            found[code] = name

    # 2. Extract known stock names
    # Sort by length (longest first) to avoid partial matches
    sorted_names = sorted(name_to_code.keys(), key=len, reverse=True)
    for name in sorted_names:
        if name in text and name_to_code[name] not in found:
            found[name_to_code[name]] = name

    # Format as related_stocks
    result = []
    for code, name in found.items():
        entry = {"code": code, "name": name, "role": "参考标的"}
        result.append(entry)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill related_stocks for claims")
    parser.add_argument("--dry-run", action="store_true", help="Print changes without writing")
    args = parser.parse_args()

    name_to_code, code_to_name = build_stock_map()
    print(f"Stock mapping: {len(name_to_code)} names, {len(code_to_name)} codes")

    claims_dir = REPO / "knowledge" / "claims"
    total_updated = 0
    total_claims = 0
    stock_view_fixed = 0
    sector_theme_fixed = 0

    for fpath in sorted(claims_dir.glob("claim-*.yaml")):
        try:
            data = yaml.safe_load(fpath.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  ⚠️  Skipping {fpath.name}: {e}")
            continue

        items = data.get("claims", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        file_modified = False

        for c in items:
            if not isinstance(c, dict):
                continue

            cid = c.get("id", "")
            ct = c.get("claim_type", "")
            statement = c.get("statement", "")
            evidence = c.get("evidence_quote", "")
            interpretation = c.get("interpretation", "")
            subject = c.get("subject", "")

            # Skip if already has related_stocks (check both top-level and links)
            rs = c.get("related_stocks", [])
            if not rs or rs == []:
                # Also check under links (old format)
                links_dict = c.get("links", {})
                if isinstance(links_dict, dict):
                    links_rs = links_dict.get("related_stocks", [])
                    if isinstance(links_rs, list) and len(links_rs) > 0:
                        continue  # Has old-format related_stocks under links
            if isinstance(rs, list) and any(isinstance(s, dict) and (s.get("code") or s.get("name")) for s in rs):
                continue

            total_claims += 1

            # Only process stock-view and sector-theme
            if ct not in ("stock-view", "sector-theme"):
                continue

            # Extract stocks from text
            search_text = f"{subject} {statement} {evidence} {interpretation}"
            stocks = extract_stocks_from_text(search_text, name_to_code, code_to_name)

            if not stocks:
                continue

            # Set related_stocks
            c["related_stocks"] = stocks
            file_modified = True
            total_updated += 1

            if ct == "stock-view":
                stock_view_fixed += 1
            else:
                sector_theme_fixed += 1

            codes = [s["code"] for s in stocks]
            names = [s.get("name", "") for s in stocks]
            print(f"  ✅ {cid:35s} [{ct:15s}] → {', '.join(f'{n}({c})' for n, c in zip(names, codes))}")

        if file_modified and not args.dry_run:
            with open(fpath, "w", encoding="utf-8") as f:
                yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
            # print(f"  📝 Written: {fpath.name}")

    print(f"\n=== Summary ===")
    print(f"  Claims backfilled: {total_updated}")
    print(f"  Stock-view fixed:  {stock_view_fixed}")
    print(f"  Sector-theme fixed: {sector_theme_fixed}")
    print(f"  Total scanned:     {total_claims}")
    print(f"  Mode: {'DRY RUN (no changes)' if args.dry_run else 'LIVE'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
