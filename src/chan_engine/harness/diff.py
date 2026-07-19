"""diff 引擎（M1 harness）：expect 归一 + 逐字段对表。

比对语义
--------
- 只比对 expect 中实际出现的表（expect 子键可选；缺表 = 该用例不断言此表，
  ``TableDiff.status="skipped"``, ``skip_reason="no-expect"``）；
- ``actual.na_fields`` 中的表整体跳过（实现不支持，如 czsc 的 seg/bsp，
  ``skip_reason="na"``）；
- 表内序列按主键集合对齐（各表主键见 ``TABLE_KEYS``，ZS 用 (start_idx,end_idx)，
  FX 用 (idx,type)）：expect 有 actual 无 → ``missing``（缺）；
  actual 有 expect 无 → ``extra``（多）；主键命中（同主键多条按组内顺序配对）
  → 逐字段比对（``_TABLE_FIELDS``）；
- 容差 ``tolerance`` 只作用于 float 字段（zs 的 zd/zg），默认 0 = 严格相等；
  其余字段（索引/方向/sure/level）永远严格。

比对结果是机读结构（``ChartDiff``/``TableDiff``/``FieldMismatch``），
report.py 据此渲染 markdown。
"""

from __future__ import annotations

import dataclasses
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable

from chan_engine.spec.model import (
    CHART_TABLES,
    Bi,
    BSPoint,
    Direction,
    FX,
    NormalizedChart,
    Segment,
    ZhongShu,
)

_ELEMENT_CLS = {"fx": FX, "bi": Bi, "seg": Segment, "zs": ZhongShu, "bsp": BSPoint}

# 各表对齐主键（Task 6 Step 2：bi/seg/bsp 按端点+方向，FX 按 (idx,type)，
# ZS 按 (start_idx,end_idx)——区间值 zd/zg 作为比对字段而非主键）
TABLE_KEYS: dict[str, tuple[str, ...]] = {
    "fx": ("idx", "type"),
    "bi": ("start_idx", "end_idx", "dir"),
    "seg": ("start_bi", "end_bi", "dir"),
    "zs": ("start_idx", "end_idx"),
    "bsp": ("idx", "bstype", "dir"),
}

# 主键命中后逐字段比对的字段
_TABLE_FIELDS: dict[str, tuple[str, ...]] = {
    "fx": ("sure",),
    "bi": ("sure",),
    "seg": ("sure",),
    "zs": ("zd", "zg", "level", "sure"),
    "bsp": ("level", "sure"),
}

# 容差作用的 float 字段（其余字段永远严格）
_FLOAT_FIELDS = frozenset({"zd", "zg"})

# 值为 Direction 的字段名（expect dict 里是 "up"/"down" 字符串）
_DIR_FIELDS = ("dir", "type")


@dataclass
class FieldMismatch:
    """主键命中后某一比对字段不一致。``key``/``expected``/``actual`` 已机读化
    （Direction → 其 value 字符串）。"""

    table: str
    key: tuple
    field: str
    expected: Any
    actual: Any


@dataclass
class TableDiff:
    """单表比对结果。status: ok / diff / skipped。"""

    table: str
    status: str
    skip_reason: str = ""  # "na"（实现不支持）/ "no-expect"（用例不断言）
    mismatches: list[FieldMismatch] = field(default_factory=list)
    missing: list[Any] = field(default_factory=list)  # expect 有、实际无（归一元素）
    extra: list[Any] = field(default_factory=list)  # 实际有、expect 无


@dataclass
class ChartDiff:
    """五表比对总结果。passed = 所有表均非 diff（ok 或 skipped）。"""

    tables: list[TableDiff]
    tolerance: float = 0.0

    @property
    def passed(self) -> bool:
        return all(t.status != "diff" for t in self.tables)

    @property
    def problem_tables(self) -> list[TableDiff]:
        return [t for t in self.tables if t.status == "diff"]


def expect_to_chart(expect: dict[str, Any]) -> NormalizedChart:
    """用例 expect 原始 dict → NormalizedChart（dir/type 字符串 → Direction）。

    非法输入（未知表/未知字段/非列表/缺必填字段/方向值非法）抛 ``ValueError``，
    供用例作者在报告运行期得到可读错误而非栈 trace。
    """

    if not isinstance(expect, dict):
        raise ValueError("expect 必须是 mapping")
    unknown = sorted(set(expect) - set(CHART_TABLES))
    if unknown:
        raise ValueError(f"expect 含未知表 {unknown}，仅允许 {list(CHART_TABLES)}")
    chart = NormalizedChart()
    for table, entries in expect.items():
        setattr(chart, table, _build_elements(table, entries))
    return chart


