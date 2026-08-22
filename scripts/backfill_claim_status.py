#!/usr/bin/env python3
"""Backfill claim status 生命周期：supersedes 边 → 旧 claim status=superseded。

背景（2026-08-22 方法论复盘发现）：claims 的 supersedes/contradicts 关系边已回填，
但被超越旧 claim 的 status 从未自动更新（全部停留在 active）。
framework/contradiction-policy.md 要求 cycle-shift/logic-broken 时更新旧 claim status。

规则（保守、机械、幂等）：
  - 被 ≥1 条 supersedes 边指向 且 status==active → status=superseded
  - contradicts 边不做自动翻转（矛盾方向需人工裁决，如 claim-20260810-030 事后证明
    contradict 方才是对的），仅在报告列出供人工 review
  - 重复运行不产生新变化（已 superseded 的跳过）

写法：按行定点替换（claim 块内的 `status: active` 行），不做整文件 yaml dump，
避免 flow-style 列表被展开造成的 diff 噪声。git 版本控制即备份。

用法：
  .venv/bin/python scripts/backfill_claim_status.py --dry-run   # 预览
  .venv/bin/python scripts/backfill_claim_status.py             # 执行
"""
from __future__ import annotations

import argparse
import re
from datetime import datetime
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLAIMS_DIR = PROJECT_ROOT / "knowledge" / "claims"
REPORT_PATH = PROJECT_ROOT / "logs" / "status_backfill_report.txt"

_ID_RE = re.compile(r"^(\s*)-?\s*id:\s*(\S+)\s*$")
_STATUS_ACTIVE_RE = re.compile(r"^(\s*)status:\s*[\"']?active[\"']?\s*$")


def load_claims(claims_dir: Path = CLAIMS_DIR) -> tuple[dict, dict]:
    """加载全部 claims。

    返回 (claims_by_id, file_texts)：
      claims_by_id: {claim_id: claim_dict}
      file_texts:   {Path: 原始文本}（仅含目标 claim 的文件后续会被改写）
    """
    claims_by_id: dict[str, dict] = {}
    file_texts: dict[Path, str] = {}
    for fp in sorted(claims_dir.glob("claim-*.yaml")):
        text = fp.read_text(encoding="utf-8")
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError:
            continue
        if isinstance(data, dict):
            items = data.get("claims") or []
        elif isinstance(data, list):
            items = data
        else:
            continue
        found = False
        for c in items:
            if isinstance(c, dict) and c.get("id"):
                claims_by_id[c["id"]] = c
                found = True
        if found:
            file_texts[fp] = text
    return claims_by_id, file_texts


def plan_status_updates(claims_by_id: dict) -> tuple[dict, list, list]:
    """纯函数：计算 status 更新计划。

    返回 (updates, contradicts_review, missing)：
      updates:            {claim_id: "superseded"} —— 被 supersedes 指向且当前 active
      contradicts_review: [claim_id] —— 仅被 contradicts 指向（无 supersedes），留人工
      missing:            [claim_id] —— 被关系边引用但不存在于任何文件
    """
    supersedes_targets: set[str] = set()
    contradicts_targets: set[str] = set()
    for c in claims_by_id.values():
        for t in (c.get("supersedes") or []):
            supersedes_targets.add(t)
        for t in (c.get("contradicts") or []):
            contradicts_targets.add(t)

    updates: dict[str, str] = {}
    missing: set[str] = set()
    for t in sorted(supersedes_targets):
        target = claims_by_id.get(t)
        if target is None:
            missing.add(t)
        elif target.get("status") == "active":
            updates[t] = "superseded"

    contradicts_review = sorted(
        t for t in contradicts_targets - supersedes_targets
        if t in claims_by_id and claims_by_id[t].get("status") == "active"
    )
    for t in contradicts_targets - supersedes_targets:
        if t not in claims_by_id:
            missing.add(t)

    return updates, contradicts_review, sorted(missing)


def rewrite_status_in_text(text: str, target_ids: set[str], new_status: str) -> tuple[str, set[str]]:
    """按行定点替换：把目标 claim 块内的 `status: active` 改为 new_status。

    块定位：`- id: <cid>`（或扁平格式的 `id: <cid>`）开启一个 claim 块，
    块内第一条 status:active 行被替换。其它行原样保留。
    返回 (新文本, 实际改动的 claim_id 集合)。
    """
    out_lines: list[str] = []
    changed: set[str] = set()
    current_id: str | None = None
    for line in text.splitlines(keepends=True):
        m = _ID_RE.match(line.rstrip("\n"))
        if m:
            current_id = m.group(2)
        elif current_id in target_ids and current_id not in changed:
            body = line.rstrip("\n")
            m2 = _STATUS_ACTIVE_RE.match(body)
            if m2:
                line = f"{m2.group(1)}status: {new_status}\n"
                changed.add(current_id)
        out_lines.append(line)
    return "".join(out_lines), changed


def main() -> int:
    parser = argparse.ArgumentParser(description="claims status 生命周期回填（supersedes→superseded）")
    parser.add_argument("--dry-run", action="store_true", help="只预览，不写文件")
    args = parser.parse_args()

    claims_by_id, file_texts = load_claims()
    updates, contradicts_review, missing = plan_status_updates(claims_by_id)

    print(f"claims 总数: {len(claims_by_id)}")
    print(f"待回填 superseded: {len(updates)}")
    print(f"contradicts 待人工 review: {len(contradicts_review)}")
    print(f"关系边引用的缺失 id: {len(missing)}")

    report_lines = [
        f"# status 生命周期回填报告 {datetime.now().isoformat(timespec='seconds')}",
        f"mode: {'dry-run' if args.dry_run else 'apply'}",
        f"claims 总数: {len(claims_by_id)}",
        f"回填 superseded: {len(updates)}",
        "",
        "## 回填清单（supersedes 边指向的旧 claim）",
    ]

    changed_files = 0
    for fp, text in sorted(file_texts.items(), key=lambda kv: str(kv[0])):
        ids_in_file = {
            c["id"] for c in
            ((yaml.safe_load(text).get("claims") or []) if isinstance(yaml.safe_load(text), dict)
             else (yaml.safe_load(text) or []))
            if isinstance(c, dict)
        } & set(updates)
        if not ids_in_file:
            continue
        new_text, changed = rewrite_status_in_text(text, ids_in_file, "superseded")
        for cid in sorted(changed):
            report_lines.append(f"  {cid}  <- {fp.name}")
        if not args.dry_run and changed:
            fp.write_text(new_text, encoding="utf-8")
        if changed:
            changed_files += 1

    report_lines += [
        "",
        f"## contradicts 待人工 review（{len(contradicts_review)}，不自动翻转）",
        *(f"  {cid}" for cid in contradicts_review),
        "",
        f"## 关系边引用的缺失 id（{len(missing)}）",
        *(f"  {cid}" for cid in missing),
    ]
    REPORT_PATH.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    print(f"{'[DRY RUN] 将改动' if args.dry_run else '已改动'}文件: {changed_files}")
    print(f"报告: {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
