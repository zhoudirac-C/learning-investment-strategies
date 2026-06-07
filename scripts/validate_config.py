#!/usr/bin/env python3
"""配置一致性校验脚本。

检查 config/stock_monitor/ 下 YAML 配置的结构完整性和规则矛盾。
退出码：0=干净, 1=有警告, 2=有错误
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

import yaml

CN_TZ = timezone(timedelta(hours=8))
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_DIR = REPO_ROOT / "config" / "stock_monitor"
CLAIMS_DIR = REPO_ROOT / "knowledge" / "claims"


# ── helpers ──────────────────────────────────────────────────

def load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def normalize_code(code: str) -> str:
    if not code:
        return ""
    code = str(code)
    if re.match(r"^\d{6}\.(SZ|SH)$", code):
        return code
    m = re.match(r"^sh(\d{6})$", code, re.IGNORECASE)
    if m:
        return f"{m.group(1)}.SH"
    m = re.match(r"^sz(\d{6})$", code, re.IGNORECASE)
    if m:
        return f"{m.group(1)}.SZ"
    return code


def parse_price_zone(raw):
    """Parse 'X-Y' string into (low, high) tuple; return None on failure."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return (float(raw), float(raw))
    s = str(raw).strip()
    m = re.match(r"([\d.]+)\s*[-–—]\s*([\d.]+)", s)
    if m:
        return (float(m.group(1)), float(m.group(2)))
    m = re.match(r"^([\d.]+)$", s)
    if m:
        v = float(m.group(1))
        return (v, v)
    return None


def _pct(a, b):
    if b == 0:
        return 0
    return round((a - b) / b * 100, 1)


# ── checks ───────────────────────────────────────────────────

class CheckResult:
    def __init__(self):
        self.errors: list[str] = []
        self.warnings: list[str] = []

    @property
    def ok(self):
        return not self.errors and not self.warnings

    def exit_code(self):
        if self.errors:
            return 2
        if self.warnings:
            return 1
        return 0


def check_code_format(watchlist: dict) -> CheckResult:
    r = CheckResult()
    bad = []
    for theme in watchlist.get("themes", []):
        for stock in theme.get("stocks", []):
            code = str(stock.get("code", ""))
            if code and not re.match(r"^\d{6}\.(SZ|SH)$", code):
                bad.append(f"  {code} ({stock.get('name')}) in theme '{theme.get('name')}'")
    if bad:
        r.errors.append(f"非标准 code 格式 ({len(bad)} 处):\n" + "\n".join(bad))
    return r


def check_entry_duplicates(strategy_pack: dict) -> CheckResult:
    r = CheckResult()
    eps = strategy_pack.get("quant_entry_strategy", {}).get("entry_points", [])
    seen = {}
    for i, ep in enumerate(eps):
        key = f"{ep.get('code')}_{ep.get('name')}"
        if key in seen:
            r.errors.append(
                f"entry_points 重复: {key} 在第 {seen[key]} 和 {i} 行"
            )
        seen[key] = i
    return r


def check_sector_groups_coverage(watchlist: dict, strategy_pack: dict) -> CheckResult:
    r = CheckResult()
    wl_ids = {t["id"] for t in watchlist.get("themes", [])}
    sg_ids = {g["id"] for g in strategy_pack.get("sector_groups", [])}

    missing = []
    for tid in sorted(wl_ids):
        if tid in sg_ids:
            continue
        t = next((t for t in watchlist.get("themes", []) if t["id"] == tid), None)
        if not t:
            continue
        # Only flag themes that have tradable stocks
        has_tradable = any(
            s.get("tradable", True) for s in t.get("stocks", [])
        )
        if has_tradable:
            missing.append(f"  {tid} ({t.get('name')}, {len(t.get('stocks', []))} stocks)")

    extra = sg_ids - wl_ids
    if extra:
        r.warnings.append(
            f"sector_groups 中有 {len(extra)} 个 ID 在 watchlist 中没有对应 theme: {sorted(extra)}"
        )
    if missing:
        r.warnings.append(
            f"watchlist 中有 {len(missing)} 个主题未在 sector_groups 中:\n" + "\n".join(missing)
        )
    return r


def check_today_snapshot_location(watchlist: dict, strategy_pack: dict) -> CheckResult:
    r = CheckResult()
    if watchlist.get("today_snapshot"):
        r.errors.append("today_snapshot 仍存在于 watchlist.yaml — 应只放在 strategy_pack.yaml")
    if not strategy_pack.get("today_snapshot"):
        r.warnings.append("strategy_pack.yaml 缺少 today_snapshot")
    return r


