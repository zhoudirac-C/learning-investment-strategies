# 产业链逻辑演化提案（Chain Logic Evolution）设计

日期：2026-08-31
状态：设计（brainstorm 产出）
关联：`docs/tasks/m0-chain-industry-tracking.md`（M0-Chain 双引擎）、`framework/proposals/2026-08-30-industry-chain-tracking-pipeline.md`

## 1. 背景与问题

M0-Chain 现有双引擎覆盖了两件事：

- **跟踪引擎**（`chain_tracker.py` → `chain_tracker/core.py`）：新信息匹配到已有链后，LLM 按 UP 5 步推理框架只判断**阶段变化**（forward/backward/unchanged），自动回写 `current_stage/stage_confidence/stage_evidence/timing.current_recommendation/history`。
- **发现引擎**（`chain_discovery.py` → `chain_tracker/discovery_core.py`）：从触发词过滤后的新信息里发现**全新产业链**，落 `proposals_pending.json`，人工 confirm 建 chain.yaml。

缺口：chain.yaml 的**逻辑结构本身**——`thesis`（产业逻辑）、`segments`（环节拆解）、`mappings`（标的）、`tracking_metrics`（关键节点）、`timing.next_trigger/risk`、`falsification`、`chain_relations`——建立之后就冻结了，只能靠人工手改。

但 UP 的实际工作方式里产业链逻辑是持续演变的（任务书 §1.1 自己的例子：CCL 链 6 月做上游材料 → 7 月转向中游 CCL → 8 月底准备转向下游 PCB；`ai-pcb-ccl/chain.yaml` 现状也是演化产物——上游材料后来细化出"硅微粉/球形硅"，mappings 后加了中钨高新-钻针节点）。UP 每日观点（`sources/raw/财经/`）里同样频繁出现环节重心迁移、新增受益环节的表述。

**管线缺的正是这第三层能力：识别"新信息补充/改变了产业链逻辑本身"，并生成提案。**

## 2. 目标与非目标

### 目标

1. 跟踪 tick 内，LLM 在阶段判断之外顺带判断：这批新信息是否给产业链逻辑带来**结构性增量**（细化环节 / 新增节点 / 重心转移 / 修正 thesis / 更新证伪条件 / 新增跨链传导）。
2. 有结构性增量 → 生成**演化提案**，落 pending 池（机器域正本，gitignored），不自动改 chain.yaml。
3. 人工 review 后 `confirm` 应用到 chain.yaml（schema 强校验兜底），`reject` 移除。
4. 提案去重防抖：同一待定提案不重复占位，命中只累积证据。

### 非目标

- 不改变阶段自动推进的现有行为（走一格护栏不变）。
- 不让 LLM 直接改 chain.yaml（人工确认哲学，对齐任务书决策 4）。
- 不接入 UP claims 自动分析；UP 侧继续走 `chain_up_compare.py` 人工对比（演化机制按输入源无关设计，后续可复用接入，见 §7）。
- 不引入新数据源、不改发现引擎。

## 3. 方案总览

```
跟踪 tick（core.run_tick）
  └─ analyze_chain(chain, items)          ← 现有：5 步推理 + 阶段判断
       └─ prompt 增加 Step 6（可选输出）   ← 新增：逻辑演化判断
            └─ logic_update: null | {change_type, summary, detail, rationale, confidence}
  └─ parse 后若 logic_update 合法
       └─ evolution.upsert_pending()       ← 新增：去重合并 → evolution_pending.json
       └─ 审计 evolution_<date>.json + ticks.jsonl 计数 + 日报附节

人工 CLI（scripts/chain_tracker.py 子命令）
  evolution list / confirm <chain_id> <proposal_id> / reject ...
       └─ confirm → evolution.apply_evolution(chain, proposal) → store.save_chain（schema 强校验）
```

## 4. 详细设计

### 4.1 change_type 枚举（6 类）

| change_type | 语义 | detail 关键字段 | confirm 应用目标 |
|---|---|---|---|
| `refine_segment` | 环节细化：环节新增材料/拆分，或补充壁垒、趋势 | `segment_id`（或新环节 `segment_id`+`segment_name`）、`materials`、`note` | `segments[]` 增量合并 |
| `add_node` | 新增关键节点：跟踪指标和/或标的 | `metric`（含 `current`/`signal_direction`）、`stock`（含 `code`/`name`/`segment`/`relation`） | `tracking_metrics[]`、`mappings[]` 增量合并 |
| `focus_shift` | 重心转移：受益环节/时机结构性迁移 | `from_segment`→`to_segment`、`next_trigger`、`risk` | `timing.next_trigger/risk` 更新 + `stage_evidence` 附注 |
| `update_thesis` | 产业逻辑本身被新证据修正 | `new_thesis` | 替换 `thesis` |
| `update_falsification` | 证伪条件更新 | `add`（list）/ `remove`（list） | `falsification[]` 增量合并 |
| `add_relation` | 发现跨链传导关系 | `target`、`relation`、`note` | `chain_relations[]` 追加 |

### 4.2 Prompt 扩展（analysis.py）

在现有 5 步框架后追加 Step 6（可选，默认 null）：

- 判定核心：**结构性增量 vs 阶段信号**。只影响阶段/价格/进度的信息 → null；重复 chain.yaml 已有内容 → null。
- 每批最多输出 1 条（取最重要的），防提案爆炸。
- `verdict=irrelevant` 时强制 null（解析层兜底）。
- 要求给出 `rationale`（哪条信息、什么推理）与 `confidence`。

输出 JSON 增加尾部可选字段 `"logic_update": null | {...}`。主字段解析逻辑不动；`logic_update` 独立校验，非法只丢提案、不影响主分析结果。

