#!/usr/bin/env python3
"""
Claim up_id/up_name 回填脚本（阶段一）

策略：文本级插入，不重排 YAML。
- 从 source_path 反查 raw 文件的 up_uid/up_name
- 有 up_uid 的 claim → up_id=<uid>
- sources/chanlun/ → up_id="chanlun-original"，up_name="缠中说禅"
- 其余（无元数据）→ 跳过，待二次处理

幂等：已存在 up_id 字段的 claim 跳过。
插入位置：source_type 之后（保持字段顺序稳定）。
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

REPO = pathlib.Path("/home/ubuntu/learning-investment-strategies")
CLAIMS_DIR = REPO / "knowledge/claims"

CHANLUN_UID = "chanlun-original"
CHANLUN_NAME = "缠中说禅"

# 归属已确认的 up（2026-09-14 用户确认：sources/raw/财经 手工整理稿全是青枫浦上Q）
QINGFENG_UID = "1420210197"
QINGFENG_NAME = "青枫浦上Q"

# 手工整理稿目录（无 up_uid 元数据，但内容确认为青枫浦上Q）
MANUAL_DIRS = ("sources/raw/财经",)
# 早期 bilibili 抓取格式（头部无 front matter，但有"青枫浦上Q"署名）
EARLY_BILIBILI_PREFIX = "sources/original/bilibili"


def build_raw_index() -> tuple[dict[str, tuple[str, str]], dict[str, tuple[str, str]]]:
    """扫描 raw 文件，建立 path->(uid,name) 与 basename->(uid,name) 索引。"""
    by_path: dict[str, tuple[str, str]] = {}
    by_base: dict[str, tuple[str, str]] = {}
    for base in ("sources/original", "sources/raw"):
        d = REPO / base
        if not d.exists():
            continue
        for f in d.rglob("*.md"):
            try:
                head = f.read_text(encoding="utf-8", errors="ignore")[:1500]
            except Exception:
                continue
            m_uid = re.search(r'up_uid:\s*"?(\d+)"?', head)
            if not m_uid:
                continue
            m_nm = re.search(r'up_name:\s*"([^"]+)"', head)
            uid = m_uid.group(1)
            nm = m_nm.group(1) if m_nm else ""
            by_path[str(f.relative_to(REPO))] = (uid, nm)
            by_base.setdefault(f.name, (uid, nm))
    return by_path, by_base


def resolve(path: str, by_path, by_base) -> tuple[str, str] | None:
    """返回 (up_id, up_name)；无法判定返回 None。"""
    sp = (path or "").strip()
    if not sp:
        return None

    # 绝对路径归一（早期 claim 写成 /home/ubuntu/learning-investment-strategies/...）
    if sp.startswith("/"):
        marker = "learning-investment-strategies/"
        idx = sp.find(marker)
        sp = sp[idx + len(marker):] if idx >= 0 else sp.lstrip("/")

    if sp in by_path:
        return by_path[sp]
    bn = pathlib.Path(sp).name
    if bn and bn in by_base:
        return by_base[bn]
    # 缠论课程：非 up 来源，显式标识
    if sp.startswith("sources/chanlun"):
        return (CHANLUN_UID, CHANLUN_NAME)
    # 手工整理稿（2026-09-14 用户确认全部为青枫浦上Q 内容）
    for d in MANUAL_DIRS:
        if sp.startswith(d):
            return (QINGFENG_UID, QINGFENG_NAME)
    # 早期 bilibili 抓取格式（头部无 front matter，正文署名青枫浦上Q）
    if sp.startswith(EARLY_BILIBILI_PREFIX):
        return (QINGFENG_UID, QINGFENG_NAME)
    return None


def process_file(fp: pathlib.Path, by_path, by_base, apply: bool) -> tuple[int, int, int]:
    """处理单个 claim 文件。返回 (已改, 跳过已有, 无法判定)。"""
    text = fp.read_text(encoding="utf-8")
    lines = text.split("\n")
    out: list[str] = []
    changed = skipped = unresolved = 0
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        out.append(line)
        m = re.match(r"^(\s*-?\s*)source_path:\s*(.*)$", line)
        if not m:
            i += 1
            continue
        indent_raw = m.group(1)
        sp_val = m.group(2).strip().strip("'\"")
        # source_path 可能折行（长路径），尝试拼接续行
        j = i + 1
        while j < n and lines[j].startswith("  ") and not re.match(r"^\s*[a-z_]+:", lines[j]) and not lines[j].strip().startswith("-"):
            # 续行是 YAML 折行的一部分
            sp_val += " " + lines[j].strip()
            j += 1

        # 检查该 claim 块内是否已有 up_id（幂等）
        has_up = False
        k = j
        while k < n:
            nxt = lines[k]
            if re.match(r"^\s*- id:", nxt) or re.match(r"^\s*-?\s*source_path:", nxt):
                break
            if re.match(r"^\s*up_id:", nxt):
                has_up = True
                break
            if re.match(r"^\s*[a-z_]+:", nxt) and not nxt.startswith("    "):
                break
            k += 1

        if has_up:
            skipped += 1
        else:
            got = resolve(sp_val, by_path, by_base)
            if got:
                uid, nm = got
                # 插入到 source_path（及其续行）之后
                out.extend(lines[i + 1:j])
                ind = indent_raw
                out.append(f"{ind}up_id: \"{uid}\"")
                if nm:
                    out.append(f"{ind}up_name: \"{nm}\"")
                i = j
                changed += 1
                continue
            else:
                unresolved += 1
        i = j if j > i else i + 1

    if apply and changed:
        fp.write_text("\n".join(out), encoding="utf-8")
    return changed, skipped, unresolved


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="实际写入（默认 dry-run）")
    ap.add_argument("--limit", type=int, default=0, help="仅处理前 N 个文件（调试）")
    args = ap.parse_args()

    by_path, by_base = build_raw_index()
    print(f"raw 索引: {len(by_path)} 条路径 / {len(by_base)} 个 basename")

    files = sorted(CLAIMS_DIR.glob("claim-*.yaml"))
    if args.limit:
        files = files[: args.limit]

    tot_changed = tot_skip = tot_unres = 0
    files_changed = 0
    for fp in files:
        c, s, u = process_file(fp, by_path, by_base, args.apply)
        tot_changed += c
        tot_skip += s
        tot_unres += u
        if c:
            files_changed += 1

    mode = "已写入" if args.apply else "DRY-RUN"
    print(f"\n[{mode}] 文件 {len(files)} 个，改动 {files_changed} 个")
    print(f"  回填 claim:   {tot_changed}")
    print(f"  已有up_id跳过: {tot_skip}")
    print(f"  无法判定:     {tot_unres}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
