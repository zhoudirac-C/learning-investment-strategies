"""M7-2 跨周期对齐层：数据容器（chanlun-m7-multitimeframe-skill.md §5.2）。

- ``BiSlice``：日线笔 → 次级别 bar 切片窗口映射（时间窗映射暂定案，§5.1）。
- ``MultiTimeframeChart``：多周期容器——日线归一图 + 次级别图（M7-4 引擎
  分解后填充）+ 笔→切片映射。SubLevelConfirmation 属 M7-4 产出，本期不建。

tf 标签约定：multi_tf 层用 str（'60m'/'30m'，对齐设计 §5.2）；数据层用 int
（60/30，minute_bars.tf），``tf_label``/``tf_minutes`` 互转。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from chan_engine.data.fetch import VALID_MINUTE_TF
from chan_engine.spec.model import NormalizedChart


def tf_label(tf: int) -> str:
    """60 → '60m'；30 → '30m'。非法 tf 抛 ValueError。"""
    if tf not in VALID_MINUTE_TF:
        raise ValueError(f"不支持的分钟周期 tf={tf}（仅 {VALID_MINUTE_TF}）")
    return f"{tf}m"


def tf_minutes(label: str) -> int:
    """'60m' → 60；'30m' → 30。非法标签抛 ValueError。"""
    if not label.endswith("m"):
        raise ValueError(f"非法 tf 标签: {label!r}")
    try:
        tf = int(label[:-1])
    except ValueError:
        raise ValueError(f"非法 tf 标签: {label!r}") from None
    if tf not in VALID_MINUTE_TF:
        raise ValueError(f"不支持的分钟周期标签 {label!r}（仅 {[tf_label(t) for t in VALID_MINUTE_TF]}）")
    return tf


@dataclass
class BiSlice:
    """日线一笔在某个次级别上的切片窗口映射。

    ``start_pos``/``end_pos`` 为该 tf rows 列表内的切片界（python slice 惯例，
    含头不含尾）；rows 与 ``load_bars(tf)`` 同序同过滤（complete=0 已剔除），
    位置索引两边对齐。``coverage=False`` 时 ``note`` 必含"次级别数据不足"
    及缺段方向（§5.1：禁止静默降级）。
    """

    bi_ref: tuple[int, int]       # 日线笔 (start_idx, end_idx)
    tf: str                       # '60m' / '30m'
    window: tuple[str, str]       # (start_dt, end_dt)，'YYYY-MM-DD HH:MM'
    start_pos: int
    end_pos: int
    coverage: bool
    note: str = ""


@dataclass
class MultiTimeframeChart:
    """多周期容器（§5.2 最小形态；confirmations 待 M7-4 增补）。"""

    daily: NormalizedChart
    sub: dict[str, NormalizedChart] = field(default_factory=dict)  # {'60m':…,'30m':…}
    slices: list[BiSlice] = field(default_factory=list)            # 日线笔 × 次级别
