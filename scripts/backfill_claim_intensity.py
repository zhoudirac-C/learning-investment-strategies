#!/usr/bin/env python3
"""
Auto-backfill intensity field for all existing claims.

Classification rules (applied in priority order):
  1. methodology/operation/technical-knowledge → high (UP's core framework)
  2. confidence=high + strong language → high (serious analysis)
  3. source_type=bilibili_video/bilibili_column → high (deep content)
  4. source_type=bilibili_dynamic_repost → low (repost/casual)
  5. stock code + statement < 50 chars → low (casual stock mention)
  6. stock-view + confidence=low → low
  7. evidence_quote < 30 chars → low (one-liner)
  8. default → medium

Outputs:
  - Modified claim YAML files (in-place, with backup)
  - logs/intensity_backfill_report.txt (audit trail)
"""

import os
import re
import sys
from datetime import datetime
from pathlib import Path

# Add project src to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

CLAIMS_DIR = PROJECT_ROOT / "knowledge" / "claims"
LOG_DIR = PROJECT_ROOT / "logs"
REPORT_PATH = LOG_DIR / "intensity_backfill_report.txt"

# ── Classification helpers ──

STRONG_LANGUAGE_KEYWORDS = [
    "确定性", "一定要", "必买", "核心", "主线", "类比", "格局",
    "机构都要买", "确定性很高", "可以格局", "类比锂电池",
]

STOCK_CODE_RE = re.compile(r"\b(\d{6})(?:\.SH|\.SZ|\.sh|\.sz)?\b")


def classify_intensity(claim: dict) -> tuple[str, str]:
    """Return (intensity, reason)."""
    claim_type = claim.get("claim_type", claim.get("type", ""))
    confidence = claim.get("confidence", "medium")
    source_type = claim.get("source_type", "")
    statement = claim.get("statement", "") or claim.get("text", "")
    subject = claim.get("subject", "") or claim.get("topic", "")
    evidence = claim.get("evidence_quote", "")
    interpretation = claim.get("interpretation", "")

    # Rule 1: methodology/operation/technical-knowledge → high
    if claim_type in ("methodology", "operation", "technical-knowledge"):
        return ("high", f"rule1: claim_type={claim_type} is UP core framework")

    # Combine all text for keyword matching
    all_text = f"{statement} {interpretation}"

    # Rule 2: high confidence + strong language → high
    if confidence == "high":
        for kw in STRONG_LANGUAGE_KEYWORDS:
            if kw in all_text:
                return ("high", f"rule2: confidence=high + keyword='{kw}'")

    # Rule 3: video/column source → high
    deep_source_types = {
        "bilibili_video", "bilibili_column",
        "视频", "复盘", "复盘专栏", "专栏", "深度", "早盘",
        "video", "column",
    }
    if source_type in deep_source_types or any(
        kw in source_type for kw in ("视频", "复盘", "专栏", "深度")
    ):
        return ("high", f"rule3: source_type={source_type} is deep content")

    # Rule 4: repost → low
    if "repost" in source_type.lower() or "转发" in source_type:
        return ("low", "rule4: repost/转发 source_type")

    # Define local from all_text for brevity check
    local_all = all_text

    # Rule 5: stock code + short statement → low
    stock_codes = STOCK_CODE_RE.findall(subject)
    if stock_codes and len(statement) < 50:
        return ("low", f"rule5: stock code {stock_codes[0]} + short statement ({len(statement)} chars)")

    # Rule 6: stock-view + low confidence → low
    if claim_type == "stock-view" and confidence == "low":
        return ("low", "rule6: stock-view + confidence=low")

    # Rule 7: very short evidence + short interpretation → low (true one-liner)
    if len(evidence) < 30 and len(interpretation) < 50:
        return ("low", f"rule7: evidence_quote short ({len(evidence)}c) + interpretation short ({len(interpretation)}c) → one-liner")

    # Rule 8: default → medium
    return ("medium", "rule8: default (needs review)")


def parse_claims_file(path: Path) -> tuple[list[dict], bool]:
    """Parse a claims YAML file. Returns (claims_list, is_list_format)."""
    import yaml
    text = path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        print(f"  ⚠️ YAML parse error in {path.name}: {e}")
        return [], False
    if data is None:
        return [], False
    if isinstance(data, list):
        return data, True
    if isinstance(data, dict):
        if "claims" in data:
            claims = data["claims"]
            return (claims if isinstance(claims, list) else [claims]), False
        return [data], False
    return [], False


