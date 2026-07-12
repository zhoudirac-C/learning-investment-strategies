#!/usr/bin/env python3
"""一致性评估脚本：对比 Agent daily_state 与 UP claims。

用法：
    python scripts/evaluate_agent_vs_up.py --date 2026-07-08
    python scripts/evaluate_agent_vs_up.py --week

输出：evals/agent-up-consistency/YYYY-MM-DD.md（或 week-YYYY-MM-DD.md）
"""
from __future__ import annotations

import argparse
import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from qing_investment.paths import repo_root

logger = logging.getLogger(__name__)

DEFAULT_ARCHIVE_DIR = repo_root() / "config" / "stock_monitor" / "daily_state_archive"
DEFAULT_CLAIMS_DIR = repo_root() / "knowledge" / "claims"
DEFAULT_OUTPUT_DIR = repo_root() / "evals"

VIEW_CLAIM_TYPES = {"market-cycle", "operation", "risk"}
SCENARIO_CLAIM_TYPES = {"operation", "market-cycle"}


def _normalize(text: str) -> str:
    """移除标点、空白，保留中英文与数字。"""
    return re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9]", "", str(text)).lower()


def normalize_code(code: str) -> str:
    """统一股票代码格式为 6位数字.SZ/.SH（与 daily_state.normalize_code 保持一致）。"""
    if not code:
        return ""
    text = str(code).strip().upper()
    if text.endswith(".SZ") or text.endswith(".SH"):
        text = text[:-3]
    text = text.replace("SH", "").replace("SZ", "")
    digits = "".join(c for c in text if c.isdigit())
    if len(digits) >= 6:
        digits = digits[-6:]
    market = "SH" if digits.startswith("6") else "SZ"
    return f"{digits}.{market}"


def _bigrams(text: str):
    """生成中文字符二元组集合。"""
    chars = re.findall(r"[\u4e00-\u9fa5]", text)
    return {chars[i] + chars[i + 1] for i in range(len(chars) - 1)}


def _tokens(text: str) -> set[str]:
    """提取 token：英文/数字序列、中文单字、中文二元组。"""
    text = str(text)
    tokens: set[str] = set()
    for m in re.finditer(r"[a-zA-Z0-9]+", text):
        tokens.add(m.group(0).lower())
    chars = re.findall(r"[\u4e00-\u9fa5]", text)
    tokens.update(chars)
    tokens.update(_bigrams(text))
    return tokens


def _term_in_text(term: str, text: str) -> bool:
    """判断一个关键词是否出现在文本中（支持子串与二元组）。"""
    term_norm = _normalize(term)
    text_norm = _normalize(text)
    if not term_norm:
        return False
    if term_norm in text_norm:
        return True
    # 对较长术语，允许部分二元组命中
    if len(term_norm) >= 3:
        term_bigrams = _bigrams(term_norm)
        text_bigrams = _bigrams(text_norm)
        if term_bigrams and any(b in text_bigrams for b in term_bigrams):
            return True
    return False


def _build_claim_text(claim: dict[str, Any]) -> str:
    """把 claim 的关键字段拼成一段文本，用于匹配。"""
    parts = [
        claim.get("topic", ""),
        claim.get("subject", ""),
        claim.get("statement", ""),
        " ".join(str(t) for t in claim.get("tags", [])),
    ]
    for rs in claim.get("related_stocks", []):
        parts.extend([rs.get("name", ""), rs.get("code", ""), rs.get("role", "")])
    return " ".join(str(p) for p in parts)


def load_claims_by_date(claims_dir: Path, date_str: str) -> list[dict[str, Any]]:
    """读取指定日期的所有 claims（按 source_date 过滤）。"""
    claims_dir = Path(claims_dir)
    if not claims_dir.exists():
        logger.warning("Claims dir not found: %s", claims_dir)
        return []

    results: list[dict[str, Any]] = []
    for path in claims_dir.glob("*.yaml"):
        try:
            import yaml

            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception as e:
            logger.warning("Failed to load %s: %s", path, e)
            continue
        claim_list = data if isinstance(data, list) else data.get("claims", [])
        for claim in claim_list:
            if str(claim.get("source_date", "")) == date_str:
                claim["_source_file"] = path.name
                results.append(claim)
    return results


