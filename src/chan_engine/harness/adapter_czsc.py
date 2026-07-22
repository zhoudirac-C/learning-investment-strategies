"""czsc 适配器（M2-2 改造版：首分型补偿 + zs 重算 + 位置约定）。

把 czsc 0.10.12 的分型/笔/中枢识别结果搬运归一到 ``NormalizedChart``。
适配器只做搬运与归一，不含任何缠论判断逻辑；czsc 不产出线段与买卖点，
对应两张表置空并在 ``na_fields`` 标记 ``{"seg", "bsp"}``。

M2-2 改造（替换 M1 的 ``get_zs_seq`` / ``c.fx_list`` 直取口径）
----------------------------------------------------------------
1. **首分型补偿 + fx 从 bi 端点推导**：czsc ``CZSC.fx_list`` 按
   ``bi.fxs[1:]`` 拼接，丢第一笔起始分型；且 czsc 不消解"被取代的候选分型"
   （BI-004 多余 idx=5/idx=6）。M2-2 直接从 ``bi_list`` 推导 fx 表——
   ``fx[0] = bi_list[0].fx_a``（首分型补偿，有笔从它出发即 sure=True），
   ``fx[1..n] = bi_list[i].fx_b``（每笔终点分型）。集合 = 首笔起点 + 每笔终点，
   与 chanpy fx 表口径一致（幸存分型 = 笔端点）。
2. **zs 重算（弃用 ``get_zs_seq``）**：czsc ``get_zs_seq`` 把所有重叠笔算入
   中枢（start=第一笔起点、end=最后一笔终点），与课文/expect 口径不符。M2-2
   按 chanpy normal 模式口径重算：引导笔 ``bi0`` 决定走势方向（``seg_dir``），
   **反向笔**参与 zs 构造——连续 2 个反向笔重叠即确立中枢（``start=反向笔a.start_idx``、
   ``end=反向笔b.end_idx``、``zd=max(low)``、``zg=min(high)``），后续反向笔
   ``in_range``（笔 [low,high] 与中枢 [zd,zg] 严格重叠，不含边界）则延展 ``end``；
   反向笔不在 ``in_range`` → 当前中枢结束，开始下一个中枢。
   九段升级（level=2）暂不实现，归 M2-3 P-K 范围。
3. **位置约定**（M2-1 同 chanpy 适配器）：fx/bi 表末位 sure=False、其余 True。

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


def _apply_positional_sure(table: list) -> None:
    """按位置约定就地写 sure 字段（与 chanpy 适配器同口径）。

    - fx/bi/seg 表：末位 sure=False、其余 True；空表与单元素表（单元素即末位）→ 全 False
    - zs/bsp 表：形成即 sure=True（恒 True，本函数不处理这两类）

    本函数仅作用于 fx/bi；调用方在循环内把每个元素的 sure 占位为 True，
    循环结束后调本函数把末位翻为 False，与归一约定对齐。
    """
    n = len(table)
    if n == 0:
        return
    for i, elem in enumerate(table):
        elem.sure = i < n - 1  # 末位 False，其余 True


def _bi_low_high(bi: Bi, bars: List[Bar]) -> tuple[float, float]:
    """笔的极值（与 chanpy ``CBi._low()/_high()`` 同口径）。

    上升笔：low=起点 K 线 low，high=终点 K 线 high；
    下降笔：low=终点 K 线 low，high=起点 K 线 high。

    ``bi.start_idx``/``bi.end_idx`` 已是分型极值所在原始 K 线的 0 基下标
    （czsc ``fx_a.dt``/``fx_b.dt`` 取合并 K 线极值 klu 的 dt），故直接取该
    K 线的 h/l，无需扫描笔内全部 K 线。
    """
    if bi.dir is Direction.UP:
        return float(bars[bi.start_idx].l), float(bars[bi.end_idx].h)
    return float(bars[bi.end_idx].l), float(bars[bi.start_idx].h)


def _has_overlap_strict(low1: float, high1: float, low2: float, high2: float) -> bool:
    """严格重叠（不含边界），对齐 chanpy ``has_overlap(equal=False)``。"""
    return high2 > low1 and high1 > low2


def _recompute_zs(bi_table: list[Bi], bars: List[Bar]) -> list[ZhongShu]:
    """从归一 bi 表按课文/chanpy normal 模式口径重算中枢（M2-2）。

    算法（源自 expect ZS-001/002/004 + chanpy ``CZSList`` normal 模式）：
    - 引导笔 ``bi_table[0]`` 决定走势方向 ``seg_dir``，**反向笔**参与 zs 构造
    - 连续 2 个反向笔重叠即确立中枢：
      ``start=反向笔a.start_idx``、``end=反向笔b.end_idx``、
      ``zd=max(a.low, b.low)``、``zg=min(a.high, b.high)``（严格 ``zg > zd``）
    - 中枢确立后，后续**已确认**（``sure=True``）反向笔若 ``in_range``（笔 [low,high]
      与中枢 [zd,zg] 严格重叠）则延展 ``end`` 到该笔 ``end_idx``；
      **末位笔（``sure=False``）不参与延伸**——对齐 chanpy "seg 末段未确认不延伸"
      行为（chanpy zs 受 seg 切分限制，seg1 恒未确认，zs 只在确认的 seg0 内延伸）
    - 反向笔不在 ``in_range`` → 当前中枢结束，该笔入 free_lst 等待与下一反向笔配对
    - **九段升级**（M2-3 PATCHES 实现）：中枢延伸 ≥9 段时升级为 level=2，
      zd/zg 改为 3 个子中枢（bi[1:4]/bi[4:7]/bi[7:10]）的重合区间
      ``max(sub_zs.zd) / min(sub_zs.zg)``

    已知局限：BSP-002/BSP-004 等"已确认反向笔 in_range 但 expect 不延伸"的用例
    需要 chanpy seg 切分算法（特征序列分型）限制 zs 延伸范围，czsc 适配器不产出
    seg，无法完全对齐——归 M2-5 已知偏差登记。

    :return: 重算后的中枢列表（按出现顺序）；空表当 ``len(bi_table) < 3``。
    """
    n = len(bi_table)
    if n < 3:  # 至少引导笔 + 2 反向笔
        return []

    seg_dir = bi_table[0].dir  # 引导游方向（= 中枢所在 seg 方向）
    zs_list: list[ZhongShu] = []
    free_lst: list[Bi] = []  # 等待配对的反向笔队列

    for bi in bi_table[1:]:  # 跳过引导笔
        if bi.dir is seg_dir:
            continue  # 同向笔跳过（chanpy ``add_zs_from_bi_range`` 第 65 行）

        # 反向笔
        if not free_lst and zs_list:
            # free_lst 空 + 已有中枢 → 尝试延伸最后一个中枢
            # M2-3: 末位笔（sure=False）不参与延伸（对齐 chanpy seg 末段不延伸）
            low, high = _bi_low_high(bi, bars)
            last_zs = zs_list[-1]
            if bi.sure and _has_overlap_strict(last_zs.zd, last_zs.zg, low, high):
                last_zs.end_idx = bi.end_idx
                # 不更新 zd/zg（chanpy ``try_add_to_end`` 只调 ``update_zs_end``）
                continue
            # 不延伸 → 当前中枢结束，该笔入 free_lst

        free_lst.append(bi)
        if len(free_lst) >= 2:
            bi_a, bi_b = free_lst[-2], free_lst[-1]
            low_a, high_a = _bi_low_high(bi_a, bars)
            low_b, high_b = _bi_low_high(bi_b, bars)
            zd = max(low_a, low_b)
            zg = min(high_a, high_b)
            if zg > zd:  # 严格重叠
                zs_list.append(
                    ZhongShu(
                        zd=zd,
                        zg=zg,
                        start_idx=bi_a.start_idx,
                        end_idx=bi_b.end_idx,
                        level=1,
                        sure=True,
                        source=SOURCE,
                    )
                )
                free_lst = []  # 中枢构造成功，清空 free_lst

    # 九段升级后处理（M2-3 PATCHES）：中枢延伸 ≥9 段 → level=2
    _apply_nine_bi_upgrade(zs_list, bi_table, bars)
    return zs_list


def _apply_nine_bi_upgrade(
    zs_list: list[ZhongShu], bi_table: list[Bi], bars: List[Bar]
) -> None:
    """九段升级（课33）：中枢内连续 9 段重叠 → 更大级别中枢 level=2。

    规则（源自 ZS-003 expect）：
    - 中枢范围内的笔数 ≥9 时触发
    - 将 9 段分为 3 组子中枢（每组 3 笔），计算每组的 zd/zg
    - level=2 中枢的 zd/zg = 3 个子中枢的重合区间（max(sub_zd)/min(sub_zg)）
    - start_idx/end_idx 不变，level 升为 2

    就地修改 zs_list 中的元素。
    """
    for zs in zs_list:
        if zs.level != 1:
            continue
        # 收集中枢范围内的所有笔（start_idx 到 end_idx）
        in_range_bis = [
            bi for bi in bi_table if bi.start_idx >= zs.start_idx and bi.end_idx <= zs.end_idx
        ]
        if len(in_range_bis) < 9:
            continue
        # 取前 9 笔，分 3 组（每组 3 笔）
        nine_bis = in_range_bis[:9]
        sub_zs_ranges = []
        for i in range(0, 9, 3):
            group = nine_bis[i : i + 3]
            lows = []
            highs = []
            for bi in group:
                low, high = _bi_low_high(bi, bars)
                lows.append(low)
                highs.append(high)
            sub_zd = max(lows)
            sub_zg = min(highs)
            if sub_zg <= sub_zd:  # 子中枢不成立
                break
            sub_zs_ranges.append((sub_zd, sub_zg))
        if len(sub_zs_ranges) != 3:
            continue
        # 3 个子中枢的重合区间
        level2_zd = max(r[0] for r in sub_zs_ranges)
        level2_zg = min(r[1] for r in sub_zs_ranges)
        if level2_zg > level2_zd:
            zs.zd = level2_zd
            zs.zg = level2_zg
            zs.level = 2


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
            # M2-2 标记：zs 重算口径
            "zs_recompute": "chanpy_normal_mode",
            "fx_source": "bi_endpoints",
        }

    def run(self, bars: List[Bar]) -> NormalizedChart:
        if self._use_py_path:
            c, dt_to_idx = self._run_python_backend(bars)
        else:
            raw_bars, dt_to_idx = self._to_raw_bars(bars, RawBar, Freq.D)
            kwargs = {} if self.max_bi_num is None else {"max_bi_num": self.max_bi_num}
            c = CZSC(raw_bars, **kwargs)

        # czsc 笔表（全部视为 finished，含最后一笔）。
        # 归一 fx/bi 表从 bi_list 推导（M2-2：首分型补偿 + 位置约定）
        bi_table: list[Bi] = [
            Bi(
                start_idx=dt_to_idx[self._dt_key(bi.fx_a.dt)],
                end_idx=dt_to_idx[self._dt_key(bi.fx_b.dt)],
                dir=_bi_direction(bi.direction.value),
                sure=True,  # 位置约定在循环后统一应用
                source=SOURCE,
            )
            for bi in c.bi_list
        ]
        _apply_positional_sure(bi_table)

        # fx 表：从 bi 端点推导（首分型补偿 + 每笔终点）
        # fx[0] = bi_list[0].fx_a（首分型）；fx[1..n] = bi_list[i].fx_b
        fx_table: list[FX] = []
        if c.bi_list:
            first_bi = c.bi_list[0]
            fx_table.append(
                FX(
                    idx=dt_to_idx[self._dt_key(first_bi.fx_a.dt)],
                    type=_fx_direction(first_bi.fx_a.mark.value),
                    sure=True,  # 位置约定在循环后统一应用
                    source=SOURCE,
                )
            )
            for bi in c.bi_list:
                fx_table.append(
                    FX(
                        idx=dt_to_idx[self._dt_key(bi.fx_b.dt)],
                        type=_fx_direction(bi.fx_b.mark.value),
                        sure=True,  # 位置约定在循环后统一应用
                        source=SOURCE,
                    )
                )
        else:
            # 无笔时 czsc fx_list 可能含孤立分型（未成笔候选），保留搬运
            for fx in c.fx_list:
                fx_table.append(
                    FX(
                        idx=dt_to_idx[self._dt_key(fx.dt)],
                        type=_fx_direction(fx.mark.value),
                        sure=False,  # 孤立分型未确认
                        source=SOURCE,
                    )
                )
        _apply_positional_sure(fx_table)

        # zs 表：从归一 bi 表按课文口径重算（M2-2，弃用 get_zs_seq）
        zs_table = _recompute_zs(bi_table, bars)

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
