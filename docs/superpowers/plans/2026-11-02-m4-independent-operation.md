# M4 分步实施计划：多专家独立运行与 Qing-Agent 每日市场验证

## 已核实现状与实施边界

- 生产图是共享 LangGraph；qing/gator 通过 school、patterns、gator 规则快照和冲突卡进入同一流程，不新增“专家节点”。
- M4 启动前，API 只返回最终文本，没有可结算的结构化方向、专家视角或不可变记录；`daily_state.json` 与 `daily_review_summary.json` 都会覆盖，不能充当冻结账本。当前结构化响应与不可变记录已实现，验收证据见下文。
- 复用 `blindtest.score` 的收益计算和沪深300基准，但不复用 shadow 的预测生成、覆盖式重跑和毕业判定。
- 新记录默认写入已被 gitignore 的 `infra/data/qing_agent/`，防止持仓、原始输入和最终文本误入 git；shadow 目录和历史评分不改。
- validation 门禁只过滤 qing 的来源中立生产规则，并保留 school/validation 元数据。gator 的现有专家 patterns 保持原召回行为，同时如实标注草案/未独立验证；不得伪填命中率或关闭 gator 规则、冲突卡和双学派契约。新 spec 中相应句子需同步改成这个按学派处理的口径。
- 不改 `config/schools.yaml`，不删除其他 UP，不改监控器全局 `up_sentiment` 字段，不接交易接口，不安装新 cron，不执行 commit/push。

## 实施进度（更新至 2026-11-09）

> 本节记录工程进度，不代表 M4 已通过最终验收；设计文档的实施状态仅在真实链路验收通过后调整。

| 项目 | 当前状态 | 证据与剩余边界 |
|---|---|---|
| Task 1 | 定向与标准全仓回归通过 | qing 实时锚定清理、按学派 pattern 门禁及相关 prompt/图测试已写入工作区；相关回归 `268 passed, 1 warning`，最终标准全仓 `2271 passed, 4 skipped, 5 deselected, 3 warnings`；完整真实闭环仍未完成 |
| Task 2 | 真实冻结与响应回链已验收 | 2026-11-06 的 9 条真实响应均与冻结原文哈希一致，请求无 qing 实时信号键，gator 快照、数据时点及规则/prompt 版本完整；完整闭环仍受 Task 3 样本边界限制 |
| Task 3 | 工程与定向回归通过，真实到期结算待可结算样本 | 2026-11-06 的 9 条与 2026-11-09 截至 13:01 的 5 条真实记录，实际可独立结算 direction/expert 项均为 0；不能用合成测试或外层 `final_judgment.score_eligible=true` 代替真实 T+5 验收 |
| Task 4 | 真实报告回链已验收 | 2026-11-06 统一 CLI 生成日报与 4/8 周报告，正确呈现 7 条 pending、2 条 error 和零有效样本；未安装新 cron |

### 验证记录

