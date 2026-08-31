# M0-Chain Phase 3 实施计划：发现引擎（引擎 A）

> 上游设计文档：`docs/tasks/m0-chain-industry-tracking.md` Phase 3（T16-T22）
> 日期：2026-08-31

## 现状确认（Phase 2 已完成）

- `src/investment_engine/chain_tracker/`（dedup/items/matching/analysis/state/report/futures/core）
  + 薄入口 `scripts/chain_tracker.py`，测试 45 个全绿。
- 跟踪引擎每 30 分钟 tick：拉取 → 去重（processed_items.db 48h）→ 匹配 19 条 chain.yaml
  → LLM 5 步分析 → 阶段回写 + 增量日报。
- Phase 3（discovery/proposals/core/CLI）尚无任何代码，从零实现。

## 关键决策（与任务书有出入处）

1. **提议不落 chain_registry.yaml**：Phase 2 已决策"registry 无代码读写，chain.yaml 是
   知识库正本"。pending 提议落 `infra/data/chain_tracking/proposals_pending.json`
   （机器域），日产出审计 `proposals_<date>.json`（任务书指定）；人工 confirm 直接创建
   `knowledge/industry-chains/<chain_id>/chain.yaml`（schema 校验，跟踪引擎下一 tick
   自动纳入）。"active" 的 operational 定义 = chain.yaml 存在。
2. **LLM 通道**：`analysis.default_llm_call` 优先走 **Hermes 全局模型配置**
   （`resolve_runtime_provider()`，跟随全局不写死，2026-08-31 用户决策），
   .env sensenova → GLM 为兜底链；tag 区分 `chain_tracker` / `chain_discovery`。
   任务书"调 GLM-4-flash"的 cheapest 语义由全局配置承接（当前全局即 GLM 系）。
3. **触发源只有研报 + 公告标题关键词**（涨价/扩产/缺货/供需/产业链/深度/专题）：
   板块异动 API（东财 push2）Phase 2 实测本机不可达；期货异动品种全部在
   FUTURES_CHAIN_MAP 内（预分配已有链），不构成"无归属异动"。发现 tick 不拉期货
   （`collect_items(include_futures=False)`）。
4. **公告同关键词过滤**：公告标题含涨价/扩产等词的极少（实测每日 6342 条中个位数），
   不会灌爆 LLM 预算；不命中关键词的公告直接滤掉。
5. **批量一次 LLM 调用**（≤40 条/批，超出分批多调），输出 `{"proposals": [...]}`
   （0..3 条）而非任务书的单条——同日多条新闻聚类成一条提议正是发现引擎的价值。
6. **去重三层**：① `discovery_items.db` 48h 滑窗（独立于跟踪 DB——跟踪会把未匹配项
   落账，共用会抑制发现候选）；② prompt 内嵌已有链 + pending 提议清单（LLM 避免重复
   提议）；③ 后置过滤 chain_id/name 与已有链、pending 碰撞的提议。

## 模块结构

```
src/investment_engine/chain_tracker/
├── discovery.py        # T17 触发关键词过滤 + T18 发现 prompt 构建/解析 + T19 后置去重
├── proposals.py        # T20 提议持久化（pending JSON + 日产出审计）+ T21 confirm/reject
└── discovery_core.py   # T16 run_discovery 编排（复用 core.collect_items / load_chains）
scripts/chain_discovery.py   # 薄 CLI：scan（默认）/ list / confirm <id> / reject <id>
tests/investment_engine/test_chain_tracker_discovery{,_proposals,_core}.py
```

复用改动（最小）：
- `analysis.py`：`_fmt_items` → `format_items`（公开）；`_default_call` →
  `default_llm_call(messages, *, tag="chain_tracker")` 增加 tag 参数。
- `core.py`：`_collect_items` → `collect_items`（公开，加 `include_futures=True` 参数）；
  `_load_chains` → `load_chains`（公开）。

## 护栏

- 空批次静默：无候选 → 不调 LLM、不写提议文件（stdout 摘要 + discovery_ticks.jsonl）。
- LLM 失败不落账（同 Phase 2 教训：瞬时故障下一 tick 自愈重试）。
- 逐批即时落账：进程被杀不丢已完成批次的进度。
- 提议字段校验：chain_id 必须 slug、name/driver/thesis 必填，缺失则丢弃该条；
  current_stage 非法归一为 阶段0-观察，confidence 非法归一为 中。
- confirm 产物必须过 `store.save_chain` 的 schema 强校验；股票代码剥 .SZ/.SH 后缀，
  非 6 位数字的 mapping 跳过（诚实留空）。

## 验收对应（T22）

- 幂等：`--date 2026-08-28 --offline` 跑两遍，第二遍 LLM 调用数 = 0。
- 发现能力：真实 GLM 通道回放 2026-08-28 全天，产出 ≥ 1 条新产业链提议，
  且与已有 19 链不重复。
- 全量 pytest 绿。

## 增补（2026-08-31，用户确认）：候选池 + 证据累积

用户决策：提议不急着 confirm/reject 二选一，先在候选池（proposals_pending.json）
里躺一段时间，引擎持续累积相关新信息作为证据，证据够了人工再升级到观察列表。

- `discovery.build_pending_index`：pending 提议 → 匹配信号（复用
  `matching.extract_chain_signals`；提议的 stocks/key_nodes 是名称字符串，
  转成 chain.yaml 形状后走同一套提取）。
- 每个发现 tick：新信息先与 pending 提议匹配，命中即挂为证据
  （`proposals.attach_evidence`，按 info_id 去重，上限 50 条），落账
  `llm_verdict=evidence`，**不再进入发现候选**（不耗 LLM）。
- `list` 显示每条提议的证据数/最近证据日期，证据 ≥3 条提示可 confirm。
- confirm 语义改为"加入观察列表"：chain.yaml 一律 `阶段0-观察` + `stage_confidence=低`
  起步（LLM 初判阶段留痕在 stage_evidence），阶段推进交给跟踪引擎逐 tick 完成——
  避免 LLM 初判失真（实测 carbon-fiber 凭单家公司点评被判成 阶段2-加速期）。
