#!/usr/bin/env python3
"""gator pattern 演进管线（P2：增量筛选 + embedding 召回 + LLM 五分类 + 报告）。

设计：docs/design/gator-pattern-evolution-design.md
拍板：2026-10-17（D1 批准 / D2 hermes_global / D3 周五 20:00 /
      D4 新主题 ≥2 来源日期 / D5 影子期 2 周 / D6 与 A2 并行）
P2 上线：2026-10-22（用户拍板「做P2」）

P2 范围：
  Step 1  增量筛选：扫描 knowledge/claims/claim-*.yaml 中 school==gator 的
          claim，结合 state.json 只取未处理的新增；
  Step 1b 候选召回：每条 claim 与 reasoning-patterns-gator.yaml 的 pattern
          做 embedding 相似度，取 top-K 候选；
  Step 2  LLM 五分类：reinforce/refine/contradict/new_theme/irrelevant。
          保真约束：LLM 只分类不裁决，contradict/refine 必须引用 pattern
          原文冲突点；模型跟随 hermes_global（discover 同通道）。
          分类结果幂等存 state.json.classifications，重跑不重复调 LLM；
  Step 3  报告：reports/gator-pattern-evolution-YYYYMMDD.md（五分类分节）。

影子模式：本管线在影子期内【只出报告，不写任何 framework yaml】；
new_theme ≥2 来源日期仅在报告中提示「可进 proposals」，不自动写文件。

用法：
    .venv/bin/python scripts/evolve_gator_patterns.py --dry-run
    .venv/bin/python scripts/evolve_gator_patterns.py
    .venv/bin/python scripts/evolve_gator_patterns.py --since 2026-10-10
    .venv/bin/python scripts/evolve_gator_patterns.py --reclassify-since 2026-10-16
        # 测试/重跑：忽略 processed 过滤重走窗口内 gator claims，
        # 但已分类的 claim 直接读 state（不重复调 LLM）
    .venv/bin/python scripts/evolve_gator_patterns.py --no-llm   # 退回 P1 行为
"""

from __future__ import annotations

import argparse
import json
import logging
import re
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


# ── Step 2：LLM 五分类 ──────────────────────────────────────────

CATEGORIES = ["reinforce", "refine", "contradict", "new_theme", "irrelevant"]

CLASSIFY_PROMPT = """你是鳄鱼派投资方法论的规则归类器。给定一条新提取的 UP 观点（claim）和与其语义最接近的候选规则章节（pattern），判断该 claim 与规则库的关系，五选一：

- reinforce：claim 是既有 pattern 的新例证/新日期确认（规则内容不变）
- refine：claim 修正了既有 pattern（阈值调整/限定条件变化/适用范围变化）
- contradict：claim 与既有 pattern 矛盾（学派内部观点漂移）
- new_theme：claim 是规则库未覆盖的新方法论主题
- irrelevant：claim 与规则层无关（行情描述/数据流水/情绪吐槽）

保真约束（必须遵守）：
1. 你只能分类，不得改写 claim 或 pattern 的原文；
2. 判 refine / contradict 时，conflict_quote 必须引用 pattern 侧的具体条款原文；
3. 候选 pattern 全部弱匹配（已标注）时应倾向 new_theme 或 irrelevant；
4. 拿不准时 category 仍从五类中选最接近的，并在 rationale 中说明不确定点。

【claim】
id: {claim_id}
topic: {topic}
statement: {statement}
evidence_quote: {evidence_quote}

【候选 pattern】
{candidates_block}
{weak_note}

输出严格 JSON（不要输出任何其他内容）：
{{"category": "五类之一", "pattern_id": "候选 pattern_id 或 null", "rationale": "≤80字", "conflict_quote": "refine/contradict 时必填，否则空字符串"}}"""


def _pattern_summary(p: dict) -> str:
    """pattern 侧摘要：名称 + 描述 + 前 3 条阈值（保真引用原文）。"""
    lines = [f"pattern_id: {p.get('pattern_id')}", f"名称: {p.get('name')}"]
    desc = str(p.get("description", "")).strip()
    if desc:
        lines.append(f"描述: {desc[:200]}")
    for t in (p.get("thresholds") or [])[:3]:
        lines.append(f"条款: {t}")
    return "\n".join(lines)