- 2026-11-09 回归修复：为真实 summary 的 3 个新标签补显式阶段映射，其中“数据缺失，无法确定”归剔除项；ASR 试看测试改用低于长视频阈值的 mock 时长，保留生产端长视频下载前拦截；买入信号价格越界测试在当前工作区复跑通过，无需改其实现。三个历史失败节点与买入信号端到端文件合计 **10 passed**，M4 相关回归 **268 passed, 1 warning**。
- 2026-11-09 新增回归处理：120 分钟实时 bar 测试允许最近 N 根的首尾交易日及盘中截断，但继续强制中间完整交易日恰好 2 根，定向 **5 passed**。`test_phase7_scenarios.py` 真实 POST localhost Qing-Agent 却未标 live，两轮全仓共产生 12 条 `mock-*` missing 记录；已将这 3 项归入既有 live 分组，并把本轮产生的 12 条记录移出正式账本。离线选择验证为 **6 passed, 3 deselected**（与阶段测试联合运行），最终全仓后正式账本 mock 数为 0。
- 2026-11-09 最终标准全仓：`PYTHONPATH=third_party/chanpy .venv/bin/pytest tests/ -q` 结果 **2271 passed, 4 skipped, 5 deselected, 3 warnings**（446.93 秒），退出码 0。5 个 deselected 为原有 2 项及 Phase 7 的 3 项真实服务集成测试；未删除测试、伪造响应或以 deselect 掩盖原 3 项失败。
- 2026-11-09 真实样本只读审计：截至 13:01，`infra/data/qing_agent/2026-11-09/` 有 5 条真实记录，3 条 `pending_maturity`、2 条 `error(llm_empty)`，mock=0、settlement 回写=0。3 条 pending 的 `directions[]` 均为空、可独立结算 expert 项均为 0，现有 `_score_targets()` 实际选择总数为 0；虽然外层 `final_judgment.score_eligible=true` 且有板块方向文字，但没有 ID+唯一 6 位代码+T+5+polarity+失效条件的独立项，且可见文本存在“暂无主线/数据缺失”表述，与结构化方向不一致。第二步仍未通过，不提前执行 T+5、miss 归因或 M5。
- 2026-11-07 现有真实链路验收：读取 `qing-agent-request.2026-11-06.log` 与 `infra/data/qing_agent/2026-11-06/` 的 9 条真实记录，9/9 响应 `final_output` 与冻结 `raw_output` 哈希一致，9/9 请求与记录 `data_as_of` 一致；请求中 `direction_signals`、`up_sentiment` 及其他 qing 实时输入键均为 0，所有记录保留可用 gator 快照、`input_hash` 和规则/prompt 版本，未保存持仓快照。
- 2026-11-07 真实 CLI 与状态隔离：运行 `.venv/bin/python scripts/qing_agent_validation.py run --date 2026-11-06`，首次结算扫描 7 条非 error 记录、追加 `settlement.status=not_applicable`，`items=0/scored=0`；第二次运行 `updated=0` 且全部记录文件哈希不变。日报 `logs/qing-agent-daily-2026-11-06.md` 显示 `pending=7/error=2/missing=0`，缺失 pre_market/closing 轨；滚动报告 `logs/qing-agent-reliability-2026-11-06.md` 的 final/expert 方向与标的均为 `n=0/insufficient_data`，未把异常或零样本计为命中。
- 2026-11-07 验收边界：现有 9 条真实记录均无 `score_eligible=true` 的可独立结算 direction/expert 项，因此本次只通过“真实请求/响应 → 冻结 → 回链 → 报告”验收，真实 `pending_maturity` 评分项、T+5 到期结算及 miss 归因仍未验收；不得据此更新设计文档为实施完成。
- 2026-11-07 相关回归：records/settle/attribute/report/CLI、score/maturity/daily、trigger freeze、pattern policy、双学派、gator 与 claim schema 联合运行，结果 **268 passed, 1 warning**；警告为既有 Pydantic V2 弃用提示。
- 2026-11-07 标准全仓命令 `PYTHONPATH=third_party/chanpy .venv/bin/pytest tests/ -q` 已完成，结果 **2271 passed, 3 failed, 4 skipped, 2 deselected, 3 warnings**（1176.67 秒），全仓未全绿：
  - `test_qing_review.py::TestNormalizeStage::test_real_file_labels_all_mapped`：真实 summary 现有 3 个未映射标签；该测试与 11-03 历史失败重合，但标签数量与内容随真实数据变化。
  - `test_bilibili_video_asr.py::test_asr_video_preview_only_logs_and_returns_empty`：预期空字符串，实际返回长视频跳过提示；与 11-03 历史失败重合。
  - `test_buy_signal_e2e.py::TestBuySignalE2E::test_evaluate_buy_signal_candidates_rejects_when_price_out_of_zone`：价格 12.0 超出 10.0~11.0 区间仍被标为候选；相对 11-03 历史记录为新增失败，尚未做干净基线归因，不宣称与 M4 改动无关。
