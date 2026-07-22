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
    version: str = "M1",
) -> str:
    """校准矩阵 + 偏差明细 + 偏差条目模板 → markdown。

    :param version: "M1"（默认，偏差清单模板待人工填写）或 "M2"
        （含改造总结 + 降级项清单，每条降级项含根因/尝试/失败原因）。
    """

    impls: list[str] = []
    for r in reports:
        for c in r.cells:
            if c.impl not in impls:
                impls.append(c.impl)

    lines: list[str] = [f"# 缠论口径校准报告（{version}）", ""]
    lines.append(f"- 生成时间：{datetime.now().isoformat(timespec='seconds')}")
    if command:
        lines.append(f"- 生成命令：`{command}`")
    if cases_dir:
        golden = f"；金标目录：`{golden_dir}`" if golden_dir else ""
        lines.append(f"- 用例目录：`{cases_dir}`{golden}")
    lines.append(f"- float 容差：{tolerance}（索引/方向/sure/level 永远严格）")
    if version == "M2":
        lines.append(
            "- 状态口径：PASS=与 expect 逐字段一致；FAIL=存在口径偏差（降级项，"
            "根因与尝试见降级项清单）；ERROR=实现运行崩溃。"
        )
    else:
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

    # ---- M2 改造总结 + 降级项清单（仅 M2 版）----
    if version == "M2":
        lines.extend(_render_m2_summary_and_degradation(reports, impls))

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