def classify_claims(
    enriched: list[dict],
    patterns: list[dict],
    existing: dict,
    llm,
) -> list[dict]:
    """对每条 claim 做 LLM 五分类。已有 state 记录的跳过（幂等）。

    返回带 _classification 的 claim 列表；分类失败的标 parse_error 进人审。
    """
    by_id = {p.get("pattern_id"): p for p in patterns}
    results = []
    n_llm = 0
    for c in enriched:
        cid = c.get("id")
        if cid in existing:
            c["_classification"] = existing[cid]
            c["_classification"]["_from_state"] = True
            results.append(c)
            continue

        cands_block_parts = []
        for cand in c["_candidates"]:
            p = by_id.get(cand["pattern_id"])
            if p:
                cands_block_parts.append(
                    f"--- 候选（相似度 {cand['similarity']:.3f}）---\n{_pattern_summary(p)}"
                )
        weak_note = (
            "\n注意：以上候选均为弱匹配（相似度 < "
            f"{WEAK_MATCH_THRESHOLD}），请倾向 new_theme 或 irrelevant。"
            if c["_weak_match"] else ""
        )
        prompt = CLASSIFY_PROMPT.format(
            claim_id=cid,
            topic=c.get("topic", ""),
            statement=c.get("statement", ""),
            evidence_quote=str(c.get("evidence_quote", ""))[:400],
            candidates_block="\n\n".join(cands_block_parts) or "（无候选）",
            weak_note=weak_note,
        )
        try:
            resp = llm.invoke(prompt)
            text = resp.content if hasattr(resp, "content") else str(resp)
            m = re.search(r"\{.*\}", text, re.S)
            parsed = json.loads(m.group(0)) if m else {}
            cat = parsed.get("category", "")
            if cat not in CATEGORIES:
                raise ValueError(f"非法 category: {cat}")
            c["_classification"] = {
                "category": cat,
                "pattern_id": parsed.get("pattern_id"),
                "rationale": str(parsed.get("rationale", ""))[:200],
                "conflict_quote": str(parsed.get("conflict_quote", ""))[:300],
                "classified_at": datetime.now().isoformat(timespec="seconds"),
            }
            n_llm += 1
        except Exception as e:
            logger.warning("分类失败 %s: %s", cid, e)
            c["_classification"] = {
                "category": "parse_error",
                "pattern_id": None,
                "rationale": f"LLM 输出解析失败: {e}",
                "conflict_quote": "",
                "classified_at": datetime.now().isoformat(timespec="seconds"),
            }
        results.append(c)
        logger.info(
            "分类 %s → %s%s", cid, c["_classification"]["category"],
            "" if cid not in existing else "（state 缓存）",
        )
    logger.info("Step 2 完成：LLM 新分类 %d 条，state 命中 %d 条",
                n_llm, len(enriched) - n_llm)
    return results


# ── Step 3：报告 ─────────────────────────────────────────────────

