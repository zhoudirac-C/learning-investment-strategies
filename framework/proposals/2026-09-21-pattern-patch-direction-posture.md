---
date: 2026-09-21
type: pattern-patch
status: open
source: evals/shadow/attributions/2026-09-21.json
---

# direction posture与顶部结构硬约束联动

## 分析

错因核心为概念误用，共两处：①cycle_state存在多指数底部日期分歧（创业板指rebound_day=2/bottom_date=2026-09-17、科创50 rebound_day=34/bottom_date=2026-08-04、上证rebound_day=36/bottom_date=2026-07-31），AI未按正确做法给出区间或取中位，而是以“科技主线锚定值”单点选取创业板指作为唯一口径，支撑“反弹中段”的乐观预设；科创50/上证均已远超2天窗口的事实只在note中被降格为“旧周期延续”，没有作为风险条件参与direction选择，构成审计项“对预设结论最有利的单一指数锚定”。②direction选择对“隔夜外盘映射”框架用错场景：memory_nor/optical_communication前一日已分别有普冉股份+10.06%、兆易创新+4.95%、中际旭创+3.40%等涨幅，且上证60min顶部（2026-09-10）与120min顶部（2026-09-03）、科创50/创业板td9向上count=6/5均未失效，AI仍基于美光+3.92%、闪迪+10.99%、COHR+7.22%给出memory_nor“加强”、optical_communication“维持”；事后9-21两方向收益-7.32%/-11.45%，均跑输基准-4.28%，说明在反弹窗口早期+高位压制未消解场景下，外盘映射打开的是兑现/反转风险而非延续机会。scenarios虽设置“高开低走”分支，但未将其作为direction posture的前置否决，方向选择与阶段技术风险脱节，属于框架用错场景。当日缺席数据为无，不涉及数据缺；未依赖非公开渠道信息，不涉及信息差。

## 处置建议

在direction选股规则中加入强制门槛：上证60min/120min顶部、科创50/创业板td9向上未完成（count未归零）任一存在时，所有direction不得标记“加强”；必须等结构invalidated或新底部形成后再升级。
