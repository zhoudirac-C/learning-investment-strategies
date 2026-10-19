#!/usr/bin/env python3
"""把 claims_enabled: false 学派（watchlist 观察池）的 claim 从 knowledge/claims/ 迁出。

背景（2026-10-20）：
  config/schools.yaml 对 watchlist 学派写明「仅通知，不进 claim 库」，
  但该约定从未被执行——截至 2026-10-20 库内已有 254 条 watchlist claim
  （卢本圆复盘 550494308 等），并污染了方法论复盘（决策者曾误把
  「2.2万亿量能总开关」当成青枫浦上Q 本人的纪律）。

做法：
  1. 扫描 knowledge/claims/*.yaml，按 up_id 归属学派筛出 claims_enabled=false 的 claim
     （school 缺失时由 up_id 推导，与 claim_schema 一致）
  2. 追加写入 archive/schools/<school_id>/claims-quarantine.yaml（保留全部字段）
  3. 从源文件移除这些 claim；源文件移除后为空则删除文件
  4. 清洗引用：其它 claim 的 supersedes/contradicts/disagrees_with 中
     指向被迁出 claim 的 id 一律剔除（避免悬空引用）

用法：
  .venv/bin/python scripts/quarantine_school_claims.py --dry-run   # 先看清单
  .venv/bin/python scripts/quarantine_school_claims.py             # 执行
  .venv/bin/python scripts/quarantine_school_claims.py --restore   # 反向恢复

⚠️ 执行前先 git commit，便于回滚。
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from qing_investment.schools import load_schools, school_of_up  # noqa: E402

CLAIMS_DIR = REPO / "knowledge" / "claims"
ARCHIVE_DIR = REPO / "archive" / "schools"
REL_KEYS = ("supersedes", "contradicts", "disagrees_with")


def _iter_claim_files() -> list[Path]:
    return sorted(CLAIMS_DIR.glob("claim-*.yaml"))


def _load(path: Path):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data, True
    return data, False


def _claims_of(data, is_list: bool) -> list[dict]:
    if is_list:
        return [c for c in data if isinstance(c, dict)]
    return [c for c in (data.get("claims") or []) if isinstance(c, dict)]


def _disabled_schools() -> set[str]:
    return {s.school_id for s in load_schools() if not s.claims_enabled}


def collect() -> dict[str, list[tuple[Path, dict]]]:
    """school_id -> [(源文件, claim)]"""
    disabled = _disabled_schools()
    out: dict[str, list[tuple[Path, dict]]] = {}
    for path in _iter_claim_files():
        try:
            data, is_list = _load(path)
        except Exception as exc:
            print(f"  [skip] {path.name}: YAML 解析失败 {exc}")
            continue
        for claim in _claims_of(data, is_list):
            up_id = str(claim.get("up_id", "") or "")
            sid = school_of_up(up_id) if up_id else None
            if sid and sid in disabled:
                out.setdefault(sid, []).append((path, claim))
    return out


def strip_refs(target_ids: set[str], dry: bool) -> list[str]:
    """剔除指向被迁出 claim 的引用边，返回变更说明。"""
    changes: list[str] = []
    for path in _iter_claim_files():
        try:
            data, is_list = _load(path)
        except Exception:
            continue
        touched = False
        for claim in _claims_of(data, is_list):
            for key in REL_KEYS:
                vals = claim.get(key)
                if not isinstance(vals, list):
                    continue
                kept = [v for v in vals if str(v) not in target_ids]
                if len(kept) != len(vals):
                    changes.append(
                        f"{path.name}: {claim.get('id')} {key} 移除 "
                        f"{sorted(set(map(str, vals)) - set(kept))}"
                    )
                    claim[key] = kept
                    touched = True
        if touched and not dry:
            path.write_text(
                yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=1000),
                encoding="utf-8",
            )
    return changes


def remove_claims(grouped: dict[str, list[tuple[Path, dict]]], dry: bool) -> int:
    by_file: dict[Path, set[str]] = {}
    for items in grouped.values():
        for path, claim in items:
            by_file.setdefault(path, set()).add(str(claim.get("id")))

    removed = 0
    for path, ids in by_file.items():
        data, is_list = _load(path)
        if is_list:
            kept = [c for c in data if str(c.get("id")) not in ids]
            removed += len(data) - len(kept)
            if dry:
                continue
            if kept:
                path.write_text(
                    yaml.safe_dump(kept, allow_unicode=True, sort_keys=False, width=1000),
                    encoding="utf-8",
                )
            else:
                path.unlink()
        elif isinstance(data, dict):
            claims = data.get("claims") or []
            kept = [c for c in claims if str(c.get("id")) not in ids]
            removed += len(claims) - len(kept)
            if dry:
                continue
            if kept:
                data["claims"] = kept
                path.write_text(
                    yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=1000),
                    encoding="utf-8",
                )
            else:
                path.unlink()
    return removed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--restore", action="store_true", help="从隔离区恢复（暂未实现，用 git 回滚）")
    args = ap.parse_args()

    if args.restore:
        print("恢复请用 git checkout -- knowledge/claims archive/ （保留原始语义，避免重放丢失字段）")
        return 1

    grouped = collect()
    if not grouped:
        print("未发现需迁出的 claim（所有 claim 所属学派均 claims_enabled: true）")
        return 0

    total = sum(len(v) for v in grouped.values())
    print(f"待迁出 {total} 条 claim，涉及 {len({p for v in grouped.values() for p, _ in v})} 个文件")
    for sid, items in grouped.items():
        print(f"  · 学派 {sid}: {len(items)} 条")

    target_ids = {str(c.get("id")) for v in grouped.values() for _, c in v}
    ref_changes = strip_refs(target_ids, args.dry_run)
    print(f"引用边清理：{len(ref_changes)} 处")
    for line in ref_changes[:20]:
        print("   ", line)

    removed = remove_claims(grouped, args.dry_run)

    if args.dry_run:
        print(f"\n[DRY RUN] 将移除 {removed} 条，未写入任何文件。")
        return 0

    for sid, items in grouped.items():
        out_dir = ARCHIVE_DIR / sid
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / "claims-quarantine.yaml"
        existing = []
        if out.exists():
            prev = yaml.safe_load(out.read_text(encoding="utf-8")) or []
            if isinstance(prev, list):
                existing = prev
            elif isinstance(prev, dict):
                existing = prev.get("claims", []) or []
            else:
                existing = []
        out.write_text(
            yaml.safe_dump(existing + [c for _, c in items],
                           allow_unicode=True, sort_keys=False, width=1000),
            encoding="utf-8",
        )
        print(f"  归档 → {out.relative_to(REPO)} ({len(items)} 条)")

    print(f"\n完成：移除 {removed} 条，清理引用边 {len(ref_changes)} 处。")
    print("下一步：重跑 migrate_claims_to_neo4j.py + index_claims_to_qdrant.py 使检索层生效。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
