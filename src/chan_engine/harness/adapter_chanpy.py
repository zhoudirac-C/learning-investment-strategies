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
- BSP：bstype 按 ``bsp.type`` 逐 distinct ``main_type()`` 出一条（M5-1：同笔
  多类型合并场景如二买+三买 T2+T3B 各出一条，课21 二三类重合；同 main_type
  去重）；dir = 操作方向（ADR-006）——
  买点（is_buy）→ up，卖点 → down；level 恒 1（单级别输入）。
- ZS：chanpy normal 模式直取（seg 内构造）；M5-2 起叠加「跨 seg 延伸试探 +
  九段升级」后处理（门控=延伸后范围内笔数≥9 且 3 子中枢重合，课33）。
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


def _apply_positional_sure(table: list) -> None:
    """按位置约定就地写 sure 字段（规则源自全部 expect 语料，见模块 docstring）。

    - fx/bi/seg 表：末位 sure=False、其余 True；空表与单元素表（单元素即末位）→ 全 False
    - zs/bsp 表：形成即 sure=True（恒 True，本函数不处理这两类）

    本函数仅作用于 fx/bi/seg；调用方在循环内把每个元素的 sure 占位为 True，
    循环结束后调本函数把末位翻为 False，与归一约定对齐。
    """
    n = len(table)
    if n == 0:
        return
    for i, elem in enumerate(table):
        elem.sure = i < n - 1  # 末位 False，其余 True


def _distinct_main_types(bsp_type_list) -> list[int]:
    """``bsp.type``（BSP_TYPE 列表）→ distinct main_type int 列表，保持原顺序。

    chanpy 把同笔多个买卖点合并进同一 CBS_Point（如二买+三买重合 T2+T3B，
    课21 / claim-20070109-001-b），多类型信息保留在 type 列表中；归一表按
    每个 distinct main_type 出一条 BSPoint（M5-1，M4 评估 §2 UP 批准的
    B 类补偿）。同 main_type 去重（T1/T1P 理论可同挂一笔，M4-2 评审提示）。
    """
    seen: list[int] = []
    for t in bsp_type_list:
        mt = int(t.main_type())
        if mt not in seen:
            seen.append(mt)
    return seen


def _bi_low_high(bi: Bi, bars: list[Bar]) -> tuple[float, float]:
    """笔的极值（与 czsc 适配器 _bi_low_high 同口径；两适配器刻意各自持有
    小辅助函数保持独立，先例：_apply_positional_sure 双份持有）。

    上升笔：low=起点 K 线 low，high=终点 K 线 high；下降笔反之。
    """
    if bi.dir is Direction.UP:
        return float(bars[bi.start_idx].l), float(bars[bi.end_idx].h)
    return float(bars[bi.end_idx].l), float(bars[bi.start_idx].h)


def _has_overlap_strict(low1: float, high1: float, low2: float, high2: float) -> bool:
    """严格重叠（不含边界），对齐 chanpy has_overlap(equal=False)。"""
    return high2 > low1 and high1 > low2


def _apply_nine_bi_upgrade_with_extension(
    zs_list: list[ZhongShu], bi_table: list[Bi], bars: list[Bar]
) -> None:
    """跨 seg 延伸试探 + 九段升级（课33，claim-20070302-001-b；M5-2，
    M4 评估 §3 UP 批准的复合 B 补偿）。

    chanpy 中枢受 seg 切分限制不跨 seg 延伸（ZS.combine :118），九段升级
    在单 seg 内永不触发（全语料实测 zs 内笔数最多 3）。补偿口径（与 M4-3
    探针演算一致）：

    1. **延伸试探**：自 zs.end_idx 起按 bi_table 顺序逐笔与 [zd,zg] 判严格
       重叠，重叠则试探性延展 end；遇未确认笔（sure=False，位置约定下即
       末位笔）或首笔不重叠即停（对齐 M2-3 czsc 延伸口径）。
    2. **门控（唯一落改条件）**：试探后范围内笔数 ≥9，且前 9 笔分 3 组
       （每组 3 笔）子中枢各自成立（sub_zg > sub_zd），且 3 子中枢重合区间
       成立（max(sub_zd) < min(sub_zg)）。
    3. **落改**：zd/zg = 重合区间，end_idx = 试探终点，level = 2；门控不
       通过则 zs 逐字段不变——延伸只是升级判定的内部试探，不单独落改
       （bsp-002/bsp-004/seg-005 触发试探但门控不通过，输出逐字节不变，
       M4 §3 半径实证）。
    """
    for zs in zs_list:
        if zs.level != 1:
            continue
        # 1. 延伸试探（不落改）
        probe_end = zs.end_idx
        for bi in bi_table:
            if bi.end_idx <= zs.end_idx:
                continue  # 已在范围内的笔跳过（归一笔表首尾相接）
            if not bi.sure:
                break  # 末位未确认笔不延伸（对齐 M2-3 czsc 口径）
            low, high = _bi_low_high(bi, bars)
            if not _has_overlap_strict(zs.zd, zs.zg, low, high):
                break  # 首笔不重叠即停（延伸连续语义）
            probe_end = bi.end_idx
        # 2. 门控：范围内笔数 ≥9 且 3 子中枢重合
        in_range = [
            bi
            for bi in bi_table
            if bi.start_idx >= zs.start_idx and bi.end_idx <= probe_end
        ]
        if len(in_range) < 9:
            continue
        nine_bis = in_range[:9]
        sub_ranges: list[tuple[float, float]] = []
        for i in range(0, 9, 3):
            lows, highs = [], []
            for bi in nine_bis[i : i + 3]:
                low, high = _bi_low_high(bi, bars)
                lows.append(low)
                highs.append(high)
            sub_zd, sub_zg = max(lows), min(highs)
            if sub_zg <= sub_zd:
                break  # 子中枢不成立
            sub_ranges.append((sub_zd, sub_zg))
        if len(sub_ranges) != 3:
            continue
        level2_zd = max(r[0] for r in sub_ranges)
        level2_zg = min(r[1] for r in sub_ranges)
        if level2_zg <= level2_zd:
            continue
        # 3. 落改
        zs.zd = level2_zd
        zs.zg = level2_zg
        zs.end_idx = probe_end
        zs.level = 2


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