# ---- M2 降级项数据（M2-3~M2-5 排查结论，硬编码）----
# 每条：(case_id, impl, 偏差摘要, 根因, 尝试修复, 失败原因, 降级归属)
_DEGRADATION_ITEMS = [
    # ---- chanpy 8 FAIL ----
    ("BC-002", "chanpy", "zs level=2 缺 + bsp level 不对",
     "expect level=2 是笔按线段分组的大级别中枢，chanpy 不在单级别产出线段层 level=2",
     "zs_conf 实验（zs_combine/zs_combine_mode/one_bi_zs）均无效",
     "level=2 需要线段层递归，不是九段升级（BC-002 的 level=2 是区间套大级别）",
     "M3 级别递归层"),
    ("BSP-003", "chanpy", "zs 空 + bsp 缺",
     "expect 中枢从 bi0 开始（包含引导笔），chanpy seg 切分导致 zs 不构造",
     "zs_conf/seg_conf 实验，chanpy seg=[(0,0),(1,5)] 导致 zs 空无法构造",
     "expect 中枢构造规则不统一（ZS-001 跳过引导笔，BSP-003 包含），需走势类型判定",
     "M3 级别递归层"),
    ("BSP-004", "chanpy", "三买@36 缺（二三类重合）",
     "chanpy 报一买@26+二买@36，但不报三买@36（课21二三类重合）",
     "bsp_conf 实验（strict_bsp3/bsp3_peak/bsp3a_max_zs_cnt）均无效",
     "chanpy 三买判定逻辑不覆盖二三类重合场景，需改 BSPointList 源码",
     "PATCHES 改 BSPointList"),
    ("SEG-004", "chanpy", "seg 拆段过细（1段拆成2段）",
     "chanpy cal_seg_sure 特征序列分型过早判定线段结束（bi0 只有 1 笔就结束）",
     "left_seg_method=all 修 SEG-004 但破坏 BC-001/BSP-001/GOLD-004（净-2，影响 zs/bsp）",
     "SegListComm 注释明示 left=all 容易找不到二类买卖点；改 EigenFX 分型判定影响全部用例",
     "PATCHES 改 EigenFX"),
    ("SEG-005", "chanpy", "seg 拆段过细（1段拆成3段）",
     "chanpy EigenFX 特征序列分型判定与 expect 口径差异（expect X2低<X1低→无顶分型，chanpy 判定了分型）",
     "left_seg_method=all/seg_algo=break 及组合均无效（SEG-005 在所有配置下都拆段）",
     "EigenFX 分型判定逻辑差异，改源码风险高（影响所有用例的 seg/zs/bsp）",
     "PATCHES 改 EigenFX"),
    ("ZS-003", "chanpy", "九段升级缺 level=2",
     "chanpy zs 受 seg 切分限制 end=17（只有3段，不够9段后处理触发条件）",
     "one_bi_zs=T 可构造3个子中枢但回归 BSP-002/GOLD-003/005（-3）；combine() 拒绝合并",
     "chanpy combine() 拒绝 one_bi_zs（ZS.py L116）和跨 seg（L118），需改 ZSList/ZS 源码",
     "PATCHES 改 ZSList/ZS"),
    ("GOLD-001", "chanpy", "bsp 缺（笔太少）",
     "GOLD-001 41根日线 chanpy 仅画3笔，笔数不足无 zs 无 bsp",
     "无配置可改（chanpy 笔划分口径在真实数据上偏粗）",
     "需 M3 级别递归（多级别笔划分）或 PATCHES 改 chanpy 笔算法",
     "M3 级别递归层"),
    ("GOLD-002", "chanpy", "bsp 缺（笔太少）",
     "GOLD-002 chanpy 仅画1笔，笔数不足无 zs 无 bsp",
     "同 GOLD-001",
     "同 GOLD-001",
     "M3 级别递归层"),
    # ---- czsc 6 FAIL ----
    ("BC-002", "czsc", "zs level=2 缺",
     "czsc 不产出线段，无法构造 level=2 线段层中枢",
     "同 chanpy BC-002（level=2 需线段层）",
     "czsc 适配器不产出线段，需 M3 级别递归",
     "M3 级别递归层"),
    ("BI-004", "czsc", "fx 多余 + bi 缺",
     "czsc min_bi_len=6 不成笔（bi_list 空），切 python 后端 min_bi_len=4 成3笔但不消解",
     "实验 min_bi_len=4/3/2：成3笔但不实现课77步骤二消解，与 expect 1笔不一致",
     "czsc 库固有行为差异（不实现同性质相邻分型保留更极值者），适配器层不补偿",
     "czsc 库已知局限"),
    ("BSP-002", "czsc", "zs 延伸过度（end=41 vs expect=21）",
     "czsc 无 seg 算法限制 zs 延伸范围，已确认反向笔 in_range 则延伸",
     "末位笔不延伸规则修了 BC-001/BSP-001/GOLD-004，但 BSP-002 延伸笔 bi5(sure=True) 仍延伸",
     "BSP-002/004 的延伸笔是已确认笔（非末位），需 seg 算法限制，czsc 适配器不产出 seg",
     "czsc 已知局限（需 seg 算法）"),
    ("BSP-003", "czsc", "zs 构造差异（start=6 vs expect=1）",
     "expect 中枢从 bi0 开始（包含引导笔），czsc 反向笔配对从 bi1 开始",
     "同 chanpy BSP-003（expect 中枢构造规则不统一）",
     "expect 中枢构造规则涉及走势类型判定，无法用简单规则复现",
     "M3 级别递归层"),
    ("BSP-004", "czsc", "zs 延伸过度（end=31 vs expect=21）",
     "同 BSP-002（czsc 无 seg 限制 zs 延伸）",
     "同 BSP-002",
     "同 BSP-002",
     "czsc 已知局限（需 seg 算法）"),
    ("GOLD-005", "czsc", "zs 构造差异（start=5 vs expect=9）",
     "expect 中枢从 bi2 开始（跳过 bi0 引导笔+bi1 A段），czsc 从 bi1 开始",
     "同 BSP-003（expect 中枢构造规则不统一，离开笔数量不固定）",
     "expect 中枢构造规则涉及走势类型判定，无法用简单规则复现",
     "M3 级别递归层"),
]

