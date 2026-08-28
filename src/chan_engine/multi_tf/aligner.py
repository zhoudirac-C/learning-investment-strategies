"""M7-2 跨周期对齐层：TFAligner（chanlun-m7-multitimeframe-skill.md §5）。

日线笔时间窗 → 次级别 bar 切片（时间窗映射暂定案，§5.1）：

- 窗口：``daily_dates[bi.start_idx] 00:00 ~ daily_dates[bi.end_idx] 15:00``；
- 纪律：分钟 dt 形态 + A 股时段校验（异常抛 ``AlignmentError``，§5.3），
  complete=0 未收盘 bar 默认剔除，切片结果全部 bar 必落窗口内（断言防错位）；
- 边界：切片空窗 / 数据前段缺 / 后段缺 → ``coverage=False`` + note 标注
  "次级别数据不足"，禁止静默降级。
"""
from __future__ import annotations

from datetime import datetime

from chan_engine.multi_tf.model import (
    BiSlice,
    MultiTimeframeChart,
    tf_label,
    tf_minutes,
)
from chan_engine.spec.model import Bi, NormalizedChart


class AlignmentError(RuntimeError):
    """时间戳对齐违规：异常 dt（形态/时段）或笔索引/周期标签越界。"""


def _check_dt(dt: str) -> None:
    """分钟 dt 须为 'YYYY-MM-DD HH:MM' 且落在 A 股时段。

    bar 标签 = 周期结束时刻，合法区间 (09:30, 11:30] ∪ [13:00, 15:00]
    （9:30 无结束标签——首根 60m 收 10:30；午餐/盘后非法）。
    """
    try:
        datetime.strptime(dt, "%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        raise AlignmentError(f"分钟 dt 形态异常: {dt!r}")
    hm = dt[11:]
    if not ("09:30" < hm <= "11:30" or "13:00" <= hm <= "15:00"):
        raise AlignmentError(f"分钟 dt 非交易时段: {dt!r}")


class TFAligner:
    """日线笔 → 次级别切片的对齐器。

    ``daily_dates``：与喂给引擎的日线 bars 平行的 'YYYY-MM-DD' 列表
    （bi.start_idx/end_idx 即该列表索引）。``sub_rows``：{'60m': rows, '30m': rows}，
    rows 为 load_minute 归一行（含 dt/complete）；构造时校验 dt 并按 dt 排序，
    默认剔除 complete=0（load_minute 已默认剔除，此处防御性再过滤）。
    """

    def __init__(self, daily_dates: list[str], sub_rows: dict[str, list[dict]],
                 include_partial: bool = False):
        self.daily_dates = list(daily_dates)
        self.sub_rows: dict[str, list[dict]] = {}
        for label, rows in sub_rows.items():
            tf_minutes(label)  # 标签越界 → ValueError
            kept = []
            for r in rows:
                _check_dt(str(r.get("dt", "")))
                complete = r.get("complete")
                if not include_partial and int(complete if complete is not None else 1) == 0:
                    continue
                kept.append(r)
            kept.sort(key=lambda r: r["dt"])
            self.sub_rows[label] = kept

    def window_of(self, bi: Bi) -> tuple[str, str]:
        """日线笔 → 时间窗（start_date 00:00, end_date 15:00）。"""
        for idx in (bi.start_idx, bi.end_idx):
            if not 0 <= idx < len(self.daily_dates):
                raise AlignmentError(
                    f"笔索引越界: ({bi.start_idx}, {bi.end_idx})，"
                    f"daily_dates 长度 {len(self.daily_dates)}")
        return (f"{self.daily_dates[bi.start_idx]} 00:00",
                f"{self.daily_dates[bi.end_idx]} 15:00")

    def slice_bi(self, bi: Bi, tf: str) -> BiSlice:
        """单根笔 → 该 tf 的切片映射（含 coverage 判定）。"""
        if tf not in self.sub_rows:
            raise AlignmentError(f"未知次级别 {tf!r}（已有 {sorted(self.sub_rows)}）")
        window = self.window_of(bi)
        rows = self.sub_rows[tf]
        start_pos = next((i for i, r in enumerate(rows) if r["dt"] >= window[0]),
                         len(rows))
        end_pos = next((i for i, r in enumerate(rows) if r["dt"] > window[1]),
                       len(rows))
        start_pos = min(start_pos, end_pos)
        sliced = rows[start_pos:end_pos]
        # 重叠校验：切片 bar 必落窗口内（防数据错位，§5.3）
        assert all(window[0] <= r["dt"] <= window[1] for r in sliced), \
            f"切片越出窗口 {window}: {sliced[0]['dt']} ~ {sliced[-1]['dt']}"

        coverage, note = True, ""
        if not sliced:
            coverage, note = False, "次级别数据不足：窗口内无数据"
        else:
            head_ok = rows[0]["dt"][:10] <= window[0][:10]
            tail_ok = rows[-1]["dt"][:10] >= window[1][:10]
            if not head_ok:
                coverage = False
                note = f"次级别数据不足：窗口前段无数据（数据起于 {rows[0]['dt'][:10]}）"
            elif not tail_ok:
                coverage = False
                note = f"次级别数据不足：窗口后段无数据（数据止于 {rows[-1]['dt'][:10]}）"
        return BiSlice(
            bi_ref=(bi.start_idx, bi.end_idx),
            tf=tf,
            window=window,
            start_pos=start_pos,
            end_pos=end_pos,
            coverage=coverage,
            note=note,
        )

    def slice_all(self, chart: NormalizedChart) -> list[BiSlice]:
        """整图：日线全部笔 × 全部已载次级别 → 切片映射列表。"""
        return [self.slice_bi(bi, tf)
                for bi in chart.bi for tf in sorted(self.sub_rows)]

    def slice_rows(self, s: BiSlice) -> list[dict]:
        """取切片对应的实际分钟行（与 BiSlice 位置界一致）。"""
        return self.sub_rows[s.tf][s.start_pos:s.end_pos]


def build_multi_tf_chart(
    daily: NormalizedChart,
    daily_dates: list[str],
    sub_rows: dict[str, list[dict]],
) -> MultiTimeframeChart:
    """M7-2 容器装配：日线归一图 + 笔→切片映射（sub 图留 M7-4 引擎分解填充）。"""
    aligner = TFAligner(daily_dates, sub_rows)
    return MultiTimeframeChart(daily=daily, slices=aligner.slice_all(daily))