def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    yaml_files = sorted(CLAIMS_DIR.glob("*.yaml"))
    if not yaml_files:
        print(f"No YAML files found in {CLAIMS_DIR}")
        return

    total_claims = 0
    updated_claims = 0
    stats = {"high": 0, "medium": 0, "low": 0}
    report_lines = [
        f"# Intensity Backfill Report",
        f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"# Total files scanned: {len(yaml_files)}",
        f"",
        f"## Classification Rules Applied",
        f"1. methodology/operation/technical-knowledge → high",
        f"2. confidence=high + strong language keywords → high",
        f"3. bilibili_video/bilibili_column → high",
        f"4. repost/转发 source_type → low",
        f"5. stock code in subject + statement < 50 chars → low",
        f"6. stock-view + confidence=low → low",
        f"7. evidence_quote < 30 chars → low",
        f"8. default → medium",
        f"",
    ]

    medium_needs_review: list[str] = []
    low_claims: list[str] = []

    for yf in yaml_files:
        claims, is_list = parse_claims_file(yf)
        if not claims:
            continue

        file_modified = False
        for i, claim in enumerate(claims):
            if not isinstance(claim, dict):
                continue
            total_claims += 1

            # Skip if already has intensity
            if "intensity" in claim:
                stats[claim["intensity"]] += 1
                continue

            # Classify
            intensity, reason = classify_intensity(claim)
            claim["intensity"] = intensity
            stats[intensity] += 1
            updated_claims += 1
            file_modified = True

            cid = claim.get("id", f"#{i}")
            stmt = (claim.get("statement") or claim.get("text", ""))[:50]
            entry = f"  {cid}: {intensity} ({reason}) | {stmt}"
            print(entry)

            if intensity == "medium":
                medium_needs_review.append(f"  {yf.name} → {cid}: {stmt}...")
            elif intensity == "low":
                low_claims.append(f"  {yf.name} → {cid}: {stmt}...")

        # Write back if modified
        if file_modified:
            import yaml
            # Backup original
            backup_path = yf.with_suffix(".yaml.bak")
            if not backup_path.exists():
                yf.rename(backup_path)

            if is_list:
                output = claims
            else:
                output = {"claims": claims} if len(claims) > 1 else claims[0]

            with open(yf, "w", encoding="utf-8") as f:
                yaml.dump(output, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    # ── Build report ──
    report_lines.append(f"## Summary")
    report_lines.append(f"Total claims: {total_claims}")
    report_lines.append(f"Updated (new intensity): {updated_claims}")
    report_lines.append(f"Already had intensity (skipped): {total_claims - updated_claims}")
    report_lines.append(f"")
    report_lines.append(f"### Distribution")
    report_lines.append(f"- high:   {stats['high']}")
    report_lines.append(f"- medium: {stats['medium']}")
    report_lines.append(f"- low:    {stats['low']}")
    report_lines.append(f"")

    report_lines.append(f"## ⚪ LOW intensity claims (review for correctness)")
    report_lines.append(f"  Count: {len(low_claims)}")
    report_lines.append(f"  These are claims classified as casual mentions / one-liners.")
    report_lines.append(f"  If any are actually serious analysis, reclassify to medium or high.")
    report_lines.append(f"")
    for line in low_claims:
        report_lines.append(line)
    report_lines.append(f"")

    report_lines.append(f"## 🟡 MEDIUM intensity claims (defaults, needs review)")
    report_lines.append(f"  Count: {len(medium_needs_review)}")
    report_lines.append(f"  These fell through all rules and got the default.")
    report_lines.append(f"  If any contain strong analysis, reclassify to high.")
    report_lines.append(f"")
    for line in medium_needs_review:
        report_lines.append(line)

    report_text = "\n".join(report_lines)
    REPORT_PATH.write_text(report_text, encoding="utf-8")

    print(f"\n{'='*60}")
    print(f"✅ Backfill complete!")
    print(f"   Total: {total_claims} | Updated: {updated_claims} | Skipped: {total_claims - updated_claims}")
    print(f"   high={stats['high']}, medium={stats['medium']}, low={stats['low']}")
    print(f"   Report: {REPORT_PATH}")


if __name__ == "__main__":
    main()