def render_report(
    enriched: list[dict],
    window_desc: str,
    total_gator: int,
    model_note: str,
    llm_note: str = "未接入",
) -> str:
    today = date.today().isoformat()
    classified = [c for c in enriched if "_classification" in c]
    lines = [
        f"# gator pattern 演进周报（{today}）",
        "",
        f"> 阶段：P2 影子模式（LLM 五分类已接入，{llm_note}）",
        f"> 窗口：{window_desc} ｜ gator claims 总数：{total_gator} ｜ "
        f"本周新增：{len(enriched)}",
        "> ⚠️ 影子期约束：本报告不改任何 framework yaml，所有归类需人工复核；"
        "contradict/refine 不自动裁决。",
        "",
    ]
    if not enriched:
        lines.append("本周无新增 gator claim，管线空转（零 LLM 调用）。")
        return "\n".join(lines) + "\n"

    # ── 汇总表 ──
    if classified:
        from collections import Counter
        cnt = Counter(c["_classification"]["category"] for c in classified)
        lines += [
            "## 一、五分类汇总",
            "",
            "| 类别 | 数量 | 含义 |",
            "|---|---|---|",
            f"| reinforce | {cnt.get('reinforce', 0)} | 新例证强化既有规则 |",
            f"| refine | {cnt.get('refine', 0)} | 阈值/条件修正（需人审） |",
            f"| contradict | {cnt.get('contradict', 0)} | 学派内漂移（需人审，不自动裁决） |",
            f"| new_theme | {cnt.get('new_theme', 0)} | 规则库未覆盖新主题 |",
            f"| irrelevant | {cnt.get('irrelevant', 0)} | 与规则层无关 |",
            f"| parse_error | {cnt.get('parse_error', 0)} | LLM 解析失败（需人审） |",
            "",
        ]

    def claim_block(c: dict) -> list[str]:
        cls = c.get("_classification", {})
        b = [
            f"### {c.get('id')}（{c.get('source_date')}）",
            f"- **topic**: {c.get('topic', '')}",
            f"- **statement**: {c.get('statement', '')}",
        ]
        if cls:
            b.append(
                f"- **分类**: `{cls.get('category')}` → "
                f"`{cls.get('pattern_id') or '无'}`"
            )
            b.append(f"- **理由**: {cls.get('rationale', '')}")
            if cls.get("conflict_quote"):
                b.append(f"- **冲突条款原文**: {cls.get('conflict_quote')}")
            if cls.get("_from_state"):
                b.append("- （state 缓存，非本次 LLM 调用）")
        b.append("- **候选 pattern（top-3）**:")
        for cand in c["_candidates"]:
            b.append(
                f"  {cand['similarity']:.3f} 第{cand['chapter']}章 "
                f"{cand['name']}（`{cand['pattern_id']}`）"
            )
        b.append("")
        return b

    def section(title: str, cat: str, note: str = "") -> None:
        group = [c for c in classified if c["_classification"]["category"] == cat]
        if not group:
            return
        lines.append(f"## {title}（{len(group)} 条）{note}")
        lines.append("")
        for c in group:
            lines.extend(claim_block(c))

    # ── 分节：风险项在前 ──
    section("二、⚠️ contradict（学派内漂移，需人审）", "contradict")
    section("三、⚠️ refine（阈值/条件修正，需人审）", "refine")

    # new_theme：按 topic 聚合，≥2 来源日期提示可进 proposals
    new_themes = [c for c in classified if c["_classification"]["category"] == "new_theme"]
    if new_themes:
        lines.append(f"## 四、🆕 new_theme（{len(new_themes)} 条）")
        lines.append("")
        from collections import defaultdict
        by_topic = defaultdict(list)
        for c in new_themes:
            by_topic[c.get("topic", "（无 topic）")].append(c)
        lines.append("### 主题聚合（D4：≥2 个来源日期 → 可进 framework/proposals/）")
        lines.append("")
        for topic, cs in sorted(by_topic.items(), key=lambda kv: -len(kv[1])):
            dates = sorted({str(c.get("source_date", "")) for c in cs})
            flag = " ✅ **可进 proposals**" if len(dates) >= 2 else ""
            lines.append(f"- **{topic}**（{len(cs)} 条，{len(dates)} 个日期：{'、'.join(dates)}）{flag}")
        lines.append("")
        for c in new_themes:
            lines.extend(claim_block(c))

    section("五、reinforce（新例证强化）", "reinforce")
    section("六、irrelevant（与规则层无关）", "irrelevant")
    section("七、❌ parse_error（LLM 解析失败）", "parse_error")

    # 未分类（--no-llm 模式）走 P1 展示
    unclassified = [c for c in enriched if "_classification" not in c]
    if unclassified:
        lines.append(f"## 附、未分类配对（--no-llm 模式，{len(unclassified)} 条）")
        lines.append("")
        for c in unclassified:
            lines.extend(claim_block(c))

    lines += [
        "## 人工复核区（影子期填写）",
        "",
        "| claim_id | LLM 归类 | 人工认定（reinforce/refine/contradict/new_theme/irrelevant） | 备注 |",
        "|---|---|---|---|",
    ]
    for c in enriched:
        llm_cat = c.get("_classification", {}).get("category", "未分类")
        lines.append(f"| {c.get('id')} | {llm_cat} |  |  |")
    lines += [
        "",
        "---",
        f"*embedding: {model_note} ｜ LLM: {llm_note} ｜ 生成: scripts/evolve_gator_patterns.py*",
    ]
    return "\n".join(lines) + "\n"