def load_daily_state_archive(archive_dir: Path, date_str: str) -> dict[str, Any] | None:
    """读取指定日期的归档 daily_state。"""
    archive_dir = Path(archive_dir)
    path = archive_dir / f"daily_state_{date_str}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Failed to load daily state archive %s: %s", path, e)
        return None


def compare_directions(
    directions: list[dict[str, Any]], claims: list[dict[str, Any]]
) -> dict[str, Any]:
    """方向优先级与 claims 的重合度。

    对 direction_priority 中的每个方向，检查其关键词是否出现在同日期 claims
    的 topic/subject/tags/related_stocks 中。
    """
    claim_text = " ".join(_build_claim_text(c) for c in claims)
    matched: list[str] = []
    unmatched: list[str] = []

    for item in directions:
        term = str(item.get("direction", "")).strip()
        if not term:
            continue
        if _term_in_text(term, claim_text):
            matched.append(term)
        else:
            unmatched.append(term)

    total = len(matched) + len(unmatched)
    score = len(matched) / total if total else 0.0
    return {
        "score": round(score, 2),
        "total": total,
        "matched": matched,
        "unmatched": unmatched,
    }


def _jaccard_similarity(text_a: str, text_b: str) -> float:
    tokens_a = _tokens(text_a)
    tokens_b = _tokens(text_b)
    if not tokens_a or not tokens_b:
        return 0.0
    inter = len(tokens_a & tokens_b)
    union = len(tokens_a | tokens_b)
    return inter / union if union else 0.0


def compare_assumptions(
    agent_text: str, claims: list[dict[str, Any]]
) -> dict[str, Any]:
    """持仓态度/市场阶段假设与 claims 的最大 Jaccard 重合度。"""
    best_score = 0.0
    best_claim: dict[str, Any] | None = None
    for claim in claims:
        score = _jaccard_similarity(agent_text, _build_claim_text(claim))
        if score > best_score:
            best_score = score
            best_claim = claim

    return {
        "score": round(best_score, 2),
        "best_claim_id": best_claim["id"] if best_claim else None,
        "best_topic": best_claim.get("topic", "") if best_claim else "",
    }


def compare_scenarios(
    narratives: list[str], claims: list[dict[str, Any]]
) -> dict[str, Any]:
    """盘中情景/剧本判断与 claims 的最大 Jaccard 重合度。"""
    agent_text = " ".join(str(n) for n in narratives)
    best_score = 0.0
    best_claim: dict[str, Any] | None = None
    for claim in claims:
        score = _jaccard_similarity(agent_text, _build_claim_text(claim))
        if score > best_score:
            best_score = score
            best_claim = claim

    return {
        "score": round(best_score, 2),
        "best_claim_id": best_claim["id"] if best_claim else None,
        "best_topic": best_claim.get("topic", "") if best_claim else "",
    }


def compare_opportunities(
    opportunities: list[dict[str, Any]], claims: list[dict[str, Any]]
) -> dict[str, Any]:
    """活跃机会与 claims 相关标的的命中率。"""
    hits: list[dict[str, Any]] = []
    misses: list[dict[str, Any]] = []

    for opp in opportunities:
        opp_code = normalize_code(opp.get("code", ""))
        opp_stock = str(opp.get("stock", "")).strip()
        opp_pattern = str(opp.get("pattern", "")).strip()
        matched_claims: list[str] = []

        for claim in claims:
            claim_text = _build_claim_text(claim)
            related = claim.get("related_stocks", [])
            if opp_code:
                if any(
                    normalize_code(rs.get("code", "")) == opp_code for rs in related
                ):
                    matched_claims.append(claim["id"])
                    continue
            if opp_stock:
                if any(opp_stock in str(rs.get("name", "")) for rs in related):
                    matched_claims.append(claim["id"])
                    continue
            if opp_pattern and _term_in_text(opp_pattern, claim_text):
                matched_claims.append(claim["id"])
                continue

        record = {
            "stock": opp_stock,
            "code": opp_code,
            "pattern": opp_pattern,
            "matched_claims": matched_claims,
        }
        if matched_claims:
            hits.append(record)
        else:
            misses.append(record)

    total = len(hits) + len(misses)
    score = len(hits) / total if total else 0.0
    return {
        "score": round(score, 2),
        "total": total,
        "hits": hits,
        "misses": misses,
    }