def diff_expect(
    expect: dict[str, Any], actual: NormalizedChart, *, tolerance: float = 0.0
) -> ChartDiff:
    """expect 原始 dict 与实现输出对表（只比对 expect 断言的表）。"""

    expected = expect_to_chart(expect)
    return diff_charts(expected, actual, tables=set(expect), tolerance=tolerance)


def diff_charts(
    expected: NormalizedChart,
    actual: NormalizedChart,
    *,
    tables: Iterable[str] | None = None,
    tolerance: float = 0.0,
) -> ChartDiff:
    """两份归一输出逐表对表。

    :param tables: 要比对的表名集合；None = CHART_TABLES 全部。
    :param tolerance: float 字段容差，默认 0（严格）。
    """

    asserted = set(CHART_TABLES) if tables is None else set(tables)
    bad = sorted(asserted - set(CHART_TABLES))
    if bad:
        raise ValueError(f"未知表 {bad}，仅允许 {list(CHART_TABLES)}")
    results: list[TableDiff] = []
    for table in CHART_TABLES:
        if table not in asserted:
            results.append(TableDiff(table, "skipped", skip_reason="no-expect"))
        elif table in actual.na_fields:
            results.append(TableDiff(table, "skipped", skip_reason="na"))
        else:
            results.append(
                diff_table(
                    table,
                    getattr(expected, table),
                    getattr(actual, table),
                    tolerance=tolerance,
                )
            )
    return ChartDiff(tables=results, tolerance=tolerance)


def diff_table(
    table: str, expected: list, actual: list, *, tolerance: float = 0.0
) -> TableDiff:
    """单表主键集合对齐 + 命中后逐字段比对。"""

    e_groups: dict[tuple, list] = defaultdict(list)
    a_groups: dict[tuple, list] = defaultdict(list)
    for e in expected:
        e_groups[_key_of(table, e)].append(e)
    for a in actual:
        a_groups[_key_of(table, a)].append(a)

    td = TableDiff(table=table, status="ok")
    for key in sorted(set(e_groups) | set(a_groups)):
        es, as_ = e_groups.get(key, []), a_groups.get(key, [])
        n = min(len(es), len(as_))
        for e, a in zip(es[:n], as_[:n]):
            for fname in _TABLE_FIELDS[table]:
                ev, av = getattr(e, fname), getattr(a, fname)
                if _fields_differ(fname, ev, av, tolerance):
                    td.mismatches.append(
                        FieldMismatch(table, key, fname, _norm(ev), _norm(av))
                    )
        td.missing.extend(es[n:])
        td.extra.extend(as_[n:])
    if td.mismatches or td.missing or td.extra:
        td.status = "diff"
    return td


def _build_elements(table: str, entries: Any) -> list:
    if entries is None:  # YAML 里 "bi:" 无值 → None，按空列表处理
        return []
    if not isinstance(entries, list):
        raise ValueError(f"expect.{table} 必须是列表，得到 {type(entries).__name__}")
    cls = _ELEMENT_CLS[table]
    allowed = {f.name for f in dataclasses.fields(cls)} - {"source"}
    items = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"expect.{table}[{i}] 必须是 mapping")
        bad = sorted(set(entry) - allowed)
        if bad:
            raise ValueError(
                f"expect.{table}[{i}] 含未知字段 {bad}，允许 {sorted(allowed)}"
            )
        kwargs = dict(entry)
        for k in _DIR_FIELDS:
            if k in kwargs:
                kwargs[k] = _to_direction(kwargs[k], table, i)
        try:
            items.append(cls(**kwargs))
        except (TypeError, ValueError) as e:
            raise ValueError(f"expect.{table}[{i}] 非法：{e}") from e
    return items


def _to_direction(value: Any, table: str, i: int) -> Direction:
    if isinstance(value, Direction):
        return value
    try:
        return Direction(str(value).strip().lower())
    except ValueError:
        raise ValueError(
            f"expect.{table}[{i}] 方向值非法: {value!r}（取 up/down）"
        ) from None


def _norm(v: Any) -> Any:
    """机读化：Direction → value 字符串，其余原样。"""

    return v.value if isinstance(v, Direction) else v


def _key_of(table: str, elem: Any) -> tuple:
    return tuple(_norm(getattr(elem, f)) for f in TABLE_KEYS[table])


def _fields_differ(fname: str, ev: Any, av: Any, tolerance: float) -> bool:
    if fname in _FLOAT_FIELDS:
        try:
            return abs(float(ev) - float(av)) > tolerance
        except (TypeError, ValueError):
            return True
    return _norm(ev) != _norm(av)