# ── main ─────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--window", default="7d", help="窗口，如 7d / 14d（默认 7d）")
    ap.add_argument("--since", help="显式起始日期 YYYY-MM-DD（优先于 --window）")
    ap.add_argument("--dry-run", action="store_true", help="不更新 state.json")
    ap.add_argument("--top-k", type=int, default=TOP_K)
    ap.add_argument("--no-llm", action="store_true", help="跳过 Step 2（退回 P1 行为）")
    ap.add_argument(
        "--reclassify-since",
        help="测试/重跑：忽略 processed 过滤，重走该日期起全部 gator claims"
        "（已分类的读 state 缓存，不重复调 LLM）",
    )
    return ap.parse_args()


def main() -> int:
    args = parse_args()

    if args.reclassify_since:
        since = date.fromisoformat(args.reclassify_since)
        window_desc = f"自 {since}（reclassify 模式）"
    elif args.since:
        since = date.fromisoformat(args.since)
        window_desc = f"自 {since}（显式指定）"
    else:
        days = int(args.window.rstrip("d"))
        since = date.today() - timedelta(days=days)
        window_desc = f"近 {days} 天（自 {since}）"

    state = load_state()
    processed_ids = set(state.get("processed_claim_ids", []))
    classifications = state.get("classifications", {})

    all_gator = iter_gator_claims()
    logger.info("gator claims 总数: %d，已处理: %d", len(all_gator), len(processed_ids))

    if args.reclassify_since:
        # reclassify 模式：忽略 processed 过滤（但 LLM 分类仍读 state 幂等）
        new_claims = filter_new_claims(all_gator, set(), since)
    else:
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

    # ── Step 2：LLM 五分类 ──
    llm_note = "--no-llm（未调用）"
    if enriched and not args.no_llm:
        try:
            from qing_investment.agent.tools.llm_client import (
                SENSENOVA_FALLBACK_MODELS,
                get_llm_client_with_fallback,
            )

            # 与 discover_claim_relations 同一通道（2026-10-22 拍板主通道）
            llm = get_llm_client_with_fallback(
                provider="hermes_global",
                fallback_models=[
                    "openrouter:z-ai/glm-5.3-flash",
                    "workbuddy:glm-5.3-flash",
                    *SENSENOVA_FALLBACK_MODELS,
                ],
            )
            llm_note = f"hermes_global（fallback: openrouter/workbuddy/sensenova）"
            enriched = classify_claims(enriched, patterns, classifications, llm)
        except Exception as e:
            logger.error("LLM 通道初始化失败，退回 P1 行为: %s", e)
            llm_note = f"初始化失败（{e}），退回 P1"

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / f"gator-pattern-evolution-{date.today():%Y%m%d}.md"
    report_path.write_text(
        render_report(enriched, window_desc, len(all_gator), model_note, llm_note),
        encoding="utf-8",
    )
    logger.info("报告已写: %s", report_path)

    if not args.dry_run:
        processed_ids.update(c["id"] for c in new_claims)
        state["processed_claim_ids"] = sorted(processed_ids)
        # 分类结果幂等入库（即使 dry-run 外失败也不丢已完成的分类）
        for c in enriched:
            cls = c.get("_classification")
            if cls and not cls.get("_from_state"):
                cls.pop("_from_state", None)
                classifications[c["id"]] = cls
        state["classifications"] = classifications
        state["last_run_at"] = datetime.now().isoformat(timespec="seconds")
        save_state(state)
        logger.info("state 已更新: %s（累计处理 %d 条，已分类 %d 条）",
                    STATE_PATH, len(processed_ids), len(classifications))
    else:
        logger.info("dry-run：state 未更新")

    # 控制台摘要（供 cron 投递）
    print(f"\n=== gator pattern 演进周报 {date.today()} ===")
    print(f"窗口: {window_desc} ｜ 新增 claim: {len(new_claims)} ｜ 报告: {report_path}")
    for c in enriched:
        top = c["_candidates"][0]
        flag = " ⚠️弱匹配" if c["_weak_match"] else ""
        cls = c.get("_classification", {}).get("category", "")
        cls_note = f" [{cls}]" if cls else ""
        print(
            f"- {c['id']}{cls_note}: {c.get('topic', '')[:30]} → "
            f"第{top['chapter']}章{top['name']} ({top['similarity']:.3f}){flag}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
