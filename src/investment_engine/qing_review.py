"""qing-agent 复盘臂市场评分（v2.2 §16.3 对比臂）。

数据源：config/stock_monitor/daily_review_summary.json（qing-agent 每日 17 点复盘的
结构化落盘，2026-06-11 起按日累积）。该臂 = UP 锚定 + 收盘后信息（非盲）重管线；
shadow 臂 = 盲判轻管线。两臂用同一份机械真值（blindtest/truth.py）评分。

阶段归一化（先验规则，不拟合真值）：
- 回暖/修复/震荡/结构 家族 → 震荡（UP 语境中"回暖"是冰点后的修复反弹，
  不满足机械主升口径 r20≥+4% 且 pos20≥0.6 的典型状态）
- 退潮/调整/磨底 家族 → 调整
- 标签含"恐慌" → 恐慌（恐慌只作加强语气出现，取强信号）
- "未判断"/未映射 → 剔除（如实计入 excluded）
注意：qing 词汇体系在本窗口无法表达"主升"，这本身是对比发现之一。
"""
from __future__ import annotations

import json
from pathlib import Path

SUMMARY_PATH = Path("config/stock_monitor/daily_review_summary.json")

# 显式映射表：复盘 stage 原文 → 四枚举。None = 剔除。
STAGE_MAP: dict[str, str | None] = {
    "回暖期": "震荡",
    "回暖期（虹吸型）": "震荡",
    "回暖期（冰点修复）": "震荡",
    "回暖期（弱修复/冰点后修复初期）": "震荡",
    "修复期": "震荡",
    "结构性修复期": "震荡",
    "震荡修复期": "震荡",
    "震荡偏弱": "震荡",
    "高位震荡": "震荡",
    "高位震荡期": "震荡",
    "高位震荡尾期→调整预警": "震荡",  # 取当前状态，不取预警
    "结构性轮动（周期主导）": "震荡",
    "退潮期": "调整",
    "退潮调整期": "调整",
    "退潮末期/底部区域": "调整",
    "退潮期/底部构筑中": "调整",
    "调整期": "调整",
    "调整期（退潮）": "调整",  # 8-21：调整期带退潮定性，归调整桶（同退潮期口径）
    "调整末期/震荡修复": "调整",
    "调整末期，假修复": "调整",
    "磨底期": "调整",
    "磨底期（情绪已回暖，指数二次回踩）": "调整",
    "冰点期": "调整",  # 8-19：情绪冰点但无恐慌杀跌，归调整桶（同磨底期口径）
    "调整期/恐慌杀跌": "恐慌",
    "调整期/恐慌冰点": "恐慌",
    "未判断": None,
}


def load_summaries(path: Path = SUMMARY_PATH) -> dict[str, dict]:
    """读复盘 summary，返回 {date: market 区块}（跳过无 market 的日期）。"""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    out = {}
    for day, rec in raw.items():
        market = (rec or {}).get("market") or {}
        out[day] = market
    return out


def normalize_stage(label: str | None) -> str | None:
    """自由文本 stage → 四枚举；剔除返回 None；未映射抛 KeyError（强制评审）。"""
    if label is None:
        return None
    if label not in STAGE_MAP:
        raise KeyError(f"未映射的 stage 标签: {label!r}（请评审后加入 STAGE_MAP）")
    return STAGE_MAP[label]


def score_vs_truth(summaries: dict[str, dict], truth: dict[str, str]) -> dict:
    """qing 臂 stage 一致率。只评有真值且有映射的日期。"""
    hits = samples = 0
    by_label: dict[str, dict] = {}
    excluded: list[str] = []
    details: list[dict] = []
    for day in sorted(summaries):
        label = truth.get(day)
        if label is None:
            continue
        raw_stage = summaries[day].get("stage")
        norm = normalize_stage(raw_stage)
        if norm is None:
            excluded.append(day)
            continue
        hit = norm == label
        samples += 1
        hits += int(hit)
        bucket = by_label.setdefault(label, {"samples": 0, "hits": 0})
        bucket["samples"] += 1
        bucket["hits"] += int(hit)
        details.append({"date": day, "raw": raw_stage, "norm": norm,
                        "truth": label, "hit": hit})
    for b in by_label.values():
        b["accuracy"] = b["hits"] / b["samples"] if b["samples"] else None
    return {"samples": samples, "hits": hits,
            "accuracy": hits / samples if samples else None,
            "by_label": by_label, "excluded": excluded, "details": details}


def shadow_stage_records(pred_dir: Path) -> dict[str, dict]:
    """shadow 臂 {date: {stage, hit}}（仅正式复盘记录，跳过 -pre 与 error）。"""
    out = {}
    for p in sorted(Path(pred_dir).glob("*.json")):
        if p.stem.endswith("-pre"):
            continue
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        result = rec.get("result") or {}
        if not result.get("market_stage"):
            continue
        out[rec.get("date", p.stem)] = {"stage": result["market_stage"],
                                        "hit": rec.get("stage_hit")}
    return out
