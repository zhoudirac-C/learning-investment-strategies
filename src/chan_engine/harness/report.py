"""校准矩阵与 markdown 报告生成（M1 harness）。

CLI（实施计划 Task 9 Step 1）::

    PYTHONPATH=src:third_party/chanpy .venv/bin/python -m chan_engine.harness.report \
        --cases src/chan_engine/spec/cases \
        --golden src/chan_engine/spec/golden \
        --out docs/design/chanlun-calibration-report.md

退出码：0 正常；1 用例/目录问题；2 适配器不可用（如 chan.py vendor 不在
sys.path、czsc 未安装）——均给清晰错误提示，不打栈 trace。

单元格状态：PASS 与 expect 逐字段一致；FAIL 存在口径偏差（M1 的预期产出）；
ERROR 实现运行崩溃（记 cell 后继续，不让整批中断）。
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from chan_engine.harness.diff import (
    TABLE_KEYS,
    ChartDiff,
    diff_expect,
    expect_to_chart,
)
from chan_engine.spec.case_io import Case, CaseValidationError, load_case
from chan_engine.spec.model import Direction

PASS = "PASS"
FAIL = "FAIL"
ERROR = "ERROR"

_PLACEHOLDER = "【待 Task 9 人工填写】"
# 矩阵里实现名 → 偏差条目里的中文标签
_IMPL_LABEL = {"chanpy": "chan.py"}

_CHANPY_HINT = (
    "chanpy 适配器需要 third_party/chanpy 在 sys.path 中，请这样运行：\n"
    "  PYTHONPATH=src:third_party/chanpy .venv/bin/python -m chan_engine.harness.report ..."
)
_CZSC_HINT = "czsc 未安装或不可导入，请在 .venv 中安装（pip install czsc）。"


class _AdapterUnavailable(Exception):
    """适配器模块不可导入/初始化失败（环境/用法问题，清晰报错退出码 2）。"""


@dataclass
class CellResult:
    """一个 case × 一个 impl 的单元格结果。"""

    impl: str
    status: str  # PASS / FAIL / ERROR
    diff: ChartDiff | None = None
    error: str = ""


@dataclass
class CaseReport:
    case_id: str
    claim_refs: list[str]
    cells: list[CellResult]
    source: str = "case"  # "case" / "golden"


def run_case(case: Case, adapters, *, tolerance: float = 0.0) -> CaseReport:
    """对一条用例跑全部适配器并 diff。实现崩溃记 ERROR 并继续下一适配器。"""

    cells: list[CellResult] = []
    for adapter in adapters:
        try:
            chart = adapter.run(case.bars)
            d = diff_expect(case.expect, chart, tolerance=tolerance)
            cells.append(
                CellResult(adapter.name, PASS if d.passed else FAIL, diff=d)
            )
        except Exception as e:  # FAIL 是预期产出，崩溃只是这一个 cell 的事
            cells.append(
                CellResult(adapter.name, ERROR, error=f"{type(e).__name__}: {e}")
            )
    return CaseReport(case.case_id, list(case.claim_refs), cells)


def render_report(
    reports: list[CaseReport],
    *,
    command: str = "",
    cases_dir: str = "",
    golden_dir: str = "",
    tolerance: float = 0.0,
) -> str:
    """校准矩阵 + 偏差明细 + 偏差条目模板 → markdown。"""

    impls: list[str] = []
    for r in reports:
        for c in r.cells:
            if c.impl not in impls:
                impls.append(c.impl)

    lines: list[str] = ["# 缠论口径校准报告（M1）", ""]
    lines.append(f"- 生成时间：{datetime.now().isoformat(timespec='seconds')}")
    if command:
        lines.append(f"- 生成命令：`{command}`")
    if cases_dir:
        golden = f"；金标目录：`{golden_dir}`" if golden_dir else ""
        lines.append(f"- 用例目录：`{cases_dir}`{golden}")
    lines.append(f"- float 容差：{tolerance}（索引/方向/sure/level 永远严格）")
    lines.append(
        "- 状态口径：PASS=与 expect 逐字段一致；FAIL=存在口径偏差（M1 预期产出）；"
        "ERROR=实现运行崩溃。"
    )
    lines.append("")

    # ---- 校准矩阵 ----
    lines.append("## 校准矩阵")
    lines.append("")
    header = "| 用例 | 来源 | " + " | ".join(impls) + " |"
    lines.append(header)
    lines.append("| --- | --- | " + " | ".join("---" for _ in impls) + " |")
    for r in reports:
        by_impl = {c.impl: c for c in r.cells}
        row = [r.case_id, r.source]
        row += [by_impl[i].status if i in by_impl else "—" for i in impls]
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    # ---- 统计 ----
    lines.append("## 统计")
    lines.append("")
    lines.append("| 实现 | PASS | FAIL | ERROR | 合计 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for impl in impls:
        cells = [c for r in reports for c in r.cells if c.impl == impl]
        counts = {s: sum(1 for c in cells if c.status == s) for s in (PASS, FAIL, ERROR)}
        lines.append(
            f"| {impl} | {counts[PASS]} | {counts[FAIL]} | {counts[ERROR]} | {len(cells)} |"
        )
    lines.append("")

    # ---- 偏差明细 ----
    lines.append("## 偏差明细")
    lines.append("")
    problems = [(r, c) for r in reports for c in r.cells if c.status != PASS]
    if not problems:
        lines.append("（全部 PASS，无偏差）")
        lines.append("")
    for r, c in problems:
        lines.extend(_render_cell_detail(r.case_id, c))

    # ---- 口径偏差清单（模板）----
    lines.append("## 口径偏差清单（模板）")
    lines.append("")
    lines.append(
        "> 每条偏差的【原文依据 / 仲裁结论 / M2 改造点】由 Task 9 人工评审填写。"
    )
    lines.append("")
    n = 0
    for r in reports:
        bad_cells = [c for c in r.cells if c.status != PASS]
        if not bad_cells:
            continue
        n += 1
        lines.append(f"### 偏差 {n}：{r.case_id}")
        lines.append("")
        lines.append(f"- 规则源 claim：{', '.join(r.claim_refs)}")
        for c in r.cells:
            label = _IMPL_LABEL.get(c.impl, c.impl)
            lines.append(f"- {label} 行为：{_cell_summary(c)}")
        lines.append(f"- 原文依据：{_PLACEHOLDER}")
        lines.append(f"- 仲裁结论：{_PLACEHOLDER}")
        lines.append(f"- M2 改造点：{_PLACEHOLDER}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main(argv=None, *, adapters=None) -> int:
    parser = argparse.ArgumentParser(
        prog="chan_engine.harness.report",
        description="M1 校准门：全量用例 × chanpy/czsc 对表，产出校准报告 markdown。",
    )
    parser.add_argument("--cases", required=True, type=Path, help="用例 YAML 目录")
    parser.add_argument("--golden", type=Path, default=None, help="金标 YAML 目录（可选）")
    parser.add_argument("--out", required=True, type=Path, help="报告输出路径")
    parser.add_argument("--tolerance", type=float, default=0.0, help="float 字段容差（默认 0 严格）")
    args = parser.parse_args(argv)

    dirs: list[tuple[Path, str]] = [(args.cases, "case")]
    if args.golden is not None:
        dirs.append((args.golden, "golden"))
    for d, _ in dirs:
        if not d.is_dir():
            print(f"错误：目录不存在：{d}", file=sys.stderr)
            return 1

    if adapters is None:
        try:
            adapters = _default_adapters()
        except _AdapterUnavailable as e:
            print(f"错误：{e}", file=sys.stderr)
            return 2

    reports: list[CaseReport] = []
    for d, source in dirs:
        for path in sorted(d.glob("*.yaml")):
            try:
                case = load_case(path)
                expect_to_chart(case.expect)  # 提前校验 expect，用例错误当场报
            except (CaseValidationError, ValueError) as e:
                print(f"错误：用例加载失败 {path}：{e}", file=sys.stderr)
                return 1
            rep = run_case(case, adapters, tolerance=args.tolerance)
            rep.source = source
            reports.append(rep)

    command = (
        f"python -m chan_engine.harness.report --cases {args.cases} "
        + (f"--golden {args.golden} " if args.golden is not None else "")
        + f"--out {args.out}"
    )
    md = render_report(
        reports,
        command=command,
        cases_dir=str(args.cases),
        golden_dir=str(args.golden) if args.golden is not None else "",
        tolerance=args.tolerance,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(md, encoding="utf-8")

    print(f"报告已写出：{args.out}（{len(reports)} 条用例）")
    for impl in dict.fromkeys(c.impl for r in reports for c in r.cells):
        cells = [c for r in reports for c in r.cells if c.impl == impl]
        counts = {s: sum(1 for c in cells if c.status == s) for s in (PASS, FAIL, ERROR)}
        print(
            f"  {impl}: PASS {counts[PASS]} / FAIL {counts[FAIL]} / ERROR {counts[ERROR]}"
        )
    return 0


def _default_adapters():
    """懒加载真实适配器（chanpy 需要 third_party/chanpy 在 sys.path）。"""

    chanpy_cls = _load_adapter(
        "chan_engine.harness.adapter_chanpy", "ChanPyAdapter", _CHANPY_HINT
    )
    czsc_cls = _load_adapter(
        "chan_engine.harness.adapter_czsc", "CzscAdapter", _CZSC_HINT
    )
    adapters = []
    for cls, hint in ((chanpy_cls, _CHANPY_HINT), (czsc_cls, _CZSC_HINT)):
        try:
            adapters.append(cls())
        except Exception as e:
            raise _AdapterUnavailable(
                f"{cls.__name__} 初始化失败：{type(e).__name__}: {e}\n{hint}"
            ) from e
    return adapters


def _load_adapter(module: str, cls: str, hint: str):
    """导入适配器模块并取类；ImportError → _AdapterUnavailable（清晰提示）。"""

    try:
        mod = importlib.import_module(module)
    except ImportError as e:
        raise _AdapterUnavailable(f"无法导入 {module}（{e}）。\n{hint}") from e
    return getattr(mod, cls)


def _render_cell_detail(case_id: str, cell: CellResult) -> list[str]:
    lines = [f"### {case_id} × {cell.impl} — {cell.status}", ""]
    if cell.status == ERROR:
        lines.append(f"- 运行异常：`{cell.error}`")
        lines.append("")
        return lines
    assert cell.diff is not None
    for t in cell.diff.problem_tables:
        lines.append(f"**{t.table} 表**")
        lines.append("")
        for e in t.missing:
            lines.append(f"- 缺（expect 有，实现无）：`({_fmt_elem(e)})`")
        for e in t.extra:
            lines.append(f"- 多（expect 无，实现有）：`({_fmt_elem(e)})`")
        for m in t.mismatches:
            lines.append(
                f"- 主键 `({_fmt_key(t.table, m.key)})` 字段 `{m.field}`："
                f"期望 `{m.expected}`，实际 `{m.actual}`"
            )
        lines.append("")
    return lines


def _cell_summary(cell: CellResult) -> str:
    if cell.status == PASS:
        return "PASS（与 expect 一致）"
    if cell.status == ERROR:
        return f"ERROR：{cell.error}"
    assert cell.diff is not None
    parts = []
    for t in cell.diff.problem_tables:
        detail = []
        if t.missing:
            detail.append(f"缺 {len(t.missing)} 条")
        if t.extra:
            detail.append(f"多 {len(t.extra)} 条")
        if t.mismatches:
            detail.append(f"字段不一致 {len(t.mismatches)} 处")
        parts.append(f"{t.table} 表：" + "、".join(detail))
    return "FAIL — " + "；".join(parts)


def _fmt_elem(elem) -> str:
    """归一元素 → 紧凑串（不含 source），如 start_idx=0, end_idx=5, dir=up。"""

    parts = []
    for f in dataclasses.fields(elem):
        if f.name == "source":
            continue
        parts.append(f"{f.name}={_norm(getattr(elem, f.name))}")
    return ", ".join(parts)


def _fmt_key(table: str, key: tuple) -> str:
    return ", ".join(f"{name}={val}" for name, val in zip(TABLE_KEYS[table], key))


def _norm(v):
    return v.value if isinstance(v, Direction) else v


if __name__ == "__main__":
    sys.exit(main())
