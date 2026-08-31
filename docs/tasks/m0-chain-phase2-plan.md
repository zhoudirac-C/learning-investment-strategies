# M0-Chain Phase 2 实施计划：跟踪引擎（引擎 B）

> 上游设计文档：`docs/tasks/m0-chain-industry-tracking.md` Phase 2（T9-T16）
> 日期：2026-08-31

## 现状确认（Phase 1 已完成）

- `knowledge/industry-chains/` 下 19 条产业链 chain.yaml 全部通过 schema 校验，
  均含 `tracking_metrics` / `current_stage` / `falsification`，`history` 均待建。
- `config/stock_monitor/chain_registry.yaml`（16 条）为 Phase 1 登记清单，
  其 tracking_metrics 已同步进各 chain.yaml。

## 关键决策（与任务书有出入处）

1. **匹配源用 chain.yaml，不用 chain_registry.yaml**：chain.yaml 是 schema 校验过的
   知识库正本（T13 要回写的也是它），tracking_metrics/mappings/segments 齐全；
   registry 无代码读写、字段口径不同（股票代码带 .SZ/.SH 后缀）。避免双源不一致。
2. **LLM 通道**（2026-08-31 二次修订）：任务书写的 `model_route` cheapest/smartest
   在代码中不存在。第一版复用 `blindtest.replay.call_deepseek`（.env sensenova →
   GLM 兜底）；**现已改为优先走 Hermes 全局模型配置**（`resolve_runtime_provider()`
   与 cron 调度器同函数，跟随 `config.yaml model.default`，不写死），.env 通道
   降为兜底，`CHAIN_TRACKER_LLM=glm` 保留为逃生口。用户决策：cron 化 + 共享全局配置。
3. **期货行情源改用新浪**：东财 push2 本机实测不可达（含已知可用的 A 股 fs 也断），
   新浪 `hq.sinajs.cn/list=nf_XX0` 主力连续合约实测可用。品种映射：
   CU0/AL0→copper-aluminum，J0/JM0/RB0→coal-coke，SI0→photovoltaic。
4. **跟踪范围**：知识库全部 19 条链（含 watch 态）——watch 链正是为了等信号，
   匹配成本相同，只有命中才花 LLM 调用。

## 模块结构

```
src/investment_engine/chain_tracker/
├── __init__.py
├── dedup.py       # T10 ProcessedItemsDB：SQLite，info_id 主键去重 + 48h TTL
├── items.py       # 信息归一化：report/notice/futures → InfoItem(info_id 提取规则)
├── matching.py    # T11 关键词/标的匹配 → (item, chain_id) pairs
├── analysis.py    # T12 5 步推理 prompt 构建 + LLM 调用 + 结果解析校验
├── state.py       # T13 chain.yaml 阶段更新 + history 追加（走 store.save_chain）
├── report.py      # T14 增量报告（仅变化链）+ ticks.jsonl
├── futures.py     # T15 新浪期货快照解析 + 异动检测（state 文件防抖）
└── core.py        # T9 run_tick 编排
scripts/chain_tracker.py   # 薄 CLI：--date/--offline/--no-llm/--dry-run
tests/investment_engine/test_chain_tracker_{dedup,matching,analysis,state,report,futures,core}.py
```

## 三条硬规则落实

- 去重键 = info_id：研报 `info_code`；公告取 url 中 `AN\d+`（缺失则 sha1(code+title+date)）；
  期货 `futures:{symbol}:{date}:{30min窗口}`。
- 空批次静默：无新信息 → 不调 LLM、不写报告（stdout 一行摘要 + ticks.jsonl 一条）。
- TTL 清理内置 tick 末尾：`DELETE WHERE processed_at < now-48h`。

## 状态更新护栏（T13）

- 仅当 LLM `stage_change ∈ {forward, backward}` 且 new_stage 合法才回写。
- 阶段一次最多走一格（防 LLM 幻觉跳变，超出则截断到相邻阶段并记录）。
- 回写字段：`current_stage` / `stage_confidence` / `stage_evidence` /
  `timing.current_recommendation` + 追加 `history {date, stage, action, result: 待验证}`。
  `last_verified` 与 `timing.next_trigger` 不动（属人工确认域）。

## 期货异动判定（T15）

- 变动% =（最新价 − 昨结）/ 昨结；|变动| ≥ 2%（可调）触发。
- 防抖 state 文件 `futures_state.json`：同品种同日内仅当 |变动| 较上次告警扩大 ≥1pp 才重复告警。

## 验收对应（T16）

- 幂等：`--date 2026-08-28 --offline` 跑两遍，第二遍 LLM 调用数 = 0。
- 一致性：真实 LLM 跑一天数据，人工（我）抽查判断与 LLM 结论一致率。
- 全量 pytest 绿（live 测试单独 mark，默认跳过）。
