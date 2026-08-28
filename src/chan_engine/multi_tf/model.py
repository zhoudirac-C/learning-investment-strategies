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
from chan_engine.spec.model import BSPoint, NormalizedChart, ZhongShu


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
class SubLevelConfirmation:
    """日线一笔在某次级别上的区间套确认（M7-4，§5.2 骨架 + §7.1 四输出）。

    - ``zs_in_bi``/``bsp_in_bi``：窗口归属的次级别中枢/买卖点（精确定位）；
    - ``backchi``：窗口内存在与日线笔**反向**的 bstype=1（次级别背驰确认信号）；
    - ``backchi_metric``：双口径证据 ``{"area_proxy": {enter,leave},
      "macd_area": {enter,leave}}``（MACD 主口径已下结论，此处为对照证据）；
    - ``coverage``/``note``：次级别数据不足显式传播（禁止静默降级）；
    - ``small_to_large``：小转大候选（课 43——次级别背驰 + 大级别同位置无背驰；
      仅标注，升级须人工与大级别背驰同时确认，防级别错配镜像纪律）；
    - ``second_buy_confirmed``：日线二买候选的次级别一买确认（买点定律
      claim-20061205-001-a）；无关联二买时为 None。
    """

    bi_ref: tuple[int, int]       # 日线笔 (start_idx, end_idx)
    tf: str                       # '60m' / '30m'
    zs_in_bi: list[ZhongShu] = field(default_factory=list)
    bsp_in_bi: list[BSPoint] = field(default_factory=list)
    backchi: bool = False
    backchi_metric: dict = field(default_factory=dict)
    coverage: bool = True
    note: str = ""
    small_to_large: bool = False
    second_buy_confirmed: bool | None = None


@dataclass
class MultiTimeframeChart:
    """多周期容器（§5.2；M7-2 建 slices，M7-4 填 sub 图与 confirmations）。"""

    daily: NormalizedChart
    sub: dict[str, NormalizedChart] = field(default_factory=dict)  # {'60m':…,'30m':…}
    slices: list[BiSlice] = field(default_factory=list)            # 日线笔 × 次级别
    confirmations: list[SubLevelConfirmation] = field(default_factory=list)