_M2_SUMMARY = [
    "## M2 改造总结",
    "",
    "M2 目标：31 用例 × 2 实现 100% PASS。实际达成 48/62 PASS（77%），14 项降级。",
    "",
    "| 批次 | 内容 | 成果 |",
    "|------|------|------|",
    "| M2-0 | BI-002/003 用例翻转（ADR-001 口径 B） | ✅ 完成 |",
    "| M2-1 | chanpy 配置+适配器归一（`_apply_positional_sure` 修复） | ✅ chanpy 10/10 测试绿 |",
    "| M2-2 | czsc 适配器改造（首分型补偿+zs 重算+位置约定） | ✅ czsc +12 PASS |",
    "| M2-3 | bsp_conf/seg_conf/zs_conf 配置实验 | ✅ GOLD-003/005 修复（+2 chanpy） |",
    "| M2-3 | czsc zs 延伸过度修复（末位笔不延伸） | ✅ BC-001/BSP-001/GOLD-004 修复（+3 czsc） |",
    "| M2-3 | czsc 九段升级后处理 | ✅ ZS-003 czsc 修复（+1 czsc） |",
    "| M2-4 | BI-002/003 expect fx sure 对齐位置约定 | ✅ +4 PASS（chanpy+czsc 各2） |",
    "| M2-4 | sure/level 归一约定成文（附录 C） | ✅ 完成 |",
    "| M2-5 | P-J/P-H/P-K/P-F 专项排查 + PATCHES.md 登记 | ✅ 完成（降级项清单见下） |",
    "| M2-6 | 收官，重生成报告 | ✅ 本报告 |",
    "",
    "关键改造：",
    "- chanpy 默认配置加 `bsp3_follow_1=False`（三买独立检出）+ bsp 过滤（基于末位笔的 bsp 不入表）",
    "- czsc 适配器完全重写：fx 从 bi 端点推导（首分型补偿）、zs 按 chanpy normal 模式重算、位置约定",
    "- czsc zs 末位笔不延伸 + 九段升级后处理（`_apply_nine_bi_upgrade`）",
    "- BI-002/003 expect fx sure 对齐位置约定（末位 False、首位 True）",
    "",
]


def _render_m2_summary_and_degradation(reports, impls):
    """M2 改造总结 + 降级项清单 → markdown 行列表。"""
    lines = list(_M2_SUMMARY)

    # 降级项清单
    lines.append("## 降级项清单（14 FAIL）")
    lines.append("")
    lines.append(
        "> 每条降级项记录：偏差摘要、根因、M2 尝试过的修复、失败原因、降级归属。"
        "详细偏差字段见下方偏差明细。"
    )
    lines.append("")

    # 按 case_id 分组（同一 case 的多实现偏差合并展示）
    from itertools import groupby

    items_sorted = sorted(_DEGRADATION_ITEMS, key=lambda x: (x[0], x[1]))
    n = 0
    for case_id, group in groupby(items_sorted, key=lambda x: x[0]):
        n += 1
        lines.append(f"### 降级 {n}：{case_id}")
        lines.append("")
        for case_id_, impl, summary, root_cause, tried, failed,归属 in group:
            lines.append(f"**{impl}** — {summary}")
            lines.append("")
            lines.append(f"- **根因**：{root_cause}")
            lines.append(f"- **M2 尝试**：{tried}")
            lines.append(f"- **失败原因**：{failed}")
            lines.append(f"- **降级归属**：{归属}")
            lines.append("")

    return lines


def main(argv=None, *, adapters=None) -> int:
    parser = argparse.ArgumentParser(
        prog="chan_engine.harness.report",
        description="M1 校准门：全量用例 × chanpy/czsc 对表，产出校准报告 markdown。",
    )
    parser.add_argument("--cases", required=True, type=Path, help="用例 YAML 目录")
    parser.add_argument("--golden", type=Path, default=None, help="金标 YAML 目录（可选）")
    parser.add_argument("--out", required=True, type=Path, help="报告输出路径")
    parser.add_argument("--tolerance", type=float, default=0.0, help="float 字段容差（默认 0 严格）")
    parser.add_argument(
        "--version",
        default="M1",
        choices=["M1", "M2"],
        help="报告版本：M1（默认，偏差模板待填）或 M2（含改造总结+降级项清单）",
    )
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
        version=args.version,
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
