---
date: 2026-08-10
type: data-channel
status: done（2026-08-11 实施，见下方执行记录）
source: evals/shadow/attributions/2026-08-10.json
---

# KPL 情绪快照 + 资讯标题接入盲判数据包

## 分析

UP 复盘的分析地基是打板情绪与市场广度（涨停 99 家/连板 12 家/封板率 87.6%/上涨 4068 家/成交 2.52 万亿），这些字段在 KPL 情绪快照中全部存在且与 UP 引用值逐字段一致。但 `build_daily_pack`（`src/investment_engine/blindtest/dataset.py`）只含指数 K 线 + stock_pool 快照 + 静态配置，AI 对当日情绪结构完全失明；且 cron 时序 shadow(15:40) 先于 KPL 拉取(15:45)，当日数据时序上也不可得。

## 处置建议

1. `build_daily_pack` 增加 `emotion`（daban 核心字段白名单 + 连板梯队 + 风口名称）与 `news_titles`（当日资讯标题/时间/关联股票，不含全文）两个可选块，缺失时如实省略不编造；
2. cron 时序调整：KPL 拉取提前、shadow_daily 推后至 18:00 后（配合龙虎榜披露时间）；
3. `KNOWN_DATA_GAPS` 同步更新（移除已补项）。