def evaluate(
    date_str: str,
    *,
    archive_dir: Path | None = None,
    claims_dir: Path | None = None,
) -> dict[str, Any]:
    """评估某一天的 Agent 输出与 UP claims 一致性。"""
    archive_dir = Path(archive_dir or DEFAULT_ARCHIVE_DIR)
    claims_dir = Path(claims_dir or DEFAULT_CLAIMS_DIR)

    state = load_daily_state_archive(archive_dir, date_str)
    claims = load_claims_by_date(claims_dir, date_str)

    if state is None:
        return {
            "date": date_str,
            "direction_overlap": {"score": 0.0, "total": 0, "matched": [], "unmatched": []},
            "assumption_accuracy": {"score": 0.0, "best_claim_id": None, "best_topic": ""},
            "scenario_accuracy": {"score": 0.0, "best_claim_id": None, "best_topic": ""},
            "opportunity_hit_rate": {"score": 0.0, "total": 0, "hits": [], "misses": []},
            "overall_score": 0.0,
            "notes": [f"daily_state archive not found for {date_str}"],
        }

    market_stage = state.get("market_stage", {})
    position_stance = str(state.get("position_stance", ""))
    assumption_text = f"{position_stance} {market_stage.get('phase', '')} {market_stage.get('detail', '')}"

    view_claims = [c for c in claims if c.get("claim_type") in VIEW_CLAIM_TYPES]
    scenario_claims = [c for c in claims if c.get("claim_type") in SCENARIO_CLAIM_TYPES]

    direction_result = compare_directions(state.get("direction_priority", []), claims)
    assumption_result = compare_assumptions(assumption_text, view_claims)
    scenario_result = compare_scenarios(
        [n.get("summary", "") for n in state.get("intraday_narrative", [])],
        scenario_claims,
    )
    opportunity_result = compare_opportunities(
        state.get("active_opportunities", []), claims
    )

    scores = [
        direction_result["score"],
        assumption_result["score"],
        scenario_result["score"],
        opportunity_result["score"],
    ]
    overall = round(sum(scores) / len(scores), 2)

    return {
        "date": date_str,
        "state_file": str(archive_dir / f"daily_state_{date_str}.json"),
        "claim_count": len(claims),
        "direction_overlap": direction_result,
        "assumption_accuracy": assumption_result,
        "scenario_accuracy": scenario_result,
        "opportunity_hit_rate": opportunity_result,
        "overall_score": overall,
        "notes": [],
    }


