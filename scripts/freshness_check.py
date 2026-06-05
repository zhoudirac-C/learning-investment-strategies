#!/usr/bin/env python3
"""
每日知识库 Freshness Check

检查最近几天的 raw 文档是否已及时处理为 claims，
以及知识库中是否存在明显滞后的 active claims。

用法：
    .venv/bin/python scripts/freshness_check.py [--days 3]
"""
from __future__ import annotations

import argparse
import glob
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

RAW_DIR = REPO_ROOT / "sources" / "raw" / "财经"
CLAIMS_DIR = REPO_ROOT / "knowledge" / "claims"


def _parse_date_from_filename(name: str) -> date | None:
    m = re.search(r"(\d{4})[-_](\d{2})[-_](\d{2})", name)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    m = re.search(r"(\d{2})[-_](\d{2})[-_](\d{2})", name)
    if m:
        try:
            return date(2000 + int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    return None


def _latest_claim_date() -> date | None:
    """从 claims 文件名中提取最新日期。"""
    latest = None
    for fp in CLAIMS_DIR.glob("claim-*.yaml"):
        m = re.search(r"claim-(\d{4})(\d{2})(\d{2})-", fp.name)
        if m:
            try:
                d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                if latest is None or d > latest:
                    latest = d
            except ValueError:
                pass
    return latest


def _check_unprocessed_raw(days: int = 3) -> list[Path]:
    """检查最近 days 天内是否有未处理的 raw 文档。"""
    cutoff = date.today() - timedelta(days=days)
    unprocessed: list[Path] = []

    for fp in sorted(RAW_DIR.glob("*.md")):
        file_date = _parse_date_from_filename(fp.name)
        if file_date is None or file_date < cutoff:
            continue

        # 检查是否有对应日期的 claim 文件
        date_prefix = file_date.strftime("%Y%m%d")
        claim_files = list(CLAIMS_DIR.glob(f"claim-{date_prefix}-*.yaml"))
        if not claim_files:
            unprocessed.append(fp)

    return unprocessed


def _check_stale_active_claims(days: int = 7) -> list[dict]:
    """检查是否有超过 days 天的 active claims 涉及最近热门主题。"""
    import yaml

    cutoff = date.today() - timedelta(days=days)
    stale: list[dict] = []

    for fp in CLAIMS_DIR.glob("claim-*.yaml"):
        m = re.search(r"claim-(\d{4})(\d{2})(\d{2})-", fp.name)
        if not m:
            continue
        try:
            claim_date = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
        if claim_date >= cutoff:
            continue  # 只检查旧 claims

        try:
            data = yaml.safe_load(fp.read_text(encoding="utf-8"))
        except Exception:
            continue

        if isinstance(data, list):
            claims_list = data
        elif isinstance(data, dict):
            claims_list = data.get("claims", [])
            if isinstance(claims_list, dict):
                claims_list = [claims_list]
        else:
            claims_list = []

        for c in claims_list:
            if c.get("status") == "active" and c.get("time_frame") in ("short-term", "intraday"):
                stale.append({
                    "id": c.get("id", ""),
                    "file": fp.name,
                    "date": claim_date.isoformat(),
                    "subject": c.get("subject", ""),
                    "statement": c.get("statement", "")[:60],
                    "time_frame": c.get("time_frame", ""),
                })

    return stale


def main():
    parser = argparse.ArgumentParser(description="每日知识库 Freshness Check")
    parser.add_argument("--days", type=int, default=3, help="检查最近 N 天的 raw")
    parser.add_argument("--stale-days", type=int, default=7, help="超过 N 天的 short-term claim 视为 stale")
    args = parser.parse_args()

    today = date.today()
    print(f"=== Freshness Check {today.isoformat()} ===\n")

    # 1. 最新 claim 日期
    latest_claim = _latest_claim_date()
    if latest_claim:
        gap = (today - latest_claim).days
        if gap == 0:
            print(f"✅ 最新 claims: {latest_claim.isoformat()} (今天)")
        elif gap <= 2:
            print(f"⚠️  最新 claims: {latest_claim.isoformat()} ({gap} 天前)")
        else:
            print(f"🚨 最新 claims: {latest_claim.isoformat()} ({gap} 天前) — 知识库严重滞后")
    else:
        print("🚨 未找到 claims 文件")

    # 2. 未处理的 raw
    unprocessed = _check_unprocessed_raw(days=args.days)
    if unprocessed:
        print(f"\n⚠️  发现 {len(unprocessed)} 篇未处理 raw（最近 {args.days} 天）:")
        for fp in unprocessed:
            print(f"   - {fp.name}")
        print(f"\n💡 建议: 运行 qing-learning 流程处理上述文档")
    else:
        print(f"\n✅ 最近 {args.days} 天的 raw 已全部处理")

    # 3. 陈旧的 short-term active claims
    stale = _check_stale_active_claims(days=args.stale_days)
    if stale:
        print(f"\n⚠️  发现 {len(stale)} 条超过 {args.stale_days} 天的 short-term active claims:")
        for c in stale[:10]:
            print(f"   - {c['id']} ({c['date']}) {c['subject']}: {c['statement']}...")
        if len(stale) > 10:
            print(f"   ... 还有 {len(stale) - 10} 条")
        print(f"\n💡 建议: 运行 qing-methodology-review 检查这些 claims 是否已过期")
    else:
        print(f"\n✅ 无超过 {args.stale_days} 天的 stale short-term claims")

    print("\n=== 检查完成 ===")

    # 返回退出码：有严重问题时返回 1
    if latest_claim and (today - latest_claim).days > 2:
        sys.exit(1)
    if unprocessed:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
