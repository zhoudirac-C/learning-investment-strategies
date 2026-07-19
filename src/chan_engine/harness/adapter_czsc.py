"""czsc 适配器（M1 对照实现，Task 5）。

把 czsc 0.10.12 的分型/笔/中枢识别结果搬运归一到 ``NormalizedChart``。
适配器只做搬运归一，不含任何缠论判断逻辑；czsc 不产出线段与买卖点，
对应两张表置空并在 ``na_fields`` 标记 ``{"seg", "bsp"}``。

索引映射依据
------------
归一模型的 ``idx`` 一律是输入 ``bars`` 的 0 基位置下标。转换时第 i 根 Bar
映射为 ``RawBar(id=i+1, dt=BASE_DT + i 天, freq=Freq.D, ...)``，同时建立
``dt -> i`` 字典。czsc 输出对象（``FX.dt`` / ``BI.fx_a.dt`` / ``BI.fx_b.dt``）
的 dt 总是某根输入 RawBar 的 dt（去包含合并时 ``remove_include`` 取极值所在
原始 K 线的 dt），因此查字典即得 0 基下标。

注意（czsc 0.10.12 rust 后端的坑）：输入 naive datetime 会被 rs_czsc 当作
北京时间转成 UTC 存储，输出 dt 整体偏移 -8 小时。本适配器一律使用
tz-aware（UTC）datetime 投喂，此时输出 dt 与输入逐值相等（tz 被丢弃），
映射字典无需任何时区修正。

sure 口径
---------
czsc 没有显式的"右侧确认"标记，归一规则：
- Bi：出现在 ``CZSC.finished_bis`` 中（按 (fx_a.dt, fx_b.dt) 匹配）为 sure=True；
- FX：出现在任一 finished bi 的 ``fxs`` 中（按 dt 匹配）为 sure=True，
  仅存在于未完成笔（ubi）中的分型 sure=False。

已知口径差异（如实搬运，留给对表报告，不在此补偿）
--------------------------------------------------
1. ``CZSC.fx_list`` 按 ``bi.fxs[1:]`` 拼接，不包含第一笔的起始分型。
2. ``get_zs_seq`` 滚动分组中 ``len(bis) < 3`` 或 ``is_valid=False`` 的组
   不满足缠论中枢定义（至少三段重叠），归一时剔除。
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import List

from chan_engine.spec.model import (
    Bar,
    Bi,
    Direction,
    FX,
    NormalizedChart,
    ZhongShu,
)

import czsc
from czsc import CZSC, Freq, RawBar
from czsc import envs as czsc_envs
from czsc.core import check_rs_czsc
from czsc.utils.sig import get_zs_seq

SOURCE = "czsc"

# RawBar.dt 合成起点（tz-aware UTC，规避 rs_czsc naive-datetime 的 -8h 偏移）
BASE_DT = datetime(2000, 1, 1, tzinfo=timezone.utc)

# czsc 默认成笔最小长度（新笔口径）。rs_czsc 内置该默认值且完全忽略
# 环境变量 czsc_min_bi_len（0.10.12 实证：设 7 输出不变，kwarg 被拒），
# 只有 python 后端（czsc.py.analyze.check_bi 每次调用时读 envs.get_min_bi_len()）
# 才会响应该参数。
_DEFAULT_MIN_BI_LEN = 6

# czsc Mark/Direction 枚举值（rust 与 python 后端的枚举类不同，
# 统一按 .value 字符串比对）
_MARK_TOP = "顶分型"  # Mark.G
_MARK_BOTTOM = "底分型"  # Mark.D
_DIR_UP = "向上"  # Direction.Up


def _fx_direction(mark_value: str) -> Direction:
    """czsc Mark → 归一 FX.type（顶分型=UP，底分型=DOWN，见 model.py 约定）。"""
    if mark_value == _MARK_TOP:
        return Direction.UP
    if mark_value == _MARK_BOTTOM:
        return Direction.DOWN
    raise ValueError(f"未知 czsc 分型标记: {mark_value!r}")


def _bi_direction(direction_value: str) -> Direction:
    if direction_value == _DIR_UP:
        return Direction.UP
    return Direction.DOWN


class CzscAdapter:
    """``ChartAdapter`` 协议的 czsc 实现（结构性对齐，不 import adapter.py）。

    :param min_bi_len: 成笔最小长度（无包含 K 线数），默认 None 即跟随 czsc
        默认值 6。czsc 0.10.12 的该参数不走构造函数，只有 python 后端通过
        环境变量 ``czsc_min_bi_len`` 生效；rust 后端（rs_czsc）内置默认值 6
        并完全忽略该环境变量。因此当传入非默认值且顶层后端为 rust 时，本适配器
        对该实例改用 ``czsc.py.analyze.CZSC``（python 实现）执行，让参数真实生效；
        环境变量仅在 run() 内临时设置并在结束后恢复原值，不留进程级污染。
    :param max_bi_num: ``CZSC`` 构造参数，最大保留笔数（默认取 czsc 全局配置 50）。
    """

    def __init__(self, min_bi_len: int | None = None, max_bi_num: int | None = None):
        rs_installed, _ = check_rs_czsc()
        # 顶层 czsc 的后端在 import 时由 CZSC_USE_PYTHON / rs_czsc 是否安装决定，
        # import 之后无法再切换；但 czsc.py 子包始终可独立 import。
        self._rust_backend = rs_installed and not os.getenv("CZSC_USE_PYTHON")
        self._requested_min_bi_len = min_bi_len
        self._backend_switch_reason: str | None = None
        if min_bi_len is not None and min_bi_len != _DEFAULT_MIN_BI_LEN:
            # 非默认 min_bi_len 只有 python 后端才生效
            self._use_py_path = True
            if self._rust_backend:
                self._backend_switch_reason = (
                    f"min_bi_len={min_bi_len} 为非默认值，rs_czsc 忽略 "
                    f"czsc_min_bi_len 环境变量，改用 czsc.py（python 后端）使参数真实生效"
                )
        else:
            # 未传参或显式传默认值：rust 后端行为一致（内置 6），无需切换
            self._use_py_path = not self._rust_backend
        self.max_bi_num = max_bi_num

    @property
    def name(self) -> str:
        return SOURCE

    @property
    def config_snapshot(self) -> dict:
        rs_installed, rs_version = check_rs_czsc()
        if self._use_py_path:
            backend = "python"
            effective_min_bi_len = (
                self._requested_min_bi_len
                if self._requested_min_bi_len is not None
                else czsc_envs.get_min_bi_len()
            )
        else:
            backend = "rust"
            # rs_czsc 内置 6，忽略 czsc_min_bi_len（0.10.12 实证）
            effective_min_bi_len = _DEFAULT_MIN_BI_LEN
        return {
            "czsc_version": czsc.__version__,
            "backend": backend,
            "rs_czsc_version": rs_version if backend == "rust" else None,
            "requested_min_bi_len": self._requested_min_bi_len,
            "effective_min_bi_len": effective_min_bi_len,
            # 兼容旧 key：如实记录实际生效值（而非环境变量读数）
            "min_bi_len": effective_min_bi_len,
            "backend_switch_reason": self._backend_switch_reason,
            "max_bi_num": self.max_bi_num
            if self.max_bi_num is not None
            else czsc_envs.get_max_bi_num(),
            "freq": Freq.D.value,
            "dt_base": BASE_DT.isoformat(),
        }

    def run(self, bars: List[Bar]) -> NormalizedChart:
        if self._use_py_path:
            c, dt_to_idx = self._run_python_backend(bars)
        else:
            raw_bars, dt_to_idx = self._to_raw_bars(bars, RawBar, Freq.D)
            kwargs = {} if self.max_bi_num is None else {"max_bi_num": self.max_bi_num}
            c = CZSC(raw_bars, **kwargs)

        finished_keys = {
            (self._dt_key(bi.fx_a.dt), self._dt_key(bi.fx_b.dt))
            for bi in c.finished_bis
        }
        confirmed_fx_dts = {
            self._dt_key(fx.dt) for bi in c.finished_bis for fx in bi.fxs
        }

        fx_table = [
            FX(
                idx=dt_to_idx[self._dt_key(fx.dt)],
                type=_fx_direction(fx.mark.value),
                sure=self._dt_key(fx.dt) in confirmed_fx_dts,
                source=SOURCE,
            )
            for fx in c.fx_list
        ]

        bi_table = [
            Bi(
                start_idx=dt_to_idx[self._dt_key(bi.fx_a.dt)],
                end_idx=dt_to_idx[self._dt_key(bi.fx_b.dt)],
                dir=_bi_direction(bi.direction.value),
                sure=(self._dt_key(bi.fx_a.dt), self._dt_key(bi.fx_b.dt))
                in finished_keys,
                source=SOURCE,
            )
            for bi in c.bi_list
        ]

        zs_table = [
            ZhongShu(
                zd=zs.zd,
                zg=zs.zg,
                start_idx=dt_to_idx[self._dt_key(zs.bis[0].fx_a.dt)],
                end_idx=dt_to_idx[self._dt_key(zs.bis[-1].fx_b.dt)],
                level=1,
                sure=True,
                source=SOURCE,
            )
            for zs in get_zs_seq(c.bi_list)
            if len(zs.bis) >= 3 and zs.is_valid
        ]

        return NormalizedChart(
            fx=fx_table,
            bi=bi_table,
            seg=[],
            zs=zs_table,
            bsp=[],
            na_fields={"seg", "bsp"},
        )

    def _run_python_backend(self, bars: List[Bar]) -> tuple:
        """python 后端执行路径（非默认 min_bi_len 的唯一生效途径）。

        顶层 czsc 为 rust 时，懒加载 ``czsc.py`` 子包对象（始终可 import，
        与顶层后端选择无关）；``czsc_min_bi_len`` 仅在 CZSC 构造期间临时设置，
        finally 中恢复原值，避免进程级环境污染。
        """
        if self._rust_backend:
            from czsc.py import Freq as PyFreq
            from czsc.py import RawBar as PyRawBar
            from czsc.py.analyze import CZSC as PyCZSC

            raw_bar_cls, freq, czsc_cls = PyRawBar, PyFreq.D, PyCZSC
        else:
            # 顶层后端本身已是 python，模块级对象即 python 实现
            raw_bar_cls, freq, czsc_cls = RawBar, Freq.D, CZSC
        raw_bars, dt_to_idx = self._to_raw_bars(bars, raw_bar_cls, freq)
        kwargs = {} if self.max_bi_num is None else {"max_bi_num": self.max_bi_num}
        if self._requested_min_bi_len is None:
            return czsc_cls(raw_bars, **kwargs), dt_to_idx
        prev = os.environ.get("czsc_min_bi_len")
        os.environ["czsc_min_bi_len"] = str(self._requested_min_bi_len)
        try:
            return czsc_cls(raw_bars, **kwargs), dt_to_idx
        finally:
            if prev is None:
                del os.environ["czsc_min_bi_len"]
            else:
                os.environ["czsc_min_bi_len"] = prev

    @staticmethod
    def _to_raw_bars(bars: List[Bar], raw_bar_cls=RawBar, freq=Freq.D) -> tuple[list, dict]:
        """Bar → czsc RawBar；返回 (raw_bars, {归一化dt键: 0基下标})。"""
        raw_bars: list = []
        dt_to_idx: dict = {}
        for i, bar in enumerate(bars):
            dt = BASE_DT + timedelta(days=i)
            raw_bars.append(
                raw_bar_cls(
                    symbol="SYNTH",
                    id=i + 1,  # czsc 约定 id 升序
                    dt=dt,
                    freq=freq,
                    open=bar.o,
                    close=bar.c,
                    high=bar.h,
                    low=bar.l,
                    vol=bar.vol,
                    amount=bar.vol * bar.c,
                )
            )
            dt_to_idx[CzscAdapter._dt_key(dt)] = i
        return raw_bars, dt_to_idx

    @staticmethod
    def _dt_key(dt) -> tuple:
        """归一化 dt 键：rust 后端返回 pandas.Timestamp（可能丢 tz），
        python 后端返回 datetime；统一到 (y,m,d,H,M,S) 元组比较。"""
        return (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)
