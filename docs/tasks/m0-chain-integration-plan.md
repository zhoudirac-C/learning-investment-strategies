# M0-Chain 系统接线计划：产业链状态接入现有监控/分析/评分链路

> 上游：`docs/tasks/m0-chain-industry-tracking.md` §四（与现有系统的对接）
> 日期：2026-08-31；触发：用户确认"开工"（四步接线，优先级 1→3→2→4）
> 状态：**四步全部完成**（测试结果见末节）

## 现状差距（探索确认）

- 监控 agent 的 `chain_scanner.py` 吃 `direction_pool.yaml` 的静态 industry_chain
  （含 pumped 标记），**不读** M0-Chain 的 chain.yaml——两套产业链数据并存。
- `factor_rank.py` 标的池 = watchlist.yaml themes[].stocks[]，无链阶段维度。
- 早盘/盘中/复盘 agent 的 LLM context 无产业链状态。
- 发现引擎缺"板块异动"触发源（东财板块 API 不可达）——✅ 已用本地
  `fund_flow` 落盘补上（chain_tracker/sector.py，concept.即时 387 概念，
  |涨跌幅|≥3% → 候选；日级快照，15:40 cron 落盘后首个 tick 生效）。

## 四步接线

### 步骤 1：agent context 注入链状态（核心价值）✅ 已完成

- `investment_engine.industry_chain.store.chain_states_view()`：19 链 compact 视图
  （chain_id/name/current_stage/stage_confidence/时机/前 3 标的，单链损坏跳过）。
- 挂载三处（均带 available=False 降级，不阻断主流程）：
  ① `monitor/scheduler/__init__.py` context_data（cron 主路径，format_agent_json_context
  透传自动带进 LLM JSON）
  ② `monitor/context/__init__.py` `_agent_context_data`（备用路径）
  ③ `agent/graph/nodes.py` market_summary context（早盘/盘中/收盘复盘全 trigger 覆盖，
  context dict 整体 json.dumps 进 prompt，超 128KB 由既有截断逻辑裁剪）
- stage 词汇原样透传（chain.yaml "阶段2-加速期" vs direction_pool "diverging"
  是两套口径，不做映射）。
- ✅ uvicorn 已重启，health 正常（2026-08-31 13:26）。
- ✅ 显性 prompt 引导（2026-08-31 14:40 补）：`market_summary.txt`【输入数据说明】
  加 industry_chain_states 字段文档 +【产业链状态使用规则】（阶段口径五档）；
  cron trigger 专属 prompt（cron_closing 等不含字段文档）由数据自描述兜底——
  `store.CHAIN_STATES_NOTE` 随 context 注入，全触发路径覆盖。重启后生效。

### 步骤 2：chain_scanner 增补知识库路径（不碰现有逻辑）✅ 已完成

- direction_pool 路径**保持不动**（pumped 标记是其独有运营状态）。
- 新增 `ChainAwareScanner.find_alternatives_from_kb()`：direction_pool 无配置或
  扫描为空时，按涨停股代码在 chain.yaml mappings 定位链+环节，推荐**同链其他
  环节**标的；阶段0 的链不推荐。context 层在原 chain_alternatives 为空时调用。

### 步骤 3：板块异动触发器 ✅（已完成）

chain_tracker/sector.py + discovery_core 接线；is_discovery_candidate 对
source=sector 直通；info_id=sector:{date}:{type}:{name} 日级去重。

### 步骤 4：factor_rank 标的池按链阶段过滤 ✅ 已完成

- `store.stage0_only_codes()`：只属于阶段0链的标的集合（同属多条链时有一条
  非阶段0就保留）。
- `scripts/factor_rank.py` 去重后默认过滤，`--no-chain-filter` 关闭，打印排除清单。
- 实测（2026-08-31）：`--theme photovoltaic_low_recovery` 排除爱旭/晶澳
  （光伏链阶段0），隆基不在任何链 → 保留；真实 KB 当前 7 只阶段0-only 标的。

## 验收

- ✅ 每步带测试：`test_chain_tracker_sector.py`（4）+ discovery_core 板块用例 +
  `test_industry_chain_store.py`（chain_states_view/stage0_only_codes 3）+
  `test_chain_scanner.py`（KB fallback 3）+ analysis 通道优先级（4）。
- ✅ `tests/test_stock_monitor.py` + `tests/test_chain_scanner.py` +
  `tests/investment_engine/` 共 650 全绿。
- ✅ uvicorn 重启后 health 正常（链状态注入对早盘/复盘 trigger 生效）。
- ✅ factor_rank 真实运行确认排除清单打印正确。
