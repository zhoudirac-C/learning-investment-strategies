# 产业链逻辑演化提案 实现计划

日期：2026-08-31
设计：`docs/superpowers/specs/2026-08-31-chain-logic-evolution-design.md`
方式：TDD（每任务先红后绿）；测试目录 `tests/investment_engine/`，运行 `python -m pytest tests/investment_engine/ -k chain`

## 任务分解

### T1 evolution.py：change_type 枚举 + parse_logic_update
- 新建 `src/investment_engine/chain_tracker/evolution.py`：
  - `CHANGE_TYPES = ("refine_segment","add_node","focus_shift","update_thesis","update_falsification","add_relation")`
  - `parse_logic_update(result: dict) -> dict | None`：从 analyze_chain 结果提取 `logic_update`；`verdict=="irrelevant"`、change_type 非法、detail 非 dict、summary 空、detail 缺关键字段 → None；confidence 归一（∉高/中/低→"中"）。
  - detail 关键字段校验：refine_segment→`segment_id`；add_node→`metric` 或 `stock` 至少其一；focus_shift→`to_segment`；update_thesis→`new_thesis`；update_falsification→`add` 非空 list；add_relation→`target`+`relation`。
  - `_target_key(change_type, detail)`：refine_segment→segment_id；add_node→metric名 或 stock.code 或 stock.name；focus_shift→to_segment；update_thesis→"thesis"；update_falsification→"falsification"；add_relation→target。
  - `proposal_id(chain_id, change_type, target_key)` → `"{chain_id}:{change_type}:{target_key}"`。
- 测试 `tests/investment_engine/test_chain_tracker_evolution.py::TestParseLogicUpdate`：6 类合法通过；各非法分支返回 None；confidence 归一；verdict=irrelevant 丢弃。

### T2 evolution.py：pending 持久化 + 去重合并
- `default_pending_path()` → `infra/data/chain_tracking/evolution_pending.json`（经 report.default_tracking_dir）。
- `load_pending/save_pending/upsert_pending`（形状对齐 proposals.py 的同名函数）。
- upsert 去重键 = proposal_id；命中已有：合并 `source_info_ids` 与 `evidence`（按 info_id 去重，cap 50）、刷新 `last_evidence_at`，返回空新增；未命中：补 `proposal_id/proposed_at` 追加。
- 审计：复用 `proposals.append_daily_audit`，给它加 `prefix="proposals"` 默认参数，evolution 传 `prefix="evolution"` → `evolution_<date>.json`。
- 测试 `TestUpsertPending`：新增/命中合并/不同 target_key 并存/审计文件名。

### T3 evolution.py：apply_evolution + confirm/reject
- `apply_evolution(chain, proposal, *, today) -> dict`：就地合并并返回变更摘要；history 追加 `{date, stage: chain["current_stage"], action: "演化:<change_type> <summary>", result: "待验证"}`。
  - add_node：tracking_metrics 按 `metric` 去重 append；mappings 按 `code` 去重 append（无 6 位 code 的标的跳过，对齐 proposals._proposal_to_chain 哲学；elasticity 标 "concept"）。
  - refine_segment：按 `segment_id` 找环节，materials 去重 extend；找不到则新增 `{id, name: segment_name or segment_id, materials}`。
  - focus_shift：`timing.next_trigger/risk` 更新（有值才覆盖）；`stage_evidence` 追加附注。
  - update_thesis：替换 `thesis`。
  - update_falsification：`add` 逐条去重 append；`remove` 按文本精确移除。
  - add_relation：按 `(target, relation)` 去重 append。
- `confirm_evolution(proposal_id, *, pending_path, base_dir, today)`：`store.save_chain`（schema 强校验，非法抛错不写入）+ 从 pending 移除；`reject_evolution(proposal_id, ...)` 移除返回。
- 测试 `TestApplyEvolution`（6 类合并 + 幂等去重 + history + validate_chain 通过）与 `TestConfirmReject`（落盘/移除/报错分支）。

### T4 analysis.py：prompt 加 Step 6 + parse 扩展
- `_USER_TMPL` 追加 Step 6 演化判断说明（结构性增量 vs 阶段信号的区分硬约束、每批最多 1 条、默认 null）与输出字段 `"logic_update"`。
- `parse_analysis`：`logic_update` 缺失/非 dict/change_type 非法/verdict=irrelevant → 置 None 保留字段（不 raise，只丢提案）；合法则保留。主字段解析行为不变。
- 测试扩展 `test_chain_tracker_analysis.py`：prompt 含 "Step 6"；parse 合法保留/非法 None/缺失 None；原有用例不回归。

### T5 core.py 接线
- `run_tick`：`analyze_chain` 成功后 `parse_logic_update(result)`；非 None 时 proposal 附 `source_info_ids`（本批 info_id）与 `evidence`（date/info_id/title/source）；非 dry_run → `upsert_pending` + `append_daily_audit(prefix="evolution")`；`summary["evolution_proposals"]` 收集。
- `ticks.jsonl` 加 `evolution`（proposal_id 列表）。
- 日报：`report.append_daily_report` 加可选参数 `evolution=None`；`render_evolution_section(proposals, tick_label)`；changes 与 evolution 同时为空才静默（保持"空批次静默"硬规则）。
- `scripts/chain_tracker.py` stdout 打印演化提案行。
- 测试扩展 `test_chain_tracker_core.py`：fake call_fn 返回含 logic_update 的 JSON → pending 落账 + summary 计数；dry_run 不写；irrelevant 不落；日报含演化附节。

### T6 CLI：evolution 子命令
- `scripts/chain_tracker.py` 复用 chain_discovery 的 `parse_known_args` 子命令模式：
  `evolution list` / `evolution confirm <proposal_id>` / `evolution reject <proposal_id>`。
- 手动 smoke：`list` 空池、`confirm` 不存在 id 报错。

### T7 文档收尾
- `docs/tasks/m0-chain-industry-tracking.md` §3.4 后补一小节：引擎 B 增加演化提案能力（指向设计文档）。
- `scripts/chain_tracker.py` docstring 产物列表补 `evolution_pending.json` / `evolution_<date>.json`。
- AGENTS.md 无需改（cron 入口不变）。

## 验证

1. `python -m pytest tests/investment_engine/ -k chain -x -q` 全绿。
2. `python scripts/chain_tracker.py --offline --dry-run --date 2026-08-28` 无回归（行为兼容）。
3. 手动回放验证提案生成（依赖 LLM 通道，能跑则跑；不能跑则以单测 + parse 级回放为准，明确说明）。