class ChanPySession:
    """chan.py 增量会话：CChan 实例常驻，逐 bar 投喂逐 bar 可取图（M3-5）。

    与 ``ChanPyAdapter.run`` 同码路径（trigger_load 逐帧投喂），因此
    逐 bar 增量终态与一次性批量终态结构上一致（一致性测试为硬门）。
    """

    def __init__(self, conf_dict: dict):
        self._conf = CChanConfig(dict(conf_dict))
        self._chan = CChan(code="synthetic", lv_list=[_KL_TYPE], config=self._conf)
        self._pos = 0
        self._bars: list[Bar] = []  # 记录投喂 bars，供九段升级后处理取笔极值（M5-2）

    def push(self, bar: Bar) -> None:
        self._chan.trigger_load({_KL_TYPE: [_bar_to_klu(bar, self._pos)]})
        self._pos += 1
        self._bars.append(bar)

    def chart(self, adapter: "ChanPyAdapter") -> NormalizedChart:
        """抽取当前状态的归一五表（复用适配器归一逻辑）。"""
        return adapter._extract(self._chan, self._bars)


class ChanPyAdapter:
    """chan.py（third_party/chanpy vendor）→ NormalizedChart。"""

    name = SOURCE

    def __init__(self, config_overrides: dict | None = None):
        # 默认配置：trigger_step=True（逐帧投喂前提）+ bi_fx_check=loss（ADR-001 口径 B）
        # + bsp3_follow_1=False（M2-3：三买独立检出，不依赖一买先出现；
        #   GOLD-003/005 课文实例中三买出现前无一买，默认 True 会漏报）
        # overrides 仅供后续偏差实验
        self._conf_dict = {
            "trigger_step": True,
            "bi_fx_check": "loss",
            "bsp3_follow_1": False,
        }
        if config_overrides:
            self._conf_dict.update(config_overrides)
        # CChanConfig 会消费（del）传入 dict 的键，必须每次给新副本
        self.config_snapshot = _config_snapshot(CChanConfig(dict(self._conf_dict)))

    def run(self, bars: list[Bar]) -> NormalizedChart:
        session = self.new_session()
        for bar in bars:
            session.push(bar)
        return session.chart(self)

    def new_session(self) -> ChanPySession:
        """开增量会话（M3-5）：逐 bar push，随时 chart 取当前归一图。"""
        return ChanPySession(self._conf_dict)

    @staticmethod
    def _dir(is_up: bool) -> Direction:
        return Direction.UP if is_up else Direction.DOWN

    def _extract(self, chan: CChan, bars: list[Bar]) -> NormalizedChart:
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
                    level=1,  # 单级别恒 1；九段升级后处理（下方）可升 2
                    sure=True,  # 中枢形成即确认
                    source=SOURCE,
                )
            )
        _apply_nine_bi_upgrade_with_extension(chart.zs, chart.bi, bars)

        # BSP 表（M2-3：基于末位笔的 bsp 不入表——末位笔 sure=False 未确认，
        # 其衍生 bsp 也未确认，与 expect "只列确认 bsp" 口径对齐）。
        # bsp.bi.idx 是产出该 bsp 的笔在 bi_list 中的 idx，与 chart.bi 索引一致。
        for bsp in kl.bs_point_lst.getSortedBspList():
            bi_idx = bsp.bi.idx
            # 跳过基于未确认笔（末位笔）的 bsp：chart.bi[bi_idx].sure=False
            if bi_idx < len(chart.bi) and not chart.bi[bi_idx].sure:
                continue
            for bstype in _distinct_main_types(bsp.type):
                chart.bsp.append(
                    BSPoint(
                        idx=bsp.klu.idx,
                        bstype=bstype,
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
