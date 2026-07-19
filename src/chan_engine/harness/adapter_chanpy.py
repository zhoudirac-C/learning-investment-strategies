"""chan.py 适配器（M1 harness）：把 vendor 的 chan.py 输出归一到 NormalizedChart。

只做搬运与归一，不改 chan.py 算法口径。chan.py 源码零改动（third_party/chanpy/，
通过 PYTHONPATH 引入，包内为绝对 import）。

要点记录（详见 .superpowers/sdd/task-4-report.md）：
- 配置：CChanConfig 默认 + 两个显式项——``trigger_step=True``（逐帧 ``trigger_load``
  投喂是 chan.py 官方外部喂数据姿势（third_party/chanpy/Debug/strategy_demo2.py），
  该开关只改变计算触发方式，不改变口径）；``bi_fx_check="loss"``（M2-1 起，
  ADR-001 口径 B：笔的区间检查只比分型中间 K 线自身区间）。快照中如实记录。
- 时间：Bar.ts 是 int 序号，chan.py 需要单调递增的 CTime；按投喂位置
  合成为 2000-01-01 + pos 天（K_DAY 级别）。klu.idx 由 chan.py 按投喂顺序
  从 0 顺编（CChan.try_set_klu_idx），与输入 bars 的 0 基下标一一对应。

归一约定（M2-1 定型，规则源自全部 expect 语料）：
- FX 表：分型从合并 K 线的 CKLine.fx 标记直取。chan.py 成笔时已按课77
  步骤二/三消解候选分型（同性质相邻保留更极值者、间距/区间不满足成笔者丢弃），
  最终笔端点即幸存分型——有笔时 fx 表 = 首笔起点 + 每笔终点；全图无笔时
  （孤立分型，如 FX-002/003、INCLUDE-001/002/003）取全部 CKLine.fx 标记。
  idx 取该合并 K 线内极值所在原始 klu 的 idx（TOP 取最高高、BOTTOM 取最低低
  所在子 klu，与 CBi.get_*_klu 同一口径）；type：TOP→up、BOTTOM→down。
- sure 位置约定（替换 bi/zs/seg/bsp.is_sure 派生，对齐引擎"右侧确认"语义）：
  fx/bi/seg 表末位 sure=False、其余 True（单元素即末位 → False）；
  zs/bsp 表形成即 sure=True（恒 True）。
- BSP：bstype 取 type[0].main_type()（1/2/3）；dir = 操作方向（ADR-006）——
  买点（is_buy）→ up，卖点 → down；level 恒 1（单级别输入）。
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from enum import Enum
from typing import Any

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import DATA_FIELD, FX_TYPE, KL_TYPE
from Common.CTime import CTime
from KLine.KLine_Unit import CKLine_Unit

from chan_engine.spec.model import (
    Bar,
    Bi,
    BSPoint,
    Direction,
    FX,
    NormalizedChart,
    Segment,
    ZhongShu,
)

SOURCE = "chanpy"
_KL_TYPE = KL_TYPE.K_DAY
_BASE_DATE = date(2000, 1, 1)

# 顶层配置项（CChanConfig 直接属性），全部入快照
_TOP_LEVEL_KEYS = (
    "trigger_step",
    "skip_step",
    "kl_data_check",
    "max_kl_misalgin_cnt",
    "max_kl_inconsistent_cnt",
    "auto_skip_illegal_sub_lv",
    "print_warning",
    "print_err_time",
    "mean_metrics",
    "trend_metrics",
    "macd_config",
    "cal_demark",
    "cal_rsi",
    "cal_kdj",
    "rsi_cycle",
    "kdj_cycle",
    "demark_config",
    "boll_n",
)


def _dump(value: Any) -> Any:
    """配置值 → JSON 可序列化：Enum 取 str 值（否则名字），inf 转字符串。"""
    if isinstance(value, Enum):
        return value.value if isinstance(value.value, str) else value.name
    if isinstance(value, float) and math.isinf(value):
        return "inf" if value > 0 else "-inf"
    if isinstance(value, dict):
        return {k: _dump(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_dump(v) for v in value]
    return value


def _config_snapshot(conf: CChanConfig) -> dict:
    """从实例化后的 CChanConfig 上读取全部配置项，保证快照=实际运行配置。"""
    snapshot = {key: _dump(getattr(conf, key)) for key in _TOP_LEVEL_KEYS}
    snapshot["bi"] = _dump(vars(conf.bi_conf))
    snapshot["seg"] = _dump(vars(conf.seg_conf))
    snapshot["zs"] = _dump(vars(conf.zs_conf))
    bsp = dict(vars(conf.bs_point_conf.b_conf))
    bsp.pop("tmp_target_types", None)  # 与 target_types 重复，去噪
    snapshot["bsp"] = _dump(bsp)
    return snapshot


def _bar_to_klu(bar: Bar, pos: int) -> CKLine_Unit:
    """Bar → chan.py CKLine_Unit；时间按投喂位置合成（见模块 docstring）。"""
    day = _BASE_DATE + timedelta(days=pos)
    return CKLine_Unit(
        {
            DATA_FIELD.FIELD_TIME: CTime(day.year, day.month, day.day, 0, 0),
            DATA_FIELD.FIELD_OPEN: float(bar.o),
            DATA_FIELD.FIELD_HIGH: float(bar.h),
            DATA_FIELD.FIELD_LOW: float(bar.l),
            DATA_FIELD.FIELD_CLOSE: float(bar.c),
            DATA_FIELD.FIELD_VOLUME: float(bar.vol),
        }
    )


class ChanPyAdapter:
    """chan.py（third_party/chanpy vendor）→ NormalizedChart。"""

    name = SOURCE

    def __init__(self, config_overrides: dict | None = None):
        # 默认配置：trigger_step=True（逐帧投喂前提）+ bi_fx_check=loss（ADR-001 口径 B）；
        # overrides 仅供后续偏差实验
        self._conf_dict = {"trigger_step": True, "bi_fx_check": "loss"}
        if config_overrides:
            self._conf_dict.update(config_overrides)
        # CChanConfig 会消费（del）传入 dict 的键，必须每次给新副本
        self.config_snapshot = _config_snapshot(CChanConfig(dict(self._conf_dict)))

    def run(self, bars: list[Bar]) -> NormalizedChart:
        conf = CChanConfig(dict(self._conf_dict))
        chan = CChan(code="synthetic", lv_list=[_KL_TYPE], config=conf)
        for pos, bar in enumerate(bars):
            chan.trigger_load({_KL_TYPE: [_bar_to_klu(bar, pos)]})
        return self._extract(chan)

    @staticmethod
    def _dir(is_up: bool) -> Direction:
        return Direction.UP if is_up else Direction.DOWN

    def _extract(self, chan: CChan) -> NormalizedChart:
        kl = chan[0]  # 单级别：唯一 CKLine_List
        chart = NormalizedChart()

        bi_list = list(kl.bi_list)
        for bi in bi_list:
            chart.bi.append(
                Bi(
                    start_idx=bi.get_begin_klu().idx,
                    end_idx=bi.get_end_klu().idx,
                    dir=self._dir(bi.is_up()),
                    sure=True,  # 位置约定在循环后统一应用
                    source=SOURCE,
                )
            )
        _apply_positional_sure(chart.bi)

        # FX 表（规则见模块 docstring）：有笔时取笔端点（=课77 步骤二/三消解后的
        # 幸存分型），无笔时直取全部 CKLine.fx 标记（孤立分型）。
        if bi_list:
            # 首笔起点分型：上升笔起于底分型，下降笔起于顶分型
            first = bi_list[0]
            chart.fx.append(
                self._fx_at_klc(
                    first.begin_klc,
                    Direction.DOWN if first.is_up() else Direction.UP,
                )
            )
            # 每笔终点分型：上升笔终于顶分型，下降笔终于底分型
            for bi in bi_list:
                chart.fx.append(
                    self._fx_at_klc(
                        bi.end_klc,
                        Direction.UP if bi.is_up() else Direction.DOWN,
                    )
                )
        else:
            for klc in kl.lst:
                if klc.fx == FX_TYPE.TOP:
                    chart.fx.append(self._fx_at_klc(klc, Direction.UP))
                elif klc.fx == FX_TYPE.BOTTOM:
                    chart.fx.append(self._fx_at_klc(klc, Direction.DOWN))
        _apply_positional_sure(chart.fx)

        seg_list = list(kl.seg_list)
        for seg in seg_list:
            chart.seg.append(
                Segment(
                    start_bi=seg.start_bi.idx,
                    end_bi=seg.end_bi.idx,
                    dir=self._dir(seg.is_up()),
                    sure=True,  # 位置约定在循环后统一应用
                    source=SOURCE,
                )
            )
        _apply_positional_sure(chart.seg)

        for zs in kl.zs_list.zs_lst:
            chart.zs.append(
                ZhongShu(
                    zd=float(zs.low),
                    zg=float(zs.high),
                    start_idx=zs.begin.idx,
                    end_idx=zs.end.idx,
                    level=1,  # 单级别输入，中枢级别恒为 1
                    sure=True,  # 中枢形成即确认
                    source=SOURCE,
                )
            )

        for bsp in kl.bs_point_lst.getSortedBspList():
            chart.bsp.append(
                BSPoint(
                    idx=bsp.klu.idx,
                    bstype=int(bsp.type[0].main_type()),
                    dir=Direction.UP if bsp.is_buy else Direction.DOWN,  # 操作方向（ADR-006）
                    level=1,
                    sure=True,  # 买卖点形成即确认
                    source=SOURCE,
                )
            )

        return chart

    @staticmethod
    def _fx_at_klc(klc, fx_type: Direction) -> FX:
        """合并 K 线上的分型 → 归一 FX：idx 取极值所在原始 klu（顶取最高高、底取最低低）。"""
        if fx_type is Direction.UP:
            peak = klc.get_high_peak_klu()
        else:
            peak = klc.get_low_peak_klu()
        return FX(idx=peak.idx, type=fx_type, sure=True, source=SOURCE)