- 2026-11-04 Task 4 定向与相关回归：按 TDD 从模块缺失的预期失败开始，完成分轨统计、M4 起点日历、隐私投影、异常记录隔离和 CLI 副作用防护后，report/CLI 与 records/settle/attribute/score/maturity/daily/trigger_freeze 联合回归 **179 passed, 1 warning**。独立规格与代码质量复核无剩余 Critical/Major。
- 2026-11-04 Task 4 扩大回归与真实 CLI 冒烟：`PYTHONPATH=third_party/chanpy .venv/bin/pytest tests/investment_engine tests/test_qing_agent_trigger_freeze.py -q` 结果 **1022 passed, 3 failed, 2 warnings**；失败仍为 11-03 已有记录中的产业链护栏两项和真实复盘标签映射一项，未记为全仓全绿。随后以仓库真实记录和 K 线缓存运行 `qing_agent_validation.py report --date 2026-11-04`，成功生成日报与 4/8 周报告，正确识别 4 条 error 和 3 个无有效记录日，未生成命中；临时报告核对后已清理，未触发真实 Qing-Agent。
- 2026-11-03 Task 2 定向测试：`PYTHONPATH=third_party/chanpy .venv/bin/pytest tests/investment_engine/test_qing_validation_records.py tests/test_qing_agent_trigger_freeze.py -q`，结果 **88 passed, 1 warning**；警告为既有 Pydantic V2 弃用提示。
- 2026-11-04 Task 3 定向与相关回归：运行两个新测试文件及 `test_qing_validation_records.py`、`test_score.py`、`test_maturity.py`、`test_daily.py`，结果 **137 passed, 1 warning**。覆盖真实合成 SQLite 评分、T+4/T+5、严格正超额、非 long、缺失行情、最终/专家隔离、归因历史保留、股票代码归一化、历史补跑防前视和并发冲突保护。
- 2026-11-04 扩大回归：`PYTHONPATH=third_party/chanpy .venv/bin/pytest tests/investment_engine tests/test_qing_agent_trigger_freeze.py -q`，结果 **994 passed, 3 failed, 2 warnings**。失败为 11-03 已有记录中的 `test_chain_tracker_core.py::TestTick` 两项和 `test_qing_review.py::TestNormalizeStage::test_real_file_labels_all_mapped` 一项；本次未修改对应实现，尚未做干净基线复跑，不记为全仓全绿。
- 2026-11-03 标准全仓命令 `PYTHONPATH=third_party/chanpy .venv/bin/pytest tests/ -q` 已完成，结果 **2207 passed, 4 failed, 4 skipped, 2 deselected, 3 warnings**（1175.32 秒）。全仓未全绿，不能记为验收通过。
  - `test_chain_tracker_core.py::TestTick` 2 项失败：量价护栏拦截后 `changes` 实际为 1、预期为 2。
  - `test_qing_review.py::TestNormalizeStage::test_real_file_labels_all_mapped`：真实 summary 出现 2 个未映射阶段标签。
  - `test_bilibili_video_asr.py::test_asr_video_preview_only_logs_and_returns_empty`：预期空字符串，实际返回长视频跳过提示。
  - 上述 4 项在全仓运行前的 `.pytest_cache/v/cache/lastfailed` 中已有记录，且均不在 Task 2 的两个定向测试文件内；尚未用干净基线 worktree 复跑，因此只记为“已有失败记录、归因未完成”，不宣称已证明与 M4 改动无关。
- 截至 2026-11-07，无 qing 当日输入且保留 gator 的真实“请求/响应 → 冻结 → 报告”回链已验收；现有记录没有可独立结算项，真实 T+5 到期结算与 miss 归因仍未验收，不得用 mock 或合成测试代替该项结论。

## 本轮三步核心执行计划（2026-11-04）

1. **市场结算与错因归因**：新建 `qing_validation/settle.py`、`attribute.py` 及定向测试。只读扫描冻结记录，复用 `blindtest.score` 的沪深300相对收益口径，对最终判断和可独立结算的专家视角分别做 T+5 结算；按 `record_id + target + target_id` 追加结果，不改原判断。未到期、缺行情、异常和缺失分别保留为 `pending_maturity`、`insufficient_data`、`error/missing`，均不得误计命中；非 long 不按多头评分。市场 miss 只生成数据缺、步骤缺、概念/学派归属错误、信息差的待复核归因候选，不自动修改规则。
2. **每日完整性与滚动可靠性报告**：新建 `qing_validation/report.py` 和 `scripts/qing_agent_validation.py`。日报覆盖三轨完整性、异常、缺报和到期状态；4/8 周滚动报告将最终判断与专家视角分表，统计方向/标的超额、样本数、环境分布及候选归因。提供 `settle/report/run` 三个手动 CLI 子命令，默认读取 `infra/data/qing_agent`、写入 `logs/qing-agent-*`，不新增 cron。
3. **真实链路验收**：在无 qing 当日输入且保留 gator 输入的条件下触发一次真实 Qing-Agent 流程，核对冻结原文、专家视角、gator 快照、数据时点和规则/prompt 版本，再执行统一 CLI 检查留痕到报告的回链。未到期必须保持 `pending_maturity`，不得为验收伪造 T+5 结果；随后完成相关测试、prompt/evals 与全仓回归，并通过后再更新 M4 实施状态。

完成标准：一条真实判断能够按“冻结 → 回链 → 到期结算 → 归因 → 报告”流转，异常、缺失和未到期均不会进入命中统计。

## Task 1：拆除 qing 实时锚定，保护多专家与生产模式门禁