def check_claims_consistency(strategy_pack: dict, claims_dir: Path) -> CheckResult:
    """检查 entry_points 是否与最近 claims 中的博主纪律矛盾。

    常见矛盾：UP 说"不追高/韭菜/只观察"，但 entry_points 配了介入区间。
    """
    r = CheckResult()
    if not claims_dir.exists():
        return r

    # Load recent claims (last 7 days)
    cutoff = datetime.now(CN_TZ) - timedelta(days=7)
    recent_claims = []
    for f in sorted(claims_dir.glob("claim-*.yaml")):
        doc = load_yaml(f)
        if not isinstance(doc, dict):
            continue
        source_date_str = doc.get("source_date", "")
        try:
            if isinstance(source_date_str, str):
                source_date = datetime.strptime(source_date_str, "%Y-%m-%d").replace(tzinfo=CN_TZ)
            else:
                # Already a date/datetime object
                source_date = source_date_str
                if hasattr(source_date, 'replace'):
                    source_date = source_date.replace(tzinfo=CN_TZ)
        except (ValueError, TypeError):
            continue
        if source_date >= cutoff:
            # Flatten: each claim in the claims list
            for claim in doc.get("claims", []) or []:
                if isinstance(claim, dict):
                    claim["_source_date"] = source_date_str
                    claim["_file"] = f.name
                    recent_claims.append(claim)

    # UP "no-chase" keywords
    no_chase_keywords = [
        "不追高", "不追涨", "韭菜", "只观察不介入", "不介入",
        "不要买", "规避", "不碰", "不参与", "放弃",
    ]

    eps = strategy_pack.get("quant_entry_strategy", {}).get("entry_points", [])
    for ep in eps:
        ep_note = str(ep.get("note", "")).lower()
        ep_zone = str(ep.get("entry_zone", "")).lower()

        # Skip entries already marked "只观察不介入"
        if "只观察不介入" in ep_zone or "只观察不介入" in ep_note:
            continue
        if str(ep.get("position_ratio", "")) == "0":
            continue

        # Check if any claim warns against this stock / sector
        for claim in recent_claims:
            claim_stmt = str(claim.get("statement", "")).lower()
            claim_content = str(claim).lower()

            # Match stock code or sector
            code = normalize_code(str(ep.get("code", "")))
            name = str(ep.get("name", "")).lower()
            if name not in claim_content and code[-6:] not in claim_content:
                continue

            for kw in no_chase_keywords:
                if kw in claim_stmt:
                    r.errors.append(
                        f"claims 矛盾: claim-{claim.get('id', '?')} 中 UP 说'{kw}'，"
                        f"但 entry_points 中 {ep.get('name')}({ep.get('code')}) "
                        f"配置了 entry_zone={ep.get('entry_zone')}"
                    )
                    break

    return r


def check_position_zones_staleness(
    positions: dict, watchlist: dict, strategy_pack: dict
) -> CheckResult:
    """检查持仓价格区间是否可能失真（静态检查，不依赖实时行情）。

    检测项：
    - 是否缺少 reduce_zone / risk_zone
    - reduce_zone 是否用 risk_line 替代（可能漏报）
    """
    r = CheckResult()
    for account in positions.get("accounts", []) or []:
        for pos in account.get("positions", []) or []:
            code = normalize_code(str(pos.get("code", "")))
            name = pos.get("name", "?")

            has_reduce = pos.get("reduce_zone")
            has_risk = pos.get("risk_zone") or pos.get("risk_line")

            if not has_reduce and not has_risk:
                r.errors.append(
                    f"持仓 {name}({code}) 缺少 reduce_zone 和 risk_zone — 大跌将无提醒"
                )

    return r


# ── main ─────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="配置一致性校验")
    parser.add_argument("--config-dir", default=str(DEFAULT_CONFIG_DIR))
    parser.add_argument("--claims-dir", default=str(CLAIMS_DIR))
    parser.add_argument("--positions", action="store_true",
                        help="也检查 positions.yaml（需要存在）")
    parser.add_argument("--quiet", action="store_true",
                        help="只输出问题，干净时不输出")
    args = parser.parse_args(argv)

    config_dir = Path(args.config_dir)
    claims_dir = Path(args.claims_dir)

    watchlist = load_yaml(config_dir / "watchlist.yaml")
    strategy_pack = load_yaml(config_dir / "strategy_pack.yaml")

    all_results: list[tuple[str, CheckResult]] = []

    def run(name, fn, *fn_args):
        result = fn(*fn_args)
        all_results.append((name, result))

    run("code 格式", check_code_format, watchlist)
    run("entry 去重", check_entry_duplicates, strategy_pack)
    run("sector 覆盖", check_sector_groups_coverage, watchlist, strategy_pack)
    run("today_snapshot 位置", check_today_snapshot_location, watchlist, strategy_pack)
    run("claims 一致性", check_claims_consistency, strategy_pack, claims_dir)

    if args.positions:
        positions_path = config_dir / "positions.yaml"
        if positions_path.exists():
            positions = load_yaml(positions_path)
            run("持仓区间完整性", check_position_zones_staleness,
                positions, watchlist, strategy_pack)

    # Output
    total_errors = 0
    total_warnings = 0
    clean_count = 0

    for name, result in all_results:
        if result.ok and args.quiet:
            clean_count += 1
            continue
        if result.ok:
            print(f"[✅] {name}: OK")
            clean_count += 1
            continue

        status = "❌" if result.errors else "⚠️"
        print(f"[{status}] {name}:")
        for e in result.errors:
            print(f"  ERROR: {e}")
            total_errors += 1
        for w in result.warnings:
            print(f"  WARN:  {w}")
            total_warnings += 1
        print()

    summary_parts = [f"{clean_count} checks clean"]
    if total_errors:
        summary_parts.append(f"{total_errors} errors")
    if total_warnings:
        summary_parts.append(f"{total_warnings} warnings")

    exit_code = 2 if total_errors else (1 if total_warnings else 0)
    if not args.quiet or exit_code != 0:
        print(f"SUMMARY: {', '.join(summary_parts)} (exit={exit_code})")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
