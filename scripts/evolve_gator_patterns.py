#!/usr/bin/env python3
"""gator pattern 演进管线（P1：增量筛选 + embedding 召回 + 报告骨架）。

设计：docs/design/gator-pattern-evolution-design.md
拍板：2026-10-17（D1 批准 / D2 hermes_global / D3 周五 20:00 /
      D4 新主题 ≥2 来源日期 / D5 影子期 2 周 / D6 与 A2 并行）

P1 范围：
  Step 1  增量筛选：扫描 knowledge/claims/claim-*.yaml 中 school==gator 的
          claim，结合 state.json 只取未处理的新增；
  Step 1b 候选召回：每条 claim 与 reasoning-patterns-gator.yaml 的 50 条
          pattern 做 embedding 相似度，取 top-K 候选；
  Step 2  【P1 stub】LLM 五分类（reinforce/refine/contradict/new_theme/
          irrelevant）在 P2 接入，本阶段报告只出候选配对；
  Step 3  报告：reports/gator-pattern-evolution-YYYYMMDD.md。

影子模式：本管线在影子期内【只出报告，不写任何 framework yaml】。

用法：
    .venv/bin/python scripts/evolve_gator_patterns.py --dry-run
    .venv/bin/python scripts/evolve_gator_patterns.py
    .venv/bin/python scripts/evolve_gator_patterns.py --since 2026-10-10
    .venv/bin/python scripts/evolve_gator_patterns.py --window 14d
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CLAIMS_DIR = REPO_ROOT / "knowledge" / "claims"
PATTERNS_YAML = REPO_ROOT / "framework" / "reasoning-patterns-gator.yaml"
STATE_DIR = REPO_ROOT / "infra" / "data" / "gator_pattern_evolution"
STATE_PATH = STATE_DIR / "state.json"
REPORT_DIR = REPO_ROOT / "reports"

TOP_K = 3
# claim 与 pattern 的相似度低于此值时标注「候选均弱匹配」，
# 供 P2 的 LLM 步骤倾向 irrelevant/new_theme 判断（影子期观察用）
WEAK_MATCH_THRESHOLD = 0.45

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── Step 1：增量筛选 ─────────────────────────────────────────────

def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"processed_claim_ids": [], "last_run_at": None}


def save_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def iter_gator_claims() -> list[dict]:
    """扫描全部 claim 文件，返回 school==gator 的 claim（带来源文件）。"""
    out: list[dict] = []
    for path in sorted(CLAIMS_DIR.glob("claim-*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("跳过无法解析的 claim 文件 %s: %s", path.name, e)
            continue
        if isinstance(data, dict):
            claims = data.get("claims", [])
        elif isinstance(data, list):
            claims = data  # 部分文件根节点直接是 claim 列表
        else:
            continue
        for c in claims:
            if isinstance(c, dict) and c.get("school") == "gator":
                c["_claim_file"] = path.name
                out.append(c)
    return out


def filter_new_claims(
    claims: list[dict],
    processed_ids: set[str],
    since: date | None,
) -> list[dict]:
    out = []
    for c in claims:
        cid = c.get("id")
        if not cid or cid in processed_ids:
            continue
        if since is not None:
            sd = str(c.get("source_date", ""))
            try:
                if date.fromisoformat(sd) < since:
                    continue
            except ValueError:
                continue
        out.append(c)
    return out


# ── Step 1b：embedding 候选召回 ──────────────────────────────────

def load_patterns() -> list[dict]:
    data = yaml.safe_load(PATTERNS_YAML.read_text(encoding="utf-8"))
    return [p for p in (data or {}).get("patterns", []) if isinstance(p, dict)]


def get_embedding_model():
    """优先 ONNX bge-small-zh（与 Agent 路由同一模型），失败降级 hash。"""
    try:
        from qing_investment.agent.tools.embedding_utils import OnnxEmbeddingModel

        return OnnxEmbeddingModel(), "onnx-bge-small-zh"
    except Exception as e:
        logger.warning("ONNX embedding 不可用，降级 hash embedding: %s", e)
        from qing_investment.agent.tools.embedding_utils import (
            FallbackEmbeddingModel,
        )

        return FallbackEmbeddingModel(), "fallback-hash"


def pattern_text(p: dict) -> str:
    """与 nodes.py::_ensure_pattern_embeddings 同一口径：name + description。"""
    return f"{p.get('name', '')}。{p.get('description', '')}"


def claim_text(c: dict) -> str:
    return f"{c.get('topic', '')}。{c.get('statement', '')}"


def recall_candidates(
    new_claims: list[dict], patterns: list[dict], top_k: int = TOP_K
) -> list[dict]:
    """为每条 claim 召回 top-K 候选 pattern，返回带 candidates 的 claim 列表。"""
    model, model_name = get_embedding_model()
    logger.info("embedding 模型: %s", model_name)

    p_texts = [pattern_text(p) for p in patterns]
    p_emb = model.encode(p_texts)
    p_emb = np.atleast_2d(np.asarray(p_emb, dtype=np.float32))

    c_texts = [claim_text(c) for c in new_claims]
    c_emb = model.encode(c_texts)
    c_emb = np.atleast_2d(np.asarray(c_emb, dtype=np.float32))

    # 余弦相似度（ONNX 输出已 L2 归一化；hash fallback 也已归一化，
    # 但保险起见再归一化一次）
    def normalize(m: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(m, axis=1, keepdims=True)
        return m / np.clip(norms, a_min=1e-9, a_max=None)

    sim = normalize(c_emb) @ normalize(p_emb).T  # (n_claims, n_patterns)

    results = []
    for i, c in enumerate(new_claims):
        top_idx = np.argsort(sim[i])[::-1][:top_k]
        cands = [
            {
                "pattern_id": patterns[j].get("pattern_id"),
                "name": patterns[j].get("name"),
                "chapter": patterns[j].get("chapter"),
                "similarity": round(float(sim[i][j]), 4),
            }
            for j in top_idx
        ]
        weak = all(c["similarity"] < WEAK_MATCH_THRESHOLD for c in cands)
        results.append({**c, "_candidates": cands, "_weak_match": weak})
    return results


# ── Step 3：报告 ─────────────────────────────────────────────────

def render_report(
    enriched: list[dict],
    window_desc: str,
    total_gator: int,
    model_note: str,
) -> str:
    today = date.today().isoformat()
    lines = [
        f"# gator pattern 演进周报（{today}）",
        "",
        "> 阶段：P1 影子模式（Step 2 LLM 五分类未接入，仅候选召回配对）",
        f"> 窗口：{window_desc} ｜ gator claims 总数：{total_gator} ｜ "
        f"本周新增：{len(enriched)}",
        "> ⚠️ 影子期约束：本报告不改任何 framework yaml，所有归类需人工复核。",
        "",
        "## 一、本周新增 claim × 候选 pattern 配对",
        "",
    ]
    if not enriched:
        lines.append("本周无新增 gator claim，管线空转（零 LLM 调用）。")
        return "\n".join(lines) + "\n"

    for c in enriched:
        lines.append(f"### {c.get('id')}（{c.get('source_date')}）")
        lines.append(f"- **topic**: {c.get('topic', '')}")
        lines.append(f"- **statement**: {c.get('statement', '')}")
        quote = str(c.get("evidence_quote", "")).replace("\n", " ")
        if len(quote) > 120:
            quote = quote[:120] + "…"
        lines.append(f"- **evidence_quote**: {quote}")
        if c["_weak_match"]:
            lines.append(
                f"- ⚠️ **候选均弱匹配**（最高相似度 < {WEAK_MATCH_THRESHOLD}），"
                "P2 应倾向 new_theme / irrelevant 判断"
            )
        lines.append("- **候选 pattern（top-3）**:")
        for cand in c["_candidates"]:
            lines.append(
                f"  {cand['similarity']:.3f} 第{cand['chapter']}章 "
                f"{cand['name']}（`{cand['pattern_id']}`）"
            )
        lines.append("")

    lines += [
        "## 二、人工复核区（影子期填写）",
        "",
        "| claim_id | 正确归类（reinforce/refine/contradict/new_theme/irrelevant） | 正确 pattern | 备注 |",
        "|---|---|---|---|",
    ]
    for c in enriched:
        lines.append(f"| {c.get('id')} |  |  |  |")
    lines += [
        "",
        f"---",
        f"*embedding: {model_note} ｜ 生成: scripts/evolve_gator_patterns.py*",
    ]
    return "\n".join(lines) + "\n"


# ── main ─────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--window", default="7d", help="窗口，如 7d / 14d（默认 7d）")
    ap.add_argument("--since", help="显式起始日期 YYYY-MM-DD（优先于 --window）")
    ap.add_argument("--dry-run", action="store_true", help="不更新 state.json")
    ap.add_argument("--top-k", type=int, default=TOP_K)
    return ap.parse_args()


def main() -> int:
    args = parse_args()

    if args.since:
        since = date.fromisoformat(args.since)
        window_desc = f"自 {since}（显式指定）"
    else:
        days = int(args.window.rstrip("d"))
        since = date.today() - timedelta(days=days)
        window_desc = f"近 {days} 天（自 {since}）"

    state = load_state()
    processed_ids = set(state.get("processed_claim_ids", []))

    all_gator = iter_gator_claims()
    logger.info("gator claims 总数: %d，已处理: %d", len(all_gator), len(processed_ids))

    new_claims = filter_new_claims(all_gator, processed_ids, since)
    logger.info("窗口内新增: %d", len(new_claims))

    patterns = load_patterns()
    logger.info("gator patterns: %d", len(patterns))

    if new_claims:
        enriched = recall_candidates(new_claims, patterns, top_k=args.top_k)
        model_note = "onnx-bge-small-zh（或 fallback-hash，见日志）"
    else:
        enriched = []
        model_note = "未调用（零新增）"

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / f"gator-pattern-evolution-{date.today():%Y%m%d}.md"
    report_path.write_text(
        render_report(enriched, window_desc, len(all_gator), model_note),
        encoding="utf-8",
    )
    logger.info("报告已写: %s", report_path)

    if not args.dry_run:
        processed_ids.update(c["id"] for c in new_claims)
        state["processed_claim_ids"] = sorted(processed_ids)
        state["last_run_at"] = datetime.now().isoformat(timespec="seconds")
        save_state(state)
        logger.info("state 已更新: %s（累计处理 %d 条）", STATE_PATH, len(processed_ids))
    else:
        logger.info("dry-run：state 未更新")

    # 控制台摘要（供 cron 投递）
    print(f"\n=== gator pattern 演进周报 {date.today()} ===")
    print(f"窗口: {window_desc} ｜ 新增 claim: {len(new_claims)} ｜ 报告: {report_path}")
    for c in enriched:
        top = c["_candidates"][0]
        flag = " ⚠️弱匹配" if c["_weak_match"] else ""
        print(f"- {c['id']}: {c.get('topic', '')[:30]} → 第{top['chapter']}章{top['name']} ({top['similarity']:.3f}){flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
