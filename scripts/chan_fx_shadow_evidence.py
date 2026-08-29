#!/usr/bin/env python
"""B-3 影子证据：递归层内部单元切换到特征序列段后的全量语料差异清单（ADR-012 方案 B 前置观测）。

不改生产代码：通过模块属性替换，把 ``chan_engine.core.engine`` 内部的
``build_l0_segments``（greedy-3bi，课 35/84 f1(a0) 递归构造物）临时换成
``build_fx_segments``（课 67/71/78 特征序列），同一份归一图跑两遍，
逐用例对照 expect 的 zs/bsp 差异。

- 基线列 = 现状 recursion（greedy 内部单元），应复现官方矩阵 21 PASS / 10 FAIL；
- 影子列 = fx 内部单元；两列的 fx/bi/seg 表完全相同（seg 表 M7-6 起本来就是 fx 口径），
  差异只会出现在 zs/bsp（及不参与 diff 的 trend）；
- 判定：基线 PASS → 影子 FAIL 记「回归」；FAIL → PASS 记「修复」；其余「不变」。

用法（仓根）：
    PYTHONPATH=src:third_party/chanpy .venv/bin/python scripts/chan_fx_shadow_evidence.py
"""

from __future__ import annotations

import glob
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "third_party" / "chanpy"))

import chan_engine.core.engine as engine_mod
from chan_engine.core.engine import RecursionEngine
from chan_engine.core.segments_fx import build_fx_segments
from chan_engine.harness.diff import diff_expect
from chan_engine.spec.case_io import load_case

CASES_DIR = REPO / "src/chan_engine/spec/cases"
GOLDEN_DIR = REPO / "src/chan_engine/spec/golden"


def _fmt_elem(table: str, e) -> str:
    if table == "zs":
        return f"zs(zd={e.zd}, zg={e.zg}, {e.start_idx}→{e.end_idx}, L{e.level}, sure={e.sure})"
    if table == "bsp":
        return f"bsp(@{e.idx}, {e.bstype}{'买' if e.dir.value == 'up' else '卖'}, L{e.level}, sure={e.sure})"
    return repr(e)


def _run(engine: RecursionEngine, bars) -> tuple[object, str]:
    """跑引擎，返回 (chart, 错误信息)。"""
    try:
        return engine.run(bars), ""
    except Exception as exc:  # noqa: BLE001 - 证据脚本要崩溃可见而非中断
        return None, f"{type(exc).__name__}: {exc}"


def main() -> None:
    paths = sorted(glob.glob(str(CASES_DIR / "*.yaml"))) + sorted(
        glob.glob(str(GOLDEN_DIR / "*.yaml"))
    )
    rows: list[dict] = []
    for path in paths:
        case = load_case(path)
        base_chart, base_err = _run(RecursionEngine(), case.bars)

        orig = engine_mod.build_l0_segments
        engine_mod.build_l0_segments = build_fx_segments
        try:
            fx_chart, fx_err = _run(RecursionEngine(), case.bars)
        finally:
            engine_mod.build_l0_segments = orig

        row = {"id": case.case_id, "path": path}
        if base_err or fx_err:
            row["verdict"] = "ERROR"
            row["detail"] = f"baseline_err={base_err} fx_err={fx_err}"
            rows.append(row)
            continue

        base_diff = diff_expect(case.expect, base_chart)
        fx_diff = diff_expect(case.expect, fx_chart)
        row["base"] = "PASS" if base_diff.passed else "FAIL"
        row["fx"] = "PASS" if fx_diff.passed else "FAIL"
        if row["base"] == "PASS" and row["fx"] == "FAIL":
            row["verdict"] = "回归"
        elif row["base"] == "FAIL" and row["fx"] == "PASS":
            row["verdict"] = "修复"
        else:
            row["verdict"] = "不变"
        # 影子列的 zs/bsp 明细（仅两列判定不同的用例展开）
        if row["base"] != row["fx"]:
            row["detail"] = fx_diff
        rows.append(row)

    changed = [r for r in rows if r.get("base") != r.get("fx")]
    base_pass = sum(1 for r in rows if r.get("base") == "PASS")
    fx_pass = sum(1 for r in rows if r.get("fx") == "PASS")

    print("# B-3 影子证据：递归层内部单元 → 特征序列段（全量语料）\n")
    print(f"- 用例数：{len(rows)}（cases {len(glob.glob(str(CASES_DIR / '*.yaml')))} + "
          f"golden {len(glob.glob(str(GOLDEN_DIR / '*.yaml')))}）")
    print(f"- 基线（greedy 内部单元）：{base_pass} PASS / {len(rows) - base_pass} FAIL"
          f"（官方矩阵口径 21/10）")
    print(f"- 影子（fx 内部单元）：{fx_pass} PASS / {len(rows) - fx_pass} FAIL")
    print(f"- 判定变化：{len(changed)} 例\n")
    print("| 用例 | 基线 | 影子 | 判定 |")
    print("|---|---|---|---|")
    for r in rows:
        print(f"| {r['id']} | {r.get('base', 'ERROR')} | {r.get('fx', 'ERROR')} | {r['verdict']} |")

    if changed:
        print("\n## 判定变化明细（影子列 zs/bsp 对 expect 的差异）\n")
        for r in changed:
            print(f"### {r['id']}：{r['base']} → {r['fx']}（{r['verdict']}）\n")
            d = r["detail"]
            for t in d.problem_tables:
                print(f"- 表 `{t.table}`：")
                for m in t.mismatches:
                    print(f"  - 字段不一致 key={m.key} {m.field}: expect={m.expected} actual={m.actual}")
                for e in t.missing:
                    print(f"  - 缺（expect 有影子无）: {_fmt_elem(t.table, e)}")
                for e in t.extra:
                    print(f"  - 多（影子有 expect 无）: {_fmt_elem(t.table, e)}")
            print()


if __name__ == "__main__":
    main()
