"""synthetic K 线构造助手（M1 spec 层）。

只造 Bar，不含任何缠论逻辑。两种输入：

1. 收盘价序列：字符串 ``"10,11,9,12,8"`` 或数值序列，自动配默认振幅生成
   合法 o/h/l/c（o 取前一根收盘价，首根 o=c；h/l 按振幅外扩）；
2. 显式 ``(o, h, l, c)`` 行列表，逐行校验合法性。

两种输入都自动补 ``ts``（自 ``ts0`` 起递增整数）与 ``vol``（常量）。
合法性保证：``h >= max(o, c)`` 且 ``l <= min(o, c)``。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from chan_engine.spec.model import Bar

DEFAULT_AMPLITUDE = 0.5
DEFAULT_VOL = 1000.0


def bars_from(data: str | Iterable[Sequence[float]]) -> list[Bar]:
    """分发器：字符串走收盘价序列记法，其余走显式 (o,h,l,c) 行。"""

    if isinstance(data, str):
        return bars_from_closes(data)
    return bars_from_ohlc(data)


def bars_from_closes(
    closes: str | Sequence[float],
    amplitude: float = DEFAULT_AMPLITUDE,
    vol: float = DEFAULT_VOL,
    ts0: int = 0,
) -> list[Bar]:
    """收盘价序列 → 合法 Bar 列表。

    o 取前一根收盘价（首根 o=c）；h = max(o,c)+amplitude，l = min(o,c)-amplitude，
    因此 h>=max(o,c)、l<=min(o,c) 恒成立（amplitude>0）。
    """

    if amplitude <= 0:
        raise ValueError(f"amplitude 必须为正: {amplitude!r}")
    if isinstance(closes, str):
        values = [float(p) for p in closes.split(",") if p.strip()]
    else:
        values = [float(x) for x in closes]
    if not values:
        raise ValueError("收盘价序列为空")

    bars: list[Bar] = []
    prev_close = values[0]
    for i, c in enumerate(values):
        o = prev_close
        bars.append(
            Bar(
                ts=ts0 + i,
                o=o,
                h=max(o, c) + amplitude,
                l=min(o, c) - amplitude,
                c=c,
                vol=vol,
            )
        )
        prev_close = c
    return bars


def bars_from_ohlc(
    rows: Iterable[Sequence[float]],
    vol: float = DEFAULT_VOL,
    ts0: int = 0,
) -> list[Bar]:
    """显式 (o,h,l,c) 行 → Bar 列表，逐行校验 h>=max(o,c)、l<=min(o,c)。"""

    bars: list[Bar] = []
    for i, row in enumerate(rows):
        if not isinstance(row, (list, tuple)) or len(row) != 4:
            raise ValueError(f"bars[{i}] 必须是 (o, h, l, c) 四元组: {row!r}")
        o, h, low, c = (float(v) for v in row)
        if h < max(o, c) or low > min(o, c):
            raise ValueError(
                f"bars[{i}] 不满足 h>=max(o,c) 且 l<=min(o,c): {row!r}"
            )
        bars.append(Bar(ts=ts0 + i, o=o, h=h, l=low, c=c, vol=vol))
    if not bars:
        raise ValueError("bars 为空")
    return bars
