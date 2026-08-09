"""宽松三桶分桶（阈值定义出处：spec 2026-08-08-m3-pattern-validation-design.md）。"""
from __future__ import annotations

# 主指标 = 各模式 steps 最终产出物对应的指标，决定桶归属
PRIMARY_METRIC = {
    "sentiment_cycle": "stage",
    "mainline_identification": "direction",
    "sector_rotation": "direction",
    "upstream_cycle": "direction",
    "technical_timing": "stock",
    "ai_industry_chain": "stock",
}
# 毕业线：阶段 70%/方向 60% 出自主计划 10.4；标的 55% 由本模块定义（spec 已录）
GRADUATION_LINE = {"stage": 0.70, "direction": 0.60, "stock": 0.55}
FALSIFY_LINE = 0.50   # 掷硬币水平以下才证伪
MIN_SAMPLES = 20

BUCKET_PASS = "达标"
BUCKET_WATCH = "待观察"
BUCKET_FAIL = "证伪"
BUCKET_UNUSED = "unused"


def bucket_one(metric_kind: str, rate: float | None, n: int) -> str:
    if rate is None or n < MIN_SAMPLES:
        return BUCKET_WATCH
    if rate < FALSIFY_LINE:
        return BUCKET_FAIL
    if rate >= GRADUATION_LINE[metric_kind]:
        return BUCKET_PASS
    return BUCKET_WATCH


def bucketize(metrics: dict, all_pattern_ids) -> dict:
    """{pattern_id: {bucket, primary_metric?}}；无指标模式标 unused。"""
    out = {}
    for pid in all_pattern_ids:
        m = metrics.get(pid)
        if m is None:
            out[pid] = {"bucket": BUCKET_UNUSED, "note": "m1 未使用"}
            continue
        kind = PRIMARY_METRIC.get(pid)
        if kind is None:
            out[pid] = {"bucket": BUCKET_WATCH, "note": "无主指标映射，仅记录指标"}
            continue
        out[pid] = {"bucket": bucket_one(kind, m[kind]["rate"], m[kind]["n"]),
                    "primary_metric": kind}
    return out