### 4.3 evolution.py 新模块

职责：解析校验、pending 持久化、去重合并、confirm/reject 应用。

- `parse_logic_update(result: dict) -> dict | None`：从 analyze_chain 结果提取并校验；非法/irrelevant → None。
- `upsert_pending(proposals, path, now) -> list[dict]`：正本 `infra/data/chain_tracking/evolution_pending.json`。
  - 去重键：`(chain_id, change_type, target_key)`。`target_key` 按类型取标识（add_node→metric 名或股票 code；refine_segment→segment_id；focus_shift→to_segment；update_thesis→"thesis"；update_falsification→逐条 falsification 文本；add_relation→target）。
  - 命中已有：只合并 `source_info_ids` + `evidence` 计数 + 刷新 `last_evidence_at`，不重复占位。
- `apply_evolution(chain: dict, proposal: dict, *, today: str) -> dict`：按 §4.1 表合并进 chain dict（就地修改），并按去重规则防重复条目（tracking_metrics 按 metric、mappings 按 code、chain_relations 按 target+relation、falsification 按文本）；history 追加 `{date, stage: 当前阶段, action: "演化:<change_type> <summary>", result: "待验证"}`。返回变更摘要。
- `confirm_evolution(proposal_id, ...)` / `reject_evolution(proposal_id, ...)`：confirm 经 `store.save_chain` 落盘（schema 强校验兜底，非法即失败不写入）并从 pending 移除。
- proposal_id：`{chain_id}:{change_type}:{target_key}` 的 slug，人眼可读、CLI 可直接引用。

### 4.4 core.py 接线

- `analyze_chain` 返回后：`proposal = evolution.parse_logic_update(result)`；非 None 且非 dry_run → `upsert_pending` + `append_daily_audit`（`evolution_<date>.json`）。
- tick 摘要新增 `evolution_proposals`（列表）；`ticks.jsonl` 加 `evolution` 字段；`chain_tracker.py` stdout 打印提案行。
- 日报 `append_daily_report`：当日有演化提案时追加"演化提案"附节（独立于阶段变化，提案不要求伴随 stage change）。
- LLM 失败/解析失败语义与现有一致：不落账、下一 tick 自愈；演化提案解析失败只丢提案。

### 4.5 CLI（scripts/chain_tracker.py）

复用 chain_discovery 的子命令模式：

```
python scripts/chain_tracker.py evolution list
python scripts/chain_tracker.py evolution confirm <proposal_id>
python scripts/chain_tracker.py evolution reject <proposal_id>
```

cron 包装脚本（`~/.hermes/scripts/qing_chain_tracker.py`）不动——tick 路径行为兼容。

## 5. 关键设计决策

1. **提案制，不自动落账**：结构变化一律人工 confirm。对齐发现引擎"避免 LLM 幻觉导致产业链爆炸"的决策；chain.yaml 是知识库正本，自动改结构风险远高于自动改阶段（阶段有走一格护栏且可逆）。
2. **合并进现有 5 步分析调用，不新增 LLM 调用**：成本敏感（2026-08-31 配额故障教训）；演化判断与阶段判断共享同一份上下文（链状态+新信息），拆两次调用是重复花钱。代价是 prompt 变长，用"可选尾部字段 + 独立解析容错"控制失败面。
3. **每批最多 1 条 + pending 去重合并**：防提案刷屏；待定提案躺着累积证据，与发现引擎候选池语义一致。
4. **阶段与结构分离**：阶段继续自动（护栏内），结构走人工。两者可在同一 tick 各自产出。
5. **confirm 应用做增量合并而非整体替换**：LLM 提案是"补丁"语义，merge 规则确定性实现，避免 LLM 输出全量 chain 带来的覆盖风险。
6. **演化机制输入源无关**：`parse/upsert/apply` 不依赖信息来源，为 UP claims 接入预留（§7）。

## 6. 测试设计（TDD）

- `tests/investment_engine/test_chain_tracker_evolution.py`：
  - parse：6 类合法 detail 通过；非法 change_type/缺关键字段/verdict=irrelevant → None；fence 容错由主 parse 覆盖。
  - upsert：去重键命中 → 合并证据不新增；不同 target_key → 并存。
  - apply：6 类 change_type 各自的合并行为 + 去重防重复 + history 追加；应用后经 `validate_chain` 通过。
  - confirm/reject：confirm 落盘并从 pending 移除；链不存在/提案不存在报错；reject 移除。
- `test_chain_tracker_analysis.py` 扩展：prompt 含 Step 6 说明；`parse_analysis` 对 `logic_update` 合法保留/非法丢弃/缺失容忍。
- `test_chain_tracker_core.py` 扩展：tick 内 logic_update → pending 落账 + 摘要计数；dry_run 不写。

## 7. 后续扩展（本期不做）

- **UP claims → 演化提案**：`chain_up_compare.py collect` 时把命中链的当日 UP claims 喂给同一演化 prompt 生成提案（UP 观点是"重心转移"判断的最权威来源）。机制已输入源无关，只需加调用点与调度。
- 提案质量复盘：演化提案的 confirm/reject 率纳入 methodology-review。

## 8. 验收

1. `pytest tests/investment_engine/ -k chain` 全绿（含新增）。
2. `python scripts/chain_tracker.py --offline --dry-run` 行为兼容（无回归）。
3. 回放某日含结构增量的信息（如 PCB 链"玻璃布 Q-Glass 国产切入"研报），tick 产出 `add_node`/`refine_segment` 提案并入 pending；`evolution list/confirm/reject` 全流程可走通，confirm 后 chain.yaml 经 schema 校验。
