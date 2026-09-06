#!/usr/bin/env python3
"""影子盲判合规时序监控（无 LLM，纯本地聚合）。

背景（2026-09-06，reports/blindtest-prompt-adjudication-20260905.md 40 日复验）：
包瘦身三刀结果指标无损，但规则15（绝对量能阈值）服从度退化是真实差异
（A/B：首版违规 51 vs 32、重试后未修复 10 vs 5）。裁决结论是上线 + 生产时序监控，
本脚本即该监控：每次运行从 evals/shadow/predictions/*.json 全量重建
logs/shadow-compliance.jsonl 时间序列，并按滚动窗口检查恶化信号。

告警口径（滚动 10 条 ≈ 5 个交易日 × pre/close 双轨）：
- 规则15 重试后未修复 ≥ 3/10：生产基线 1/22≈4.5%，P(X≥3|p=0.045,n=10)≈0.1%，
  触发即显著恶化。
- validation 覆盖率 < 50%：校验层未生效（管线故障），而非合规问题。
- 首版规则15 频率 > 2.5 次/条：A/B c2 臂基线 1.28 次/条的 2 倍；
  该字段 2026-09-07 起才进生产落盘，累计 <10 条含字段记录时此路休眠。

健康时 stdout 为空（cron --no-agent 模式：空输出=静默）；--verbose 打印摘要。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRED_DIR = ROOT / "evals" / "shadow" / "predictions"
SERIES_PATH = ROOT / "logs" / "shadow-compliance.jsonl"

WINDOW = 10
R15_UNRECOVERED_ALERT = 3      # /WINDOW 条
VALIDATION_COVERAGE_FLOOR = 0.5
R15_FIRST_RATE_ALERT = 2.5     # 次/条（c2 基线 1.28 的 2 倍）
R15_FIRST_MIN_RECORDS = 10     # 首版违规告警的最小样本


def _is_r15(item) -> bool:
    return str(item).startswith("规则15")


def collect() -> list[dict]:
    """从生产盲判落盘重建时序（全量重写，幂等）。"""
    rows = []
    for path in sorted(PRED_DIR.glob("*.json")):
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        v = d.get("validation")
        first = (v or {}).get("first_violations")
        rows.append({
            "date": d.get("date") or path.stem.replace("-pre", ""),
            "track": "pre" if path.stem.endswith("-pre") else "close",
            "prompt_version": d.get("prompt_version"),
            "has_validation": v is not None,
            "retried": bool((v or {}).get("retried")),
            "validation_status": (v or {}).get("status"),
            "n_violations": len((v or {}).get("violations") or []),
            "r15_unrecovered": any(_is_r15(x) for x in (v or {}).get("violations") or []),
            "r15_first": (sum(1 for x in first if _is_r15(x)) if first is not None else None),
        })
    rows.sort(key=lambda r: (r["date"], r["track"]))
    return rows


def write_series(rows: list[dict]) -> None:
    SERIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SERIES_PATH.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def check(rows: list[dict]) -> list[str]:
    """返回告警行列表；空列表 = 健康。"""
    alerts = []
    recent = rows[-WINDOW:]
    if not recent:
        return alerts

    covered = [r for r in recent if r["has_validation"]]
    if len(covered) < len(recent) * VALIDATION_COVERAGE_FLOOR:
        alerts.append(
            f"[WARN] validation 覆盖率 {len(covered)}/{len(recent)} "
            f"< {VALIDATION_COVERAGE_FLOOR:.0%}：校验层疑似未生效（管线故障）")

    r15_unrec = sum(1 for r in covered if r["r15_unrecovered"])
    if r15_unrec >= R15_UNRECOVERED_ALERT:
        alerts.append(
            f"[WARN] 规则15 重试后未修复 {r15_unrec}/{len(covered)} 条 "
            f"（生产基线 ≈4.5%）：瘦身包合规退化在生产兑现，"
            f"考虑回滚 BLINDTEST_PACK_SLIM 或加规则15 冗余强调")

    with_first = [r for r in rows if r["r15_first"] is not None]
    if len(with_first) >= R15_FIRST_MIN_RECORDS:
        tail = with_first[-WINDOW:]
        rate = sum(r["r15_first"] for r in tail) / len(tail)
        if rate > R15_FIRST_RATE_ALERT:
            alerts.append(
                f"[WARN] 首版规则15 {rate:.1f} 次/条（近 {len(tail)} 条），"
                f"超 c2 基线 2 倍（1.28 次/条）：规则15 服从度持续劣化")
    return alerts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="影子盲判合规时序监控")
    ap.add_argument("--verbose", action="store_true", help="健康时也打印摘要")
    args = ap.parse_args(argv)

    rows = collect()
    write_series(rows)
    alerts = check(rows)

    if args.verbose or alerts:
        recent = rows[-WINDOW:]
        covered = [r for r in recent if r["has_validation"]]
        r15u = sum(1 for r in covered if r["r15_unrecovered"])
        retry = sum(1 for r in covered if r["retried"])
        print(f"[shadow-compliance] 记录 {len(rows)} 条；近 {len(recent)} 条："
              f"重试 {retry}/{len(covered)}，规则15未修复 {r15u}/{len(covered)}")
        print(f"[series] {SERIES_PATH}")
        for a in alerts:
            print(a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
