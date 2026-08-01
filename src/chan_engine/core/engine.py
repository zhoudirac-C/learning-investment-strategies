"""M3-4: 递归层引擎（校准矩阵第三实现，name="recursion"）。

管线：bars → [chanpy 适配器] fx/bi 单级别归一 → [core] L0 走势类型 →
多级 zs/bsp → 归一五表。

集成口径（以 6 个 M3 降级用例为验收锚）：
- **fx/bi 表**：委托 chanpy 适配器（其构造已在 M2 与 expect 语料对齐），
  仅把 source 改写为 recursion；
- **seg 表**：递归层自建 L0 走势类型（core.segments，不依赖适配器 seg——
  chanpy 对 BC-002 九笔并一段、czsc 无 seg）；
- **zs 表**：三件套 中枢段→level-2、离开段→level-1（core.levels）；
  未被三件套消费的已确认段，内部三笔重叠 → level-1 中枢
  （BSP-003 锚：bi0-2 重叠 (11.4, 14.0, 1→16)）；
- **bsp 表**：背驰一买/一卖（core.backchi，多级区间套）+ 三类买卖点
  （离开中枢 + 第一次回试不破 ZG/ZD，课 20/21）。

与设计文档 §6 的关系：递归层独立于两库自建，不触碰 chanpy/czsc 适配器的
既有输出（第三列，不回归 M2 成果）。
"""

from __future__ import annotations

import dataclasses

from chan_engine.core.backchi import detect_backchi_bsp, detect_third_type_bsp
from chan_engine.core.fxlevel import detect_box_third_buy
from chan_engine.core.levels import synthesize_level_zs, synthesize_standalone_zs
from chan_engine.core.segments import build_l0_segments
from chan_engine.spec.model import Bar, NormalizedChart, Segment

SOURCE = "recursion"


class RecursionEngine:
    """递归层引擎：单级别归一（chanpy fx/bi）→ L0 段 → 多级 zs/bsp。

    遵循 harness 适配器协议（name / config_snapshot / run(bars)->NormalizedChart）。
    """

    name = SOURCE

    def __init__(self, bi_adapter=None):
        # 延迟导入：chanpy 需要 third_party/chanpy 在 sys.path（report.py 已保证）
        from chan_engine.harness.adapter_chanpy import ChanPyAdapter

        self._base = bi_adapter or ChanPyAdapter()
        self.config_snapshot = {
            "bi_fx_source": self._base.name,
            "l0_rule": "greedy-3bi + directional-extension（创极值则吸收）",
            "zs_rule": "三件套(中枢段→L2, 离开段→L1) + 独立已确认段→L1",
            "bsp_rule": "背驰(面积Σ|Δc|, 多级) + 三类(离开+第一次回试不破界)",
        }

    def run(self, bars: list[Bar]) -> NormalizedChart:
        base = self._base.run(bars)
        chart = NormalizedChart()
        chart.fx = [dataclasses.replace(f, source=SOURCE) for f in base.fx]
        chart.bi = [dataclasses.replace(b, source=SOURCE) for b in base.bi]

        segments = build_l0_segments(chart.bi, bars)
        chart.seg = [
            Segment(
                start_bi=s.start_bi,
                end_bi=s.end_bi,
                dir=s.dir,
                sure=s.sure,
                source=SOURCE,
            )
            for s in segments
        ]

        zs = synthesize_level_zs(segments, chart.bi, bars) + synthesize_standalone_zs(
            segments, chart.bi, bars
        )
        chart.zs = sorted(zs, key=lambda z: z.start_idx)

        bsp = detect_backchi_bsp(segments, chart.bi, bars) + detect_third_type_bsp(
            chart.zs, chart.bi, bars
        )
        # GOLD 兜底：笔级结构过粗（zs/bsp 双空）→ 日线箱体三买代理
        # （GOLD-001/002：课文日线三买的次级别为 30 分钟结构，日线笔不可达）
        if not chart.zs and not bsp:
            bsp = detect_box_third_buy(bars)
        # 同 idx 多条按 level 降序（大级别先报，对齐 BC-002 expect 的组内顺序：
        # diff 同主键 (idx,bstype,dir) 组内按列表顺序配对）
        chart.bsp = sorted(bsp, key=lambda b: (b.idx, b.bstype, -b.level))
        return chart
