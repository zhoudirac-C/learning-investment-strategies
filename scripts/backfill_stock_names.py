#!/usr/bin/env python3
"""
Backfill name property on Stock nodes that have incorrect names.

Problem:
migrate_claims_to_neo4j.py sets Stock.name = claim.subject
(a theme description like "磨底期非科技方向——储能/六氟磷酸锂"), which is NOT
the actual stock name. The real stock name appears in claim statement text.

Strategy (4 priorities):
  Priority 1 — positions.yaml code→name mapping (already correct, trusted source)
  Priority 2 — Extract stock name from Claim statement text via patterns:
    · 股票名(6位代码,…)   e.g. 天赐材料(002709,六氟龙头) → name=天赐材料
    · 股票名6位代码        e.g. 和顺科技301237         → name=和顺科技
  Priority 3 — watchlist.yaml code→name mapping
  Priority 4 — Delete Stock nodes where code IS NULL (entity classification errors)
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from neo4j import GraphDatabase
from qing_investment.agent.config import settings

# ── Regex patterns ──────────────────────────────────────────────────────────

# Pattern A: 股票名(代码,…)  e.g. 天赐材料(002709,六氟龙头)
PAREN_PATTERN = re.compile(r"([\u4e00-\u9fff]{2,6})\s*\((\d{6})")

# Pattern B: 股票名代码  e.g. 和顺科技301237  (no parentheses, Chinese name followed by 6-digit code)
RAW_PATTERN = re.compile(r"([\u4e00-\u9fff]{2,6})(\d{6})")

# 6-digit code anywhere
CODE_PATTERN = re.compile(r"\b(\d{6})\b")


def _is_name_abnormal(name: str | None) -> bool:
    """Check if a Stock node name is abnormal (needs fixing)."""
    if not name:
        return True
    name = name.strip()
    if not name:
        return True
    # Long names containing theme descriptions
    if len(name) > 8:
        return True
    # Names containing Chinese colons or em dashes (theme description markers)
    if "：" in name or "——" in name:
        return True
    # Name is just a code number (placeholder)
    if CODE_PATTERN.fullmatch(name):
        return True
    # Theme-descriptor keywords that never appear in real 2-6 char Chinese stock names
    theme_keywords = ["方向", "标的", "清单", "核心", "观察", "逻辑", "策略", "思路"]
    for kw in theme_keywords:
        if kw in name:
            return True
    return False


# ── Data loaders ────────────────────────────────────────────────────────────

def _load_positions_mapping() -> dict[str, str]:
    """Load code→name from positions.yaml."""
    mapping: dict[str, str] = {}
    try:
        path = REPO_ROOT / "config" / "stock_monitor" / "positions.yaml"
        if path.exists():
            import yaml
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            for account in data.get("accounts", []):
                for pos in account.get("positions", []):
                    name = pos.get("name", "")
                    code = (
                        pos.get("code", "")
                        .replace(".SZ", "")
                        .replace(".SH", "")
                        .replace(".sz", "")
                        .replace(".sh", "")
                    )
                    if name and code:
                        mapping[code] = name
    except Exception:
        pass
    return mapping


def _load_watchlist_mapping() -> dict[str, str]:
    """Load code→name from watchlist.yaml."""
    mapping: dict[str, str] = {}
    try:
        path = REPO_ROOT / "config" / "stock_monitor" / "watchlist.yaml"
        if path.exists():
            import yaml
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            for theme in data.get("themes", []):
                for stock in theme.get("stocks", []):
                    code = stock.get("code", "")
                    name = stock.get("name", "")
                    if code and name:
                        # Normalize code: strip .SH/.SZ suffix
                        code = (
                            code.replace(".SZ", "")
                            .replace(".SH", "")
                            .replace(".sz", "")
                            .replace(".sh", "")
                        )
                        mapping[code] = name
    except Exception:
        pass
    return mapping


# ── Name extraction from statement text ─────────────────────────────────────

def _extract_name_from_statements(code: str, statements: list[str]) -> str | None:
    """Extract the stock name from claim statement texts.

    Strategy: find the target code (6 digits) in each statement, then look
    backwards to find the associated Chinese stock name.

    Patterns handled:
      - 天赐材料(002709,六氟龙头)  → 天赐材料  (name before `(code`)
      - 和顺科技301237            → 和顺科技  (name directly before code, no paren)
      - 明确提到罗莱生活(002293,…) → 罗莱生活  (backtrack to last Chinese word boundary)

    When multiple statements give different names, picks the most frequent.
    """
    candidates: list[str] = []

    for stmt in statements:
        if not stmt:
            continue

        # Find all positions of the target code in this statement
        start = 0
        while True:
            pos = stmt.find(code, start)
            if pos == -1:
                break

            # --- Pattern A: 股票名(代码,...) ---
            # Look backwards: if there's a '(' right before the code,
            # find the Chinese stock name before the '('
            if pos > 0 and stmt[pos - 1] == "(":
                # Scan backwards from (pos-2) for Chinese characters
                name_chars: list[str] = []
                i = pos - 2
                while i >= 0 and "\u4e00" <= stmt[i] <= "\u9fff":
                    name_chars.append(stmt[i])
                    i -= 1
                if name_chars:
                    # We scanned backwards, so reverse to get correct order
                    name = "".join(reversed(name_chars))
                    # Only accept 2-6 character stock names
                    if 2 <= len(name) <= 6:
                        candidates.append(name)
                        start = pos + len(code)
                        continue

            # --- Pattern B: 股票名代码 ---
            # The code is preceded directly by Chinese chars (no paren)
            if pos > 0 and "\u4e00" <= stmt[pos - 1] <= "\u9fff":
                name_chars = []
                i = pos - 1
                while i >= 0 and "\u4e00" <= stmt[i] <= "\u9fff":
                    name_chars.append(stmt[i])
                    i -= 1
                if name_chars:
                    name = "".join(reversed(name_chars))
                    if 2 <= len(name) <= 6:
                        candidates.append(name)

            # Special case: name before '(' but there might be a gap like
            # 「罗莱生活(002293」— already handled by Pattern A above.

            start = pos + len(code)

    if not candidates:
        return None

    # Return most frequent name
    counter = Counter(candidates)
    return counter.most_common(1)[0][0]


# ── Main backfill logic ─────────────────────────────────────────────────────

def backfill_stock_names(driver) -> dict:
    """Fix Stock node names. Returns dict with counts of operations."""
    summary = {"fixed": 0, "deleted": 0, "skipped": 0, "errors": 0}

    # Load priority mappings
    positions_map = _load_positions_mapping()
    watchlist_map = _load_watchlist_mapping()

    print(f"  📋 positions.yaml: {len(positions_map)} code→name mappings")
    print(f"  📋 watchlist.yaml: {len(watchlist_map)} code→name mappings")

    with driver.session() as session:
        # ── Step 1: Delete redundant Stock nodes (Priority 4) ──
        # Only delete nodes where BOTH code AND name are NULL (truly orphaned)
        delete_result = session.run(
            "MATCH (s:Stock) WHERE s.code IS NULL AND s.name IS NULL DETACH DELETE s RETURN count(s) AS cnt"
        )
        deleted_count = delete_result.single()["cnt"]
        summary["deleted"] = deleted_count
        if deleted_count:
            print(f"  🗑️  Deleted {deleted_count} Stock node(s) with code=NULL")

        # ── Step 2: Find Stock nodes with abnormal names ──
        # Query: all Stock nodes with code NOT NULL, collect their names and codes
        result = session.run(
            """
            MATCH (s:Stock)
            WHERE s.code IS NOT NULL
            RETURN s.code AS code, s.name AS name
            """
        )
        all_stocks = [(r["code"], r["name"]) for r in result]
        print(f"\n  📊 Total Stock nodes with code: {len(all_stocks)}")

        abnormal_stocks = [
            (code, name) for code, name in all_stocks if _is_name_abnormal(name)
        ]
        print(f"  🔍 Stock nodes with abnormal names: {len(abnormal_stocks)}")

        if not abnormal_stocks:
            print("  ✅ All Stock nodes already have correct names.")
            return summary

        # ── Step 3: For each abnormal stock, find the correct name ──
        for code, old_name in abnormal_stocks:
            new_name: str | None = None
            source: str = ""

            # Priority 1: positions.yaml
            if code in positions_map:
                new_name = positions_map[code]
                source = "positions.yaml"

            # Priority 2: Extract from claim statement text
            if new_name is None:
                stmts = session.run(
                    """
                    MATCH (c:Claim)-[:ABOUT]->(s:Stock {code: $code})
                    WHERE c.statement IS NOT NULL AND c.statement <> ''
                    RETURN c.statement AS statement
                    """,
                    {"code": code},
                ).values()
                statements = [s[0] for s in stmts if s and s[0]]
                extracted = _extract_name_from_statements(code, statements)
                if extracted:
                    new_name = extracted
                    source = "claim statement"

            # Priority 3: watchlist.yaml
            if new_name is None and code in watchlist_map:
                new_name = watchlist_map[code]
                source = "watchlist.yaml"

            # Fallback: just use code as name if nothing found
            if new_name is None:
                new_name = code
                source = "code (fallback)"

            # Update the node
            session.run(
                "MATCH (s:Stock {code: $code}) SET s.name = $name",
                {"code": code, "name": new_name},
            )
            summary["fixed"] += 1
            print(f"  ✅ {code}: {old_name!r} → {new_name!r} [from {source}]")

        return summary


def main():
    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
    try:
        summary = backfill_stock_names(driver)
        print(f"\n{'='*50}")
        print(f"✅ Backfill complete:")
        print(f"   Fixed:  {summary['fixed']} Stock node(s)")
        print(f"   Deleted: {summary['deleted']} code=NULL Stock node(s)")
        print(f"   Skips:  {summary['skipped']}")

        # Validate
        with driver.session() as session:
            null_name = session.run(
                "MATCH (s:Stock) WHERE s.name IS NULL RETURN count(s) AS cnt"
            ).single()["cnt"]
            null_code = session.run(
                "MATCH (s:Stock) WHERE s.code IS NULL AND s.name IS NULL RETURN count(s) AS cnt"
            ).single()["cnt"]
            total = session.run("MATCH (s:Stock) RETURN count(s) AS cnt").single()["cnt"]
            abnormal = session.run(
                """
                MATCH (s:Stock)
                WHERE s.code IS NOT NULL
                  AND (size(s.name) > 10
                    OR s.name CONTAINS '：'
                    OR s.name CONTAINS '——'
                    OR s.name IS NULL)
                RETURN count(s) AS cnt
                """
            ).single()["cnt"]

        print(f"\n📊 Validation:")
        print(f"   Total Stock nodes: {total}")
        print(f"   name=NULL:       {null_name}")
        print(f"   code=NULL:       {null_code}")
        print(f"   abnormal names:  {abnormal}")
        if null_name == 0 and null_code == 0 and abnormal == 0:
            print("   ✅ All Stock nodes validated successfully!")
        else:
            if null_name:
                print(f"   ❌ {null_name} Stock node(s) still have NULL name!")
            if null_code:
                print(f"   ❌ {null_code} Stock node(s) still have NULL code!")
            if abnormal:
                print(f"   ❌ {abnormal} Stock node(s) still have abnormal names!")
    finally:
        driver.close()


if __name__ == "__main__":
    main()
