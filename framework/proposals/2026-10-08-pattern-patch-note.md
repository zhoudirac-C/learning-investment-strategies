---
date: 2026-10-08
type: pattern-patch
status: open
source: evals/shadow/attributions/2026-10-08.json
---

# 新增方向必须经过至少两日相对强度与持续性确认

## 分析

错因分两层。1）概念误用：cycle_state 多指数底部日期分歧已出现，AI 原文写『科创50底8/04、上证底10/08 vs 创业板指9/17』，却以『按科技主线锚定创业板指』取 rebound_day=10，这是选取对预设结论最有利的单一指数锚定；正确做法是给出区间或取中位并显式标注分歧。此外，global_macro 缺失时 AI 写『不可校验，故定性内生瓦解』，将『无法证伪外部冲击』当成『外生冲击不存在』，属概念/归因误用。2）步骤缺：新增方向 coke_coal_upcycle、green_power_ai_electric 仅凭当日净流入（煤炭7.96亿、电力27.82亿）和领涨即列为『新增』，偏离自身场景B『防御轮动末端亦转跌』的提示，未增加多日相对强度/补跌验证步骤。事后两方向均跑输：coal dir_ret -3.37%、green_power -5.32%，bench -3.35%，说明单日资金流入在调整初期不是可靠的新增方向信号。

## 处置建议

在 mainline_identification 与 volume_source_qualify 后增加 direction_persistence_check：新增方向需连续2日净流入且跑赢大盘；调整期防御方向在未出清前只观察、不新增。
