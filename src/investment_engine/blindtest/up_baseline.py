"""vs UP 对照（诊断信息，不进命中率）：抽样日抽取 UP 当日结论，三方对照。

注意：本模块处理 UP 原文，属"参考对比"路径，与盲测推理路径物理隔离
（UP 内容只进本模块的抽取 prompt，不进 replay 的盲测 prompt）。
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from investment_engine.blindtest.truth import STAGES

UP_DIR = Path("sources/raw/财经")

EXTRACT_PROMPT = """从以下复盘文本中抽取作者当日对市场的结论，严格输出 JSON：
{"stage": "主升|震荡|调整|恐慌（最接近的一个；未明确判断则为 null）",
 "directions": ["作者看好的方向/板块（最多3个，无则空列表）"],
 "mentioned": true/false（文本是否包含对当日市场的实质判断）}
只输出 JSON。

文本：
"""


def pick_sample_days(truth: dict[str, str], n: int = 10, seed: int = 42) -> list[str]:
    """按真值标签分层抽样，确定性（固定 seed）。"""
    by_label: dict[str, list[str]] = {}
    for d, label in sorted(truth.items()):
        by_label.setdefault(label, []).append(d)
    rng = random.Random(seed)
    picked: list[str] = []
    labels = sorted(by_label, key=lambda l: -len(by_label[l]))
    while len(picked) < n and any(by_label.values()):
        for label in labels:
            pool = by_label.get(label) or []
            if pool and len(picked) < n:
                picked.append(pool.pop(rng.randrange(len(pool))))
    return sorted(picked)


def find_up_docs(day: str, up_dir: Path = UP_DIR) -> list[Path]:
    """day='2026-06-15' → 文件名含 '26-06-15' 的文档。"""
    token = day[2:]
    if not up_dir.exists():
        return []
    return sorted(p for p in up_dir.iterdir() if token in p.name)


def parse_up_view(raw: str) -> dict:
    text = raw.strip().strip("`")
    if text.lower().startswith("json"):
        text = text[4:].strip()
    data = json.loads(text)
    stage = data.get("stage")
    if stage is not None and stage not in STAGES:
        stage = None
    return {
        "stage": stage,
        "directions": [str(d) for d in (data.get("directions") or [])][:3],
        "mentioned": bool(data.get("mentioned")),
    }


def extract_up_view(doc_text: str, *, client=None, model: str = "deepseek-chat") -> dict:
    from investment_engine.blindtest.replay import call_deepseek

    raw = call_deepseek(
        [{"role": "user", "content": EXTRACT_PROMPT + doc_text[:8000]}],
        model=model, client=client,
    )
    return parse_up_view(raw)


def build_comparison(results: list[dict], truth: dict[str, str],
                     up_views: dict[str, dict]) -> list[dict]:
    """三方对照：AI vs 真值 vs UP。verdict 四分类。"""
    rows = []
    by_date = {r["date"]: r for r in results}
    for day, up in sorted(up_views.items()):
        r = by_date.get(day)
        label = truth.get(day)
        if r is None or label is None:
            continue
        ai_stage = r["result"].get("market_stage")
        ai_ok = ai_stage == label
        up_ok = up.get("stage") is not None and up["stage"] == label
        if ai_ok and up_ok:
            verdict = "AI对UP对"
        elif ai_ok and not up_ok:
            verdict = "AI对UP错"
        elif not ai_ok and up_ok:
            verdict = "AI错UP对"  # 毕业信心反例
        else:
            verdict = "都错"  # 回炉引擎⓪ 候选
        rows.append({
            "date": day, "truth": label, "ai_stage": ai_stage,
            "up_stage": up.get("stage"), "up_directions": up.get("directions", []),
            "verdict": verdict,
        })
    return rows
