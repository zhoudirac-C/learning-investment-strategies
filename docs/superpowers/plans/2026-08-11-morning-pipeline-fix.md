# 早盘分析链路修复与信息源扩容 实施计划

对应 spec：`docs/superpowers/specs/2026-08-11-morning-pipeline-fix.md`（2026-08-11 已确认）
创建：2026-08-11

## 任务

- [x] T1 (P0-1) `nodes.py` market_summary 可靠性：fallback 原因区分 + 降级数据填充
  （规则拼装指数/量能/情绪/板块榜，phase 保持"未配置"，themes 保持 []）+ 空返回重试一次
  + `_render_market_summary_text` summary 截断 200→500；单测覆盖三种失败路径
- [x] T2 (P0-2) 日期硬约束：market_summary context + style_writer prompt 注入
  today（YYYY-MM-DD 星期X）；reviewer.txt 加日期一致性检查
- [x] T3 (P0 收尾) ~~重启本地 uvicorn~~（agent 在云端，重启由云端同步管线
  `bin/run_sync_pipeline.sh` Step4 负责，推送后下个同步周期生效）+
  `pytest tests/test_stock_monitor.py` 55 passed + 全量绿 + commit
- [x] T4 (P1-1) `us_map.yaml` + `src/investment_engine/overnight_us.py` +
  `scripts/overnight_us_fetch.py` + 单测 + cron 08:20 + snapshot 接入
- [x] T5 (P1-3) `src/investment_engine/limit_pool.py` + `scripts/limit_pool_fetch.py` +
  单测 + cron 15:37 + 盲判包接入 + snapshot `limit_pool_yesterday`
- [x] T6 (P1-2+P2-2) `auction_digest`（竞价涨停+竞价额 top，09:25-09:40 窗口）+
  `post_close_alerts`（昨日 KPL 资讯关键词过滤）接入 snapshot
- [x] T7 (P2-1) 6 份模式提案（framework/proposals/2026-08-11-*.md，证据引历史复盘）
- [x] T8 (P3) `evals/morning/` 约定 + 今日归因存档 + 流程文档
- [x] T9 plan 归档（checkbox+执行记录）+ spec 转 done + 收尾 commit

## 执行记录

| 任务 | commit | 结果 |
|---|---|---|
| T1-T3 | 265873f | test_market_summary_fallback 8 passed；test_stock_monitor 55 passed |
| T4 | f82029e | 3 passed；实拉 11/11（COHR -14.2%/LITE -8.6%，与 UP 引用一致）；批量接口替代单股规避限流；FNVR 无覆盖移除 |
| T5 | 0032d63 | 4 passed；实拉 08-10（涨停99/炸板14/高度5板/梯队正确） |
| T6 | fc6ae0c | 7 passed；全量 254 passed |
| T7 | 47a7049 | 6 份提案，均 proposed 待窗口验证 |
| T8 | efed3fe | evals/morning/README + attributions/2026-08-11.md |
| T9 | 见本次 commit | 18:05 shadow 包预检：67,298 字符、防泄漏过、missing=None |