**主要文件**
- `src/qing_investment/agent/graph/nodes.py`
- `src/qing_investment/agent/tools/context_builder.py`
- `src/qing_investment/agent/tools/stock_sector_mapper.py`
- `src/qing_investment/agent/main.py`（`/chat` 内联 prompt）
- `src/qing_investment/agent/prompts/system/{market_summary,stock_analyst,stock_scanner,trader_mindset,market_analyst,reviewer,dual_school_output}.txt`
- 新增 `src/qing_investment/agent/tools/pattern_policy.py`
- 新增/扩展 `tests/test_pattern_prompt_policy.py`、`tests/test_dual_school_contract.py`、相关 prompt/图测试
- 同步 `docs/superpowers/specs/2026-11-02-m4-independent-operation-design.md` 的按学派门禁说明

**步骤**
1. 先写失败测试：带哨兵 `direction_signals/up_sentiment` 时，实际 LLM prompt 不得出现 qing 的“当前最看好/转谨慎则等待”等规则；gator 快照、patterns、冲突卡和 `[gator]` 仍出现。
2. 从 Qing-Agent 的 LLM 输入投影移除 qing 派生 `direction_signals` 和 watchlist `up_sentiment`，清理活跃 prompt、`/chat` 与遗留 `market_analyst.txt` 中对应的实时优先规则。监控器和其他 UP 的采集字段不动。
3. 将 qing 个股定位从“UP 标注可直接成为 final_position”改为实时排名优先、UP 仅作带日期的历史参考；无实时数据时明确降级，不作当前权威定位。
4. 移除 `_filter_methodology_only()` 对近期 qing market-cycle 观点的实时保留例外；保留历史方法论和教材。
5. 在 `pattern_policy.py` 实现生产准入与投影：qing 仅允许已有数值型市场验证记录的 pattern；pending/null/缺失不得进入生产召回。gator 保持现有召回并标记自身草案状态。投影必须保留 `school`、`validation`。
6. 在 embedding、LLM rerank、关键词 fallback 之前统一应用候选门禁，三个缓存保持一致；修复召回投影丢失 `school` 的问题。
7. 保留 `dual_school_output.txt` 的平权、双列分歧和 standing 规则，只把 qing claims 描述改为历史/方法论证据。`style_writer` 的文风不属于实时锚定，不误删。
8. 跑上述测试及 `tests/test_dual_school_contract.py`、`tests/monitor/test_gator_rules.py`、`tests/test_claim_schema.py`、`tests/test_bilibili_notify_gator_hook.py`。

## Task 2：结构化最终判断与专家视角，建立不可变留痕

**主要文件**
- `src/qing_investment/agent/models/schemas.py`：`TriggerRequest` 增加显式 `data_as_of`
- `src/qing_investment/agent/graph/nodes.py`：扩展 market_summary 结构化结果，保留 gator 确定性快照和实际使用的 pattern 引用
- `src/qing_investment/agent/main.py`：在 `analyze_trigger()` 图完成后、响应返回前冻结完整结果
- `scripts/hermes_stock_monitor_agent.py`：传递上下文 timestamp；传输失败/超时写 error，不把本地 fallback 记成 Qing-Agent 预测
- 新增 `src/investment_engine/qing_validation/{__init__.py,records.py}`
- 新增 `tests/investment_engine/test_qing_validation_records.py`、`tests/test_qing_agent_trigger_freeze.py`

**记录契约**
- `record_id/date/track/generated_at/data_as_of/trigger`；track 映射为 pre_market/intraday/closing。
- `input_hash`、输入数据可用性/缺口、数据/规则/prompt 版本；不完整持仓快照不入公开记录。
- `final_judgment`：市场阶段、依据、方向、标的、期限、触发/失效条件和 score_eligible。
- `directions[]` 只有在明确给出 `direction_id`、股票代码、`horizon=T+5`、`polarity` 和失效条件时才可结算；非正向判断不得按多头评分。
- `expert_views[]`：school、观点、证据、期限；gator 的规则快照直接取确定性引擎输出，不让 LLM 伪造。
- `raw_output`、review/citation 结果、`pending_maturity/scored/error/missing` 状态、结算与归因引用。
- 每次运行生成新 record_id；重跑新增版本并用 `supersedes_record_id` 链接，旧文件不覆盖。结算只允许追加规定字段。

**步骤**
1. 写存储失败测试：三轨不互相覆盖、重跑产生新版本、缺时间/期限不得评分、error/missing 独立、默认根目录在 infra/data 且测试重定向 tmp_path。
2. 实现 records.py 的 track 映射、记录构造、完整性校验、哈希、排他创建和版本链接。
3. 扩展 market_summary JSON 契约与解析回填，保留现有字段兼容；增加 expert_views、可结算 directions 及实际 pattern refs。
4. 接入 analyze_trigger 成功冻结和 wrapper 失败补记；留痕失败要显式日志告警，但不伪造成成功记录。
5. 用图测试验证：无 qing 当日输入且 gator 保留时，真实图输出能生成一条可回链记录；本地 fallback 不进入 pending_maturity。

