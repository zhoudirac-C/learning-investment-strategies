"""把 docs/标的深度研究 的 md 报告解析为 chain dict（过 schema 校验）。

解析规则见 v2.1 计划 Task 4。散文形式的 value_share/barrier/landscape
不在源文档表格里，迁移后如实为 None，由 5.5 节的维护分工补齐。
"""
from __future__ import annotations

import re

STAR_RE = re.compile(r"⭐")
SECTION_RE = re.compile(r"^##\s+[一二三四五六七八九十]+、\s*(.+?)\s*$")
SUBSECTION_RE = re.compile(r"^###\s+\d+(?:\.\d+)?\s+(.+?)\s*$")
ROW_RE = re.compile(r"^\|(.+)\|\s*$")
BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
THESIS_RE = re.compile(r"一句话核心逻辑[*\s：:]*(.+?)\s*$")
SKIP_WORDS = ("总结", "风险", "操作手册", "博主", "视角")


def elasticity_from_stars(text: str) -> str:
    n = len(STAR_RE.findall(text or ""))
    if n >= 4:
        return "core"
    if n == 3:
        return "elastic"
    return "concept"


def _clean(cell: str) -> str:
    cell = BOLD_RE.sub(r"\1", cell)
    return cell.strip().strip("*").strip()


def _split_row(line: str) -> list[str]:
    return [_clean(c) for c in line.strip().strip("|").split("|")]


def _is_separator_row(cells: list[str]) -> bool:
    return all(set(c) <= set("-: ") for c in cells)


def _find_col(header: list[str], *keywords: str) -> int | None:
    for i, h in enumerate(header):
        if any(k in h for k in keywords):
            return i
    return None


def _cert_from(text: str) -> str | None:
    if "已供货" in text:
        return "已供货"
    if "测试" in text:
        return "测试中"
    return None


def parse_research_md(
    text: str,
    *,
    chain_id: str,
    name: str,
    verified: str,
) -> dict:
    """解析深度研究 md，返回过 schema 的 chain dict。"""
    thesis = ""
    for ln in text.splitlines():
        m = THESIS_RE.search(ln)
        if m:
            thesis = _clean(m.group(1))
            break

    segments: list[dict] = []
    mappings: list[dict] = []
    current_seg_id: str | None = None
    skip_section = False
    seen_codes: set[str] = set()

    def new_segment(seg_name: str) -> None:
        nonlocal current_seg_id
        seg_id = f"seg-{len(segments) + 1:02d}"
        segments.append({
            "id": seg_id, "name": seg_name, "value_share": None, "barrier": None,
            "landscape": None, "growth": None, "status": None, "last_verified": None,
        })
        current_seg_id = seg_id

    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]

        m = SECTION_RE.match(line)
        if m:
            title = m.group(1).strip()
            skip_section = any(w in title for w in SKIP_WORDS)
            current_seg_id = None if skip_section else current_seg_id
            if not skip_section:
                new_segment(title)
            i += 1
            continue

        m = SUBSECTION_RE.match(line)
        if m and not skip_section:
            title = m.group(1).strip()
            if not any(w in title for w in SKIP_WORDS):
                new_segment(title)
            i += 1
            continue

        if ROW_RE.match(line) and not skip_section and current_seg_id:
            header = _split_row(line)
            code_col = _find_col(header, "代码")
            if code_col is not None:
                name_col = _find_col(header, "标的", "股票", "名称")
                rel_col = _find_col(header, "关系", "核心逻辑", "竞争地位", "逻辑")
                cert_col = _find_col(header, "认证", "供货状态")
                ela_col = _find_col(header, "弹性")
                i += 1
                while i < len(lines) and ROW_RE.match(lines[i]):
                    cells = _split_row(lines[i])
                    i += 1
                    if _is_separator_row(cells) or len(cells) <= code_col:
                        continue
                    code = cells[code_col]
                    if not re.fullmatch(r"\d{6}", code) or code in seen_codes:
                        continue
                    seen_codes.add(code)

                    def cell(col: int | None) -> str:
                        return cells[col] if col is not None and col < len(cells) else ""

                    mappings.append({
                        "code": code,
                        "name": cell(name_col),
                        "segment": current_seg_id,
                        "relation": cell(rel_col),
                        "cert_status": _cert_from(cell(cert_col)),
                        "order_evidence": None,
                        "elasticity": elasticity_from_stars(cell(ela_col)),
                        "elasticity_reason": None,
                        "last_verified": verified,
                    })
                continue
        i += 1

    chain = {
        "chain_id": chain_id,
        "name": name,
        "thesis": thesis,
        "last_verified": verified,
        "segments": segments,
        "mappings": mappings,
    }

    from investment_engine.industry_chain.schema import validate_chain

    return validate_chain(chain)