def render_markdown(reports: list[dict[str, Any]]) -> str:
    """把报告列表渲染成 Markdown。"""
    lines: list[str] = ["# Agent vs UP 一致性评估报告\n"]

    if not reports:
        lines.append("暂无评估数据。\n")
        return "\n".join(lines)

    dates = [r["date"] for r in reports]
    if len(dates) > 1:
        lines.append(f"## 周一致性报告 ({dates[-1]} ~ {dates[0]})\n")
    else:
        lines.append(f"**评估日期**：{dates[0]}\n")

    # 汇总表
    lines.append("## 一致性得分\n")
    lines.append("| 日期 | 方向重合度 | 假设准确率 | 情景准确率 | 机会命中率 | 综合得分 |")
    lines.append("|------|-----------|-----------|-----------|-----------|----------|")
    for r in reports:
        lines.append(
            f"| {r['date']} | "
            f"{_fmt(r['direction_overlap']['score'])} | "
            f"{_fmt(r['assumption_accuracy']['score'])} | "
            f"{_fmt(r['scenario_accuracy']['score'])} | "
            f"{_fmt(r['opportunity_hit_rate']['score'])} | "
            f"{_fmt(r['overall_score'])} |"
        )
    lines.append("")

    if len(reports) > 1:
        avg = round(
            sum(r["overall_score"] for r in reports) / len(reports), 2
        )
        lines.append(f"**周平均综合得分**：{_fmt(avg)}\n")

    # 每日详情
    for r in reports:
        lines.append(f"## {r['date']} 详情\n")

        dir_res = r["direction_overlap"]
        lines.append("### 方向重合度\n")
        lines.append(f"- 命中：{', '.join(dir_res['matched']) or '无'}")
        lines.append(f"- 未命中：{', '.join(dir_res['unmatched']) or '无'}")
        lines.append("")

        ass_res = r["assumption_accuracy"]
        lines.append("### 假设准确率\n")
        if ass_res["best_claim_id"]:
            lines.append(
                f"- 最匹配 claim：`{ass_res['best_claim_id']}` {ass_res['best_topic']}"
            )
        else:
            lines.append("- 未找到匹配 claim")
        lines.append("")

        sce_res = r["scenario_accuracy"]
        lines.append("### 情景准确率\n")
        if sce_res["best_claim_id"]:
            lines.append(
                f"- 最匹配 claim：`{sce_res['best_claim_id']}` {sce_res['best_topic']}"
            )
        else:
            lines.append("- 未找到匹配 claim")
        lines.append("")

        opp_res = r["opportunity_hit_rate"]
        lines.append("### 机会命中率\n")
        if opp_res["hits"]:
            lines.append("- 命中：")
            for h in opp_res["hits"]:
                lines.append(f"  - {h.get('stock', '')}({h.get('code', '')}): {h.get('pattern', '')}")
        else:
            lines.append("- 命中：无")
        if opp_res["misses"]:
            lines.append("- 未命中：")
            for m in opp_res["misses"]:
                lines.append(f"  - {m.get('stock', '')}({m.get('code', '')}): {m.get('pattern', '')}")
        lines.append("")

        if r["notes"]:
            lines.append("### 备注\n")
            for note in r["notes"]:
                lines.append(f"- {note}")
            lines.append("")

    return "\n".join(lines)


def _fmt(score: float) -> str:
    return f"{score:.0%} ({score:.2f})"


def _last_n_weekdays(start: datetime, n: int = 5) -> list[str]:
    """从 start 往前取 n 个工作日（仅按周一到周五过滤，不含节假日判断）。"""
    dates: list[str] = []
    current = start
    while len(dates) < n:
        if current.weekday() < 5:
            dates.append(current.strftime("%Y-%m-%d"))
        current -= timedelta(days=1)
    return dates


def main() -> int:
    parser = argparse.ArgumentParser(description="Agent vs UP 一致性评估")
    parser.add_argument(
        "--date",
        default=datetime.now().strftime("%Y-%m-%d"),
        help="评估日期（默认今天）",
    )
    parser.add_argument(
        "--week",
        action="store_true",
        help="评估最近 5 个交易日并生成周报",
    )
    parser.add_argument("--archive-dir", type=Path, default=None)
    parser.add_argument("--claims-dir", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    archive_dir = args.archive_dir or DEFAULT_ARCHIVE_DIR
    claims_dir = args.claims_dir or DEFAULT_CLAIMS_DIR
    output_dir = Path(args.output_dir or DEFAULT_OUTPUT_DIR)
    report_dir = output_dir / "agent-up-consistency"
    report_dir.mkdir(parents=True, exist_ok=True)

    if args.week:
        anchor = datetime.strptime(args.date, "%Y-%m-%d")
        dates = _last_n_weekdays(anchor, n=5)
        reports = [
            evaluate(d, archive_dir=archive_dir, claims_dir=claims_dir)
            for d in dates
            if load_daily_state_archive(archive_dir, d) is not None
        ]
        if not reports:
            logger.warning("No daily_state archives found for week ending %s", args.date)
            return 1
        md = render_markdown(reports)
        out_path = report_dir / f"week-{args.date}.md"
    else:
        report = evaluate(args.date, archive_dir=archive_dir, claims_dir=claims_dir)
        md = render_markdown([report])
        out_path = report_dir / f"{args.date}.md"

    out_path.write_text(md, encoding="utf-8")
    logger.info("Report written to %s", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
