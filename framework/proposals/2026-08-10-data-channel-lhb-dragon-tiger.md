---
date: 2026-08-10
type: data-channel
status: open
source: evals/shadow/attributions/2026-08-10.json
---

# 龙虎榜席位数据接入（KPL applhb）

## 分析

UP 复盘的资金结构分析（游资抱团、席位动向）依赖龙虎榜类数据，盲判数据包无任何席位/资金结构通道。KPL 已有现成接口：`c=UserBusiness&a=GetDay`（applhb 子域）返回分类游资榜（顶级/一线/知名/机构/庄股）与当日上榜明细，符合龙虎榜 T 日收盘后披露规则（接口清单第 5 节，2026-08-10 已捕获实样）。用户要求复盘时间推后到 18:00 以覆盖披露窗口。

## 处置建议

1. `investment_engine/kpl/` 新增 lhb 模块（`GetDay` 拉取 + 落盘 `infra/data/kpl/lhb/<date>.json`），容忍空数据（非披露日/披露未出）如实记录；
2. `kpl_daily_fetch.py` 增加 `--skip-lhb` 反向开关，默认拉取；
3. 数据包只放轻量摘要（上榜股票 + 席位类别），原始响应落盘备查；
4. 披露时间边界实盘验证后写入 ops 文档。