## Task 3：接入市场结算与分对象错因归因

**主要文件**
- 新增 `src/investment_engine/qing_validation/{settle.py,attribute.py}`
- 扩展 `src/investment_engine/blindtest/score.py`：可选 `as_of` 限制评分读取截止日期，默认行为不变
- 扩展 `src/investment_engine/qing_validation/records.py`：以共享目录锁保护版本创建与结算写入
- 新增 `tests/investment_engine/test_qing_validation_settle.py`、`test_qing_validation_attribute.py`，扩展 `test_score.py`

**步骤**
1. 写结算失败测试：T+4 不结算、T+5 到期、严格正超额、非 long 不按多头评分、缺失行情为 insufficient_data、pending/error/missing 不进分母。
2. 实现只读 `infra/data/qing_agent` 的到期扫描；用交易日缓存计算期限，不调用 shadow 预测生成器。
3. 将 final_judgment 与每个可独立结算的 expert_view 分别适配为现有评分输入；复用 `direction_scores/stock_scores/load_truth`，方向/标的明细必须带 record_id、target=final/expert、school 和原始目标 ID。
4. 每个结算项独立保存 scored/pending_maturity/insufficient_data/not_applicable；零有效样本不得冒充一次有效评分。收盘后的当日阶段解释不得进入预测评分。
5. 实现候选归因：数据缺、步骤缺、概念误用/学派归属错误、信息差分开；按 record_id+target+target_id 隔离，不用日期合并不同专家。
6. 市场 miss 只产生待复核归因候选，不自动修改 standing 冲突、不自动改方法；重复问题进入现有人审提案流程。
7. 跑新测试及既有 `tests/investment_engine/test_score.py`、`test_maturity.py`、`test_daily.py`，证明旧 shadow 行为未变。

## Task 4：每日完整性、滚动可靠性报告与统一 CLI

**主要文件**
- 新增 `src/investment_engine/qing_validation/report.py`
- 新增 `scripts/qing_agent_validation.py`
- 新增 `tests/investment_engine/test_qing_validation_report.py`、CLI 冒烟测试
- 更新 `docs/tasks/m-series-status-and-usage.md`、`docs/current-system-guide.md`；仅在真实验收通过后更新新 spec 的实施状态

**步骤**
1. 写报告失败测试：4/8 周窗口、分轨、最终/专家分表、分环境样本、缺失日置顶、pending/error/missing/insufficient 不计命中；不得输出 graduated/not_yet 门禁结论。
2. 实现每日完整性报告：当天各轨记录、缺字段、事实/归属错误、到期/未到期、异常与缺报。
3. 实现滚动 4/8 周可靠性报告：阶段参考、方向/标的 T+5 超额、样本数、环境分布、缺失/未到期/数据不足、候选归因统计。旧阈值只作参考。
4. 新增 CLI：
   - `.venv/bin/python scripts/qing_agent_validation.py settle --date YYYY-MM-DD`
   - `.venv/bin/python scripts/qing_agent_validation.py report --date YYYY-MM-DD`
   - `.venv/bin/python scripts/qing_agent_validation.py run --date YYYY-MM-DD`（结算+报告）
   默认只读 `infra/data/qing_agent`，写 `logs/qing-agent-*`；支持测试注入 root/db/config。
5. 文档写明真实命令和当前调度边界；不把手动 CLI 写成已安装 cron。

## 最终验证

1. 新模块全部先红后绿；逐任务检查 diff，不允许改变其他 UP 配置或 shadow 历史文件。
2. 运行相关 Qing-Agent/双学派/监控回归和 `.venv/bin/pytest tests/investment_engine -q`。
3. 运行标准全仓命令 `PYTHONPATH=third_party/chanpy .venv/bin/pytest tests/ -q`；若仍有既有环境失败，与已知基线逐项区分，不隐瞒。
4. 用现有真实数据链路跑一次无 qing 当日输入的 Qing-Agent 触发，检查冻结原文、专家视角、gator 快照、data_as_of 和版本；再执行 `qing_agent_validation.py run`，核对一条真实记录的留痕→到期状态→报告闭环。若服务或模型不可用，明确报告阻塞，不能用 mock 冒充真实验收。
5. 最后审阅 `git diff` 和 `git status --short`，确保只有本任务文件，且没有 positions、.env、infra/data 或历史评分被 staged/改写。