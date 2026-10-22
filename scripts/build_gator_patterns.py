#!/usr/bin/env python3
"""P3：鳄鱼派 50 章全量拆解 → reasoning-patterns gator 侧草案。

设计：docs/design/dual-school-architecture.md §3.2
输入：sources/third_party/gator-method/03-规则体系/*.md（56 个文件）
输出：
  - framework/reasoning-patterns-gator.yaml（gator school pattern，草案）
  - reports/gator-pattern-draft-<date>.md（人工 review 清单）

解析策略（章节文件结构统一）：
  H2        章标题 → pattern name（含 `[核心]` `[可计算]` 标签）
  来源：      → source_ref / source_dates（提取 YYYY-MM-DD / YYYYMMDD）
  ### 小节   → trigger 条目来源
  ```text   IF/THEN 块 → 阈值与规则（结构化存 trigger/falsification）
  | 表格     → 判定标准摘录
  受限来源   → 跳过（公开版无正文）

用法：
    python scripts/build_gator_patterns.py --dry-run
    python scripts/build_gator_patterns.py
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "sources" / "third_party" / "gator-method" / "03-规则体系"
OUT_YAML = REPO_ROOT / "framework" / "reasoning-patterns-gator.yaml"
REPORT_DIR = REPO_ROOT / "reports"

CN_NUM = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8,
    "九": 9, "十": 10, "十一": 11, "十二": 12, "十三": 13, "十四": 14, "十五": 15,
    "十六": 16, "十七": 17, "十八": 18, "十九": 19, "二十": 20,
}


def cn_chapter_to_int(text: str) -> int | None:
    """从章标题提取章号。支持『三十五』『四十八』等。"""
    m = re.match(r"^([一二三四五六七八九十]+)、", text)
    if not m:
        return None
    s = m.group(1)
    if s in CN_NUM:
        return CN_NUM[s]
    # 处理 21-59：X十Y / X十 / 十Y
    m2 = re.match(r"^([一二三四五])?十([一二三四五六七八九])?$", s)
    if m2:
        tens = CN_NUM.get(m2.group(1), 1) if m2.group(1) else 1
        ones = CN_NUM.get(m2.group(2), 0) if m2.group(2) else 0
        return tens * 10 + ones
    return None


def parse_chapter(path: Path) -> dict | None:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return None

    lines = text.splitlines()
    title_line = lines[0]
    if not title_line.startswith("## "):
        return None

    raw_title = title_line[3:].strip()
    # 章号
    chapter_num = cn_chapter_to_int(raw_title)
    if chapter_num is None:
        return None

    # 受限来源章节跳过
    if "受限来源" in raw_title or "公开版不收录" in text[:200]:
        return {
            "chapter_num": chapter_num,
            "title": raw_title,
            "restricted": True,
        }

    # 标签：[核心] [可计算] [重要] [分类表]
    # 注意：[可计算] 既可能在标题行，也可能出现在正文小节标题（如 `### 20.1 xxx [可计算]`）
    header_tags = re.findall(r"`?\[([^\]]+)\]`?", raw_title)
    body_tags = re.findall(r"`?\[([^\]]+)\]`?", "\n".join(lines[1:]))
    tags = header_tags + body_tags
    tags = [t for t in tags if t and not t.startswith("http") and len(t) <= 12]
    core = any("核心" in t for t in tags)
    computable = any("可计算" in t for t in tags)

    # 名称（去掉标签与章号前缀）
    name = re.sub(r"^[一二三四五六七八九十]+、", "", raw_title)
    name = re.sub(r"`?\[[^\]]+\]`?", "", name).strip()
    name = re.sub(r"（[^）]*20\d{6}[^）]*）", "", name).strip()  # 去掉日期括注

    # 来源行
    source_line = ""
    for ln in lines[1:12]:
        if ln.startswith("来源：") or ln.startswith("来源:"):
            source_line = ln.split("：", 1)[-1].split(":", 1)[-1].strip()
            break

    source_dates = sorted(set(
        re.findall(r"(20\d{2})[-/]?(\d{2})[-/]?(\d{2})", source_line)
    ))
    source_dates = [f"{y}-{m}-{d}" for y, m, d in source_dates]

    # 小节标题
    subsections = [ln[4:].strip() for ln in lines if ln.startswith("### ")]

    # IF/THEN 规则块
    thresholds: list[str] = []
    in_block = False
    for ln in lines:
        if ln.strip().startswith("```"):
            in_block = not in_block
            continue
        if in_block and re.search(r"\bIF\b|\bTHEN\b|>|≥|≤|>=", ln):
            s = ln.strip()
            if s and not s.startswith("⚠️") or "IF" in s:
                thresholds.append(s)
    # 去重保序
    seen: set[str] = set()
    thresholds = [t for t in thresholds if not (t in seen or seen.add(t))]

    # 表格行（判定标准）
    table_rows: list[str] = []
    for ln in lines:
        if ln.strip().startswith("|") and "---" not in ln:
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            if len(cells) >= 2 and cells[0] not in ("#", "特征", "对比", "周期"):
                table_rows.append(" | ".join(cells[:3]))

    # 正文摘要（前 3 段非标题非表格文本）
    body_lines = [
        ln.strip() for ln in lines[1:]
        if ln.strip()
        and not ln.startswith("#")
        and not ln.strip().startswith("|")
        and not ln.strip().startswith("```")
        and not ln.strip().startswith(">")
        and not ln.strip().startswith("来源")
        and not re.match(r"^[-*]\s*$", ln.strip())
    ][:4]
    summary = " ".join(body_lines)[:400]

    return {
        "chapter_num": chapter_num,
        "title": raw_title,
        "name": name,
        "tags": tags,
        "core": core,
        "computable": computable,
        "source_line": source_line,
        "source_dates": source_dates,
        "subsections": subsections,
        "thresholds": thresholds[:20],
        "table_rows": table_rows[:12],
        "summary": summary,
        "file": str(path.relative_to(REPO_ROOT)),
        "restricted": False,
    }


# 章名关键词 → 英文 slug（人工映射，保证 pattern_id 可读且可语义匹配）
SLUG_MAP = {
    1: "stop-falling-5-signals", 2: "mainline-3-buy-points", 3: "mainline-horse-race",
    4: "position-sizing", 5: "take-profit", 6: "long-short-response",
    7: "defense-vs-offense", 8: "scissors-divergence", 9: "offense-defense-sectors",
    10: "bull-4-taboos", 11: "secondary-pullback-6-steps", 12: "hedge-3-levels",
    13: "four-buy-points", 14: "decline-depth-left-buy", 15: "false-bottom-rules",
    16: "decision-6-steps", 17: "three-kinds-of-money", 18: "trading-system-3-investors",
    19: "stop-profit-loss-winrate", 20: "emotion-cycle-themes", 21: "industry-cycle-3-turns",
    22: "fundamental-framework", 23: "liquidity-fund-behavior", 24: "blackswan-response",
    25: "three-kills-defense", 26: "ta-core-thresholds", 27: "longterm-allocation",
    28: "five-system-articles", 29: "shortterm-cash-defense", 30: "shortterm-stock-picking",
    31: "dog-walking-gap", 32: "longterm-trapped-3-steps", 33: "weak-band-2-styles",
    37: "shortterm-leader-system", 38: "margin-stock-picking", 39: "herd-collapse-bull-end",
    40: "market-echelon-decline-4types", 41: "longge-behavior-3-states", 42: "main-contradiction-ai-bubble",
    43: "emotion-rhythm-3-waves", 44: "insight-soul-sector", 45: "index-sector-mismatch",
    46: "signal-two-faces", 47: "longge-3-axes", 48: "pig-cycle-3-signals",
    49: "bottom-structure-2-types", 50: "mainline-replacement", 51: "usbond-asset-choice",
    52: "risk-appetite-self", 53: "ai-market-reading-module",
}


def slugify(title: str, num: int) -> str:
    """生成 pattern_id：gator-ch<num>-<slug>。"""
    if num in SLUG_MAP:
        return f"gator-ch{num:02d}-{SLUG_MAP[num]}"
    ascii_part = re.sub(r"[^a-zA-Z0-9]+", "-", title).strip("-").lower()
    if len(ascii_part) < 3:
        ascii_part = f"rule{num:02d}"
    return f"gator-ch{num:02d}-{ascii_part[:32]}"


def build_pattern(ch: dict) -> dict:
    """章节 → reasoning-pattern 结构。"""
    pid = slugify(ch["name"], ch["chapter_num"])
    # description：供 embedding 语义路由，必须包含可检索的自然语言
    desc_bits = [f"鳄鱼派（gator school）第{ch['chapter_num']}章：{ch['name']}。"]
    if ch["summary"]:
        desc_bits.append(ch["summary"][:250])
    if ch["subsections"]:
        desc_bits.append("涉及：" + "；".join(ch["subsections"][:5]) + "。")
    desc_bits.append("用于鳄鱼派资金生态位与规则体系的判断。")

    return {
        "pattern_id": pid,
        "school": "gator",
        "name": ch["name"],
        "chapter": ch["chapter_num"],
        "description": " ".join(desc_bits),
        "trigger": (ch["thresholds"][:6] or ch["subsections"][:4] or [ch["name"]]),
        "steps": ch["subsections"][:8] or [ch["name"]],
        "thresholds": ch["thresholds"],
        "table_rules": ch["table_rows"],
        "falsification": [],
        "computable": ch["computable"],
        "core": bool(ch["core"]),
        "source_ref": ch["source_line"],
        "source_dates": ch["source_dates"],
        "source_path": ch["file"],
        "provenance": "third_party/gator-method（非UP原文，待原文校验）",
        "validation": {},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    files = sorted(SRC_DIR.glob("*.md"))
    files = [f for f in files if f.name != "README.md"]

    chapters: list[dict] = []
    restricted: list[int] = []
    for f in files:
        ch = parse_chapter(f)
        if not ch:
            print(f"⚠️  跳过（无法解析）: {f.name}")
            continue
        if ch.get("restricted"):
            restricted.append(ch["chapter_num"])
            continue
        chapters.append(ch)

    chapters.sort(key=lambda c: c["chapter_num"])
    patterns = [build_pattern(c) for c in chapters]

    computable_count = sum(1 for p in patterns if p["computable"])
    print(f"解析章节：{len(chapters)} 章（受限跳过 {len(restricted)}：{sorted(restricted)}）")
    print(f"生成 pattern：{len(patterns)} 个，其中 [可计算] {computable_count} 个")

    if args.dry_run:
        print("\n── 预览（前 5 章）──")
        for p in patterns[:5]:
            print(f"  {p['pattern_id']}")
            print(f"    名称: {p['name']}  | 章: {p['chapter']} | 可计算: {p['computable']}")
            print(f"    阈值 {len(p['thresholds'])} 条，表格 {len(p['table_rules'])} 行")
        return 0

    # 写 YAML
    doc = {
        # v1.1-draft（2026-10-22）：新增第 56 章「护盘机制与底部周期操作法」
        # （10-16~10-22 公众号回补 55 条 claim 提炼；evolution_log 见本文件头部）
        "version": "1.1-draft",
        "school": "gator",
        "generated_by": "scripts/build_gator_patterns.py",
        "generated_at": date.today().isoformat(),
        "source": "sources/third_party/gator-method/03-规则体系/",
        "provenance_note": (
            "第三方提炼库（非鳄鱼派 UP 原文）。草案状态，触发条件/步骤为程序化摘录，"
            "需人工 review 后转正式库；冲突章节进 framework/school-conflicts.yaml。"
        ),
        "stats": {
            "chapters": len(chapters),
            "patterns": len(patterns),
            "computable": computable_count,
            "restricted_skipped": sorted(restricted),
        },
        # 演进日志：每次新增/修订章节时追加（版本递增规则见 framework-maintenance skill）
        "evolution_log": [
            {
                "version": "1.1-draft",
                "date": "2026-10-22",
                "change": "新增第 56 章「护盘机制与底部周期操作法」（ch56-guard-mechanism-bottom-cycle，可计算）",
                "basis": "10-16~10-22 公众号回补提取的 55 条 claim（claim-20261016-004/005、claim-20261019-003/004、claim-20261020-006/007、claim-20261021-008/009、claim-20261022-005）",
                "approved_by": "用户拍板 2026-10-22（沉淀成第 56 篇文章后再更新推理 yaml）",
            }
        ],
        "patterns": patterns,
    }
    OUT_YAML.write_text(
        yaml.dump(doc, allow_unicode=True, sort_keys=False, width=1000),
        encoding="utf-8",
    )
    print(f"✅ 写入 {OUT_YAML.relative_to(REPO_ROOT)}")

    # 写人工 review 清单
    REPORT_DIR.mkdir(exist_ok=True)
    report = REPORT_DIR / f"gator-pattern-draft-{date.today().isoformat()}.md"
    lines = [
        f"# 鳄鱼派 pattern 草案 review 清单（{date.today().isoformat()}）",
        "",
        f"- 章节 {len(chapters)} 章 → pattern {len(patterns)} 个（可计算 {computable_count} 个）",
        f"- 受限跳过：{sorted(restricted)}",
        "- 待办：① 检查 pattern 名称/description 是否可被语义路由命中 ② 标注与 Q 框架冲突章节 ③ 补齐 falsification",
        "",
        "| # | pattern_id | 名称 | 核心 | 可计算 | 阈值数 | 小节数 |",
        "|---|---|---|---|---|---|---|",
    ]
    for p in patterns:
        lines.append(
            f"| {p['chapter']} | `{p['pattern_id']}` | {p['name'][:30]} | "
            f"{'✅' if p['core'] else ''} | {'✅' if p['computable'] else ''} | "
            f"{len(p['thresholds'])} | {len(p['steps'])} |"
        )
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"✅ 写入 {report.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
