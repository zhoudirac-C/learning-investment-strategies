#!/usr/bin/env python3
"""回填 claim 的 related_stocks —— Gate5 v4 剩余检出（方案A，2026-09-19）。

背景：
  gate5 v3 词典最大匹配上线后，全量审计报出 523 条 claim 缺代码标注。
  经分类，其中大部分是「正文罗列/提及公司名但 related_stocks 为空」。

用户 2026-09-19 拍板：
  - Q1=A ：罗列式 → 补 related_stocks，**正文一律不动**
  - Q2   ：研报署名豁免（已在 gate v4 实现）
  - Q3   ：全部录入，不设上限
  - Q4   ：正文补码 —— **最终决定不做**（用户终裁「全部只补 related_stocks，接受现状」）

  原因：机器无法可靠区分「真标的」（中芯国际被闷杀）与「背景提及」
  （深度绑定中芯国际等核心客户）。为不污染正文文本，统一走结构化字段。

  语义依据：gate3 已确立「标的池 = related_stocks」；下游检索用 RS 而非正文。

写法纪律（skill qing-claim-schema-evolution §6）：
  - 文本级插入，不用 yaml.dump 全量重写（会丢注释/改格式）
  - 默认 dry-run；--apply 才写
  - 先备份；支持 --limit N 小范围实测

用法：
  python scripts/backfill_gate5_related_stocks.py --dry-run
  python scripts/backfill_gate5_related_stocks.py --apply --limit 3
  python scripts/backfill_gate5_related_stocks.py --apply
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
CLAIMS = REPO / "knowledge" / "claims"
DICT = REPO / "data" / "company_names.json"
NAME2CODE_FILE = REPO / "data" / "stock_name_code_map.json"

ROLE = "回填-正文提及"


def iter_claims(fp: Path):
    d = yaml.safe_load(fp.read_text(encoding="utf-8"))
    if d is None:
        return []
    if isinstance(d, list):
        items = d
    elif isinstance(d, dict):
        items = d["claims"] if isinstance(d.get("claims"), list) else [d]
    else:
        return []
    return [c for c in items if isinstance(c, dict) and c.get("id")]


def load_dicts():
    names = set(json.load(open(DICT, encoding="utf-8")))
    n2c = json.load(open(NAME2CODE_FILE, encoding="utf-8"))
    return names, n2c


_N2C_CACHE: dict | None = None


def _n2c() -> dict:
    """惰性加载 name→code 映射（供内联列表转块式时补码）。"""
    global _N2C_CACHE
    if _N2C_CACHE is None:
        _N2C_CACHE = json.load(open(NAME2CODE_FILE, encoding="utf-8"))
    return _N2C_CACHE or {}


_C2N_CACHE: dict | None = None


def _code2name() -> dict:
    """惰性构建 code→name 反查（内联裸码转块式时补 name）。"""
    global _C2N_CACHE
    if _C2N_CACHE is None:
        _C2N_CACHE = {v: k for k, v in _n2c().items()}
    return _C2N_CACHE or {}


def parse_gate_errors() -> dict[str, set[str]]:
    """跑 gate --all，解析出 {claim_id: {公司名, ...}}"""
    r = subprocess.run(
        [str(REPO / ".venv/bin/python"), "scripts/gate_validate_claims.py", "--all"],
        cwd=REPO, capture_output=True, text=True)
    out = r.stdout + r.stderr
    bad: dict[str, set[str]] = defaultdict(set)
    cur = None
    for line in out.splitlines():
        m = re.match(r"^❌\s+(\S+\.yaml)", line.strip())
        if m:
            cur = m.group(1)
            continue
        m = re.search(r"^\s*(\S+?):\s*'(.*?)'\s*在文本中出现但未标注 6 位代码", line)
        if m and cur:
            bad[m.group(1)].add(m.group(2))
    return bad


def find_claim_span(lines: list[str], cid: str) -> tuple[int, int]:
    """返回该 claim 在 lines 中的 [start, end) 行范围（end 为独占）。"""
    start = None
    for i, l in enumerate(lines):
        if re.match(r"^\s*-?\s*id\s*:\s*[\"']?" + re.escape(cid) + r"[\"']?\s*$", l.strip()):
            start = i
            break
    if start is None:
        raise ValueError(f"claim {cid} 未找到")
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if re.match(r"^\s*-\s*id\s*:", lines[j]):
            end = j
            break
    return start, end


def _indent_of(lines: list[str], claim_start: int) -> str:
    """推断该 claim 的字段缩进（从 id 行取）。"""
    for l in lines[claim_start : claim_start + 3]:
        m = re.match(r"^(\s*)-?\s*id\s*:", l)
        if m:
            return m.group(1) + "  "  # id 行缩进 + 2（字段比 `- ` 多两级）
    return "  "


def apply_to_file(raw: str, items: list[dict]) -> tuple[str, int]:
    """文本级写入 related_stocks 条目。支持三种存量结构：

      A. 顶层 related_stocks（{code,name,role} 字典列表）—— 主流 4790 条
      B. 嵌套 links.related_stocks（纯字符串列表）—— 153 条
      C. 两者皆无 —— 新建顶层字段

    返回 (新文本, 改动数)。
    """
    lines = raw.split("\n")
    changed = 0
    ops = []
    for it in items:
        try:
            start, end = find_claim_span(lines, it["cid"])
        except ValueError:
            continue
        # 定位顶层 related_stocks（缩进 <= 2 视为顶层）
        # 注意：嵌套 links.related_stocks 是纯字符串列表，gate5 不读它
        # （gate5 只读顶层 claim["related_stocks"]），故不写入嵌套位置，
        # 而是在顶层新建字段——否则回填不生效。
        top_rs = None
        for j in range(start, end):
            m = re.match(r"^(\s*)related_stocks\s*:", lines[j])
            if m and len(m.group(1)) <= 2:
                top_rs = j
                break
        ops.append((start, end, top_rs, it["add"]))

    # 倒序处理，避免行号漂移
    for start, end, top_rs, add in sorted(ops, key=lambda x: -x[0]):
        indent = _indent_of(lines, start)
        if top_rs is None:
            # 新建顶层字段，插到 claim 末尾（跳过尾部空行）
            ins = [f"{indent}related_stocks:"]
            for e in add:
                ins.append(f"{indent}- code: \"{e['code']}\"")
                ins.append(f"{indent}  name: \"{e['name']}\"")
                ins.append(f"{indent}  role: \"{ROLE}\"")
            k = end
            while k > start and lines[k - 1].strip() == "":
                k -= 1
            lines[k:k] = ins
            changed += len(add)
            continue

        cur = lines[top_rs]
        # 三种形态：`[]` 空数组 / `["A","B"]` 内联流式 / 块式列表
        blank = re.match(r"^(\s*)related_stocks\s*:\s*\[\s*\]\s*$", cur)
        inline = re.match(r"^(\s*)related_stocks\s*:\s*\[(.+)\]\s*$", cur)
        if blank:
            ind = blank.group(1)
            lines[top_rs] = f"{ind}related_stocks:"
            ins = []
            for e in add:
                ins.append(f"{ind}- code: \"{e['code']}\"")
                ins.append(f"{ind}  name: \"{e['name']}\"")
                ins.append(f"{ind}  role: \"{ROLE}\"")
            lines[top_rs + 1 : top_rs + 1] = ins
            changed += len(add)
        elif inline:
            # 内联流式列表 → 转块式（gate5 只读 dict 形式才能豁免）。
            # ⚠️ 内联项可能是 **裸 6 位数字码**（`[002167, 000657]`，YAML 解析为 int）
            #    或 **公司名**（`["盛科通信"]`）——两者要区别对待。
            ind = inline.group(1)
            old_items = [x.strip().strip('"').strip("'")
                         for x in inline.group(2).split(",") if x.strip()]
            lines[top_rs] = f"{ind}related_stocks:"
            ins = []
            for tok in old_items:
                if re.fullmatch(r"\d{6}", tok):
                    # 裸码 → code 即该值，name 反查
                    ins.append(f"{ind}- code: \"{tok}\"")
                    ins.append(f"{ind}  name: \"{_code2name().get(tok, '')}\"")
                    ins.append(f"{ind}  role: \"原有\"")
                else:
                    ins.append(f"{ind}- code: \"{_n2c().get(tok, '')}\"")
                    ins.append(f"{ind}  name: \"{tok}\"")
                    ins.append(f"{ind}  role: \"原有\"")
            for e in add:
                ins.append(f"{ind}- code: \"{e['code']}\"")
                ins.append(f"{ind}  name: \"{e['name']}\"")
                ins.append(f"{ind}  role: \"{ROLE}\"")
            lines[top_rs + 1 : top_rs + 1] = ins
            changed += len(add)
            continue
        else:
            ind_m = re.match(r"^(\s*)", cur)
            ind = ind_m.group(1) if ind_m else ""
            k = top_rs + 1
            while k < end:
                s = lines[k]
                # 空行 = 列表块结束（也天然排除跨入下一个 claim）
                if s.strip() == "":
                    break
                # 同缩进的列表项 / 续行
                if re.match(rf"^{re.escape(ind)}\s*-", s) or re.match(rf"^{re.escape(ind)}\s+\w", s):
                    k += 1
                    continue
                break
            ins = []
            for e in add:
                ins.append(f"{ind}- code: \"{e['code']}\"")
                ins.append(f"{ind}  name: \"{e['name']}\"")
                ins.append(f"{ind}  role: \"{ROLE}\"")
            lines[k:k] = ins
            changed += len(add)

    return "\n".join(lines), changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只出计划不写入（默认行为）")
    ap.add_argument("--apply", action="store_true", help="实际写入")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 个文件")
    ap.add_argument("--report", default=str(REPO / "temp/backfill_gate5_report.json"))
    args = ap.parse_args()

    dic, n2c = load_dicts()
    print(f"词典 {len(dic)} 名 / name→code {len(n2c)} 条")

    bad = parse_gate_errors()
    print(f"gate5 v4 报错 claim: {len(bad)} 条")

    def norm_code(x) -> str:
        return str(x).split(".")[0].zfill(6)

    plan = []
    skipped_dup = 0
    for f in sorted(CLAIMS.glob("*.yaml")):
        for c in iter_claims(f):
            cid = c["id"]
            if cid not in bad:
                continue
            rs = c.get("related_stocks") or []
            have_names = {str(x.get("name")) for x in rs if isinstance(x, dict)}
            have_codes = {norm_code(x.get("code", "")) for x in rs if isinstance(x, dict)}
            add = []
            for name in sorted(bad[cid]):
                if name in have_names:
                    continue
                code = n2c.get(name)
                if not code:
                    continue
                if norm_code(code) in have_codes:
                    skipped_dup += 1
                    continue
                add.append({"name": name, "code": code})
                have_codes.add(norm_code(code))
            if add:
                plan.append({"file": f.name, "cid": cid, "add": add})

    n_add = sum(len(p["add"]) for p in plan)
    files_touched = len({p["file"] for p in plan})
    print(f"待处理文件 {files_touched} / claim {len(plan)} / 补条目 {n_add} 处")
    if skipped_dup:
        print(f"（跳过同码异名 {skipped_dup} 处：拟更名/别名，视为已标注）")

    Path(args.report).write_text(
        json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"计划写出 {args.report}")

    if not args.apply:
        print("\n[dry-run] 未写入。加 --apply 执行。")
        for p in plan[:5]:
            print(f"  {p['cid']}: +{[e['name'] + '(' + e['code'] + ')' for e in p['add']]}")
        return 0

    bk = Path("/tmp/claims_backup_backfill")
    if not bk.exists():
        shutil.copytree(CLAIMS, bk)
        print(f"备份 → {bk}")

    targets = sorted({p["file"] for p in plan})
    if args.limit:
        targets = targets[: args.limit]
    done, cnt = 0, 0
    for fname in targets:
        fp = CLAIMS / fname
        raw = fp.read_text(encoding="utf-8")
        items = [p for p in plan if p["file"] == fname]
        new_raw, ch = apply_to_file(raw, items)
        if ch:
            fp.write_text(new_raw, encoding="utf-8")
            done += 1
            cnt += ch
            print(f"  ✓ {fname} (+{ch})")
    print(f"\n完成 {done} 文件 / +{cnt} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
