# M0 执行交接文档（蒸馏+回测基建+产业链知识库）

> **用途**：原会话因终端滚动异常/内存问题中断，本文档供**新对话**接续执行。
> **新对话启动方式**：把本文末尾"恢复提示词"粘贴给新会话即可。

---

## 一、必读文件（新会话先读这三份）

1. **本执行计划（含全部 15 个任务的完整代码，自包含）**：
   `docs/superpowers/plans/2026-08-08-m0-distill-backtest-industry-chain.md`
2. **方案背景（为什么做 M0）**：
   `investment-learning-project/ai-stock-investment-plan.md`（v2.1，重点看第四节引擎⓪、第五节产业链知识库、第十四节里程碑）
3. 本文档（进度与约束）。

## 二、当前状态（2026-08-08 实测确认）

- **分支**：`feat/m0-distill-backtest`（从 master 切出，不要回 master 干活）
- **已完成 commit**：
  - `12681b4` docs: 方案 v2.1 + M0 实施计划（基线）
  - `5bb249a` feat: T1 包骨架 + 冒烟测试（2 passed）
- **工作区**：干净（`git status --short` 无输出）
- **进度**：T1 ✅ 完成；T2–T15 未开始；最终 code review 未做

## 三、执行约束（用户明确指令，必须遵守）

1. **不用 subagent**：此前多个 subagent 并行导致内存溢出、程序崩溃。所有任务在当前会话**顺序执行**，禁止派 Agent/AgentSwarm。
2. **git commit 已获用户一次性授权**：严格按计划里每个任务的 commit message 逐任务提交；不要额外发明 commit，不要 push。
3. **红线**：不修改 `src/qing_investment/` 任何文件（只 import 调用）。
4. **pytest 坑（已踩过）**：`tests/` 子目录下**不要放 `__init__.py`**——pytest prepend 模式会把测试目录注册为 `investment_engine` 包，遮蔽 `src/investment_engine`。仓库惯例是平铺无 __init__（参照 `tests/chan_engine/`）。
5. 测试命令一律用 `.venv/bin/pytest`（仓库根目录执行）。

## 四、任务进度表

| # | 任务 | 状态 | 完成判据（详见计划文件对应 Task） |
|---|---|---|---|
| T1 | 包骨架+冒烟测试 | ✅ 5bb249a | 2 passed |
| T2 | chain.yaml 校验器（`industry_chain/schema.py`） | ⬜ 下一个 | 9 passed + commit |
| T3 | 知识库读写层（`industry_chain/store.py`） | ⬜ | 8 passed + commit |
| T4 | 深度研究 md 解析器（`industry_chain/migrate.py`） | ⬜ | 10 passed + commit |
| T5 | 迁移 CLI + 3 篇迁移入 `knowledge/industry-chains/` | ⬜ | dry-run mappings>0 → 正式迁移 → 人工抽查 3 标的 |
| T6 | 来源中立模式校验器（`distill/pattern_schema.py`） | ⬜ | 10 passed + commit |
| T7 | 备份 + upstream_cycle 改写 | ⬜ | patterns[0] 过校验 + commit |
| T8 | mainline/rotation/macro 三框架改写 | ⬜ | patterns[1-3] 过校验 + commit |
| T9 | sentiment/technical/earnings 三框架改写 | ⬜ | patterns[4-6] 过校验 + commit |
| T10 | ai_industry/operation/others 改写 + 全量校验 + version 3.0 | ⬜ | 10 框架全过校验 |
| T11 | UP 术语词典 `framework/up-glossary.md` | ⬜ | 计划里有全文，落地+核对原文件 |
| T12 | 历史区间数据访问（`backtest/history.py`） | ⬜ | 9 passed + commit |
| T13 | 命中率统计（`backtest/hit_rate.py`） | ⬜ | 5 passed + commit |
| T14 | 回测 CLI `scripts/backtest_buy_signals.py` | ⬜ | 合成数据 e2e 跑通 + commit |
| T15 | 真实数据回测 + validation 回填 + `logs/m0-acceptance.md` | ⬜ | 验收报告 + 全量回归绿 |
| — | 最终自查（对照计划"自查记录"节） | ⬜ | 全部测试绿 |

**执行方式**：每个任务严格按 TDD——先写测试（计划里有完整代码）→ 跑确认失败 → 写实现（计划里有完整代码）→ 跑确认通过 → 按计划 message commit。T7–T10 是 YAML 内容改写（无代码测试），按计划的映射规则表改写、跑校验命令、commit。

## 五、关键技术事实（调研已确认，写代码直接用）

- K 线缓存：`qing_investment/kline_cache.py`，表 `stocks_kline(code, trade_date, open..close, volume, turnover, amplitude, pct_change)`，DB 在 `infra/data/kline_cache.db`；`get_klines(code, days)` 只有"最近 N 日"，区间查询由 T12 新建。
- 规则引擎：`BuySignalRuleEngine().evaluate(config: dict, quote_snapshot: dict)`；quote 字段契约对齐 `src/qing_investment/monitor/tests/test_e2e.py:38` 的 mock（`code`=secid 如 `1.600519`、`latest`、`turnover_rate`）。
- 配置加载：`qing_investment/monitor/context/__init__.py:1094` `load_monitor_config(path)`；标的池新结构 `config/stock_monitor/stock_pool.yaml` 的 `stocks[].code/name`。
- reasoning-patterns.yaml：顶层 `patterns:` 10 项，起始行号 upstream_cycle:5 / mainline_identification:331 / sector_rotation:835 / macro_transmission:1137 / sentiment_cycle:1416 / technical_timing:1617 / earnings_analysis:1759 / ai_industry_chain:1900 / operation_strategy:2046 / others:2167。改写映射规则见计划 Task 7 的表格。
- 深度研究 3 篇源文件：`docs/标的深度研究/方向一：长鑫存储产业链全景梳理-20260518.md`、`方向二：国产算力产业链与Token经济学深度梳理-20260518.md`、`方向三：AI基础设施与能源转型产业链梳理-20260518.md`（用无前缀完整版；行数 212/273/224）。
- 已知缺口（验收报告要如实写）：`knowledge/cases/` 实际案例仅 2 篇；回测窗口取决于缓存实际覆盖（T15 Step 1 先查 coverage 再定窗口，不用网络补数据）。

## 六、恢复提示词（复制到新对话）

```
继续执行 M0 计划。先读 docs/tasks/m0-execution-progress.md（交接文档），
再读 docs/superpowers/plans/2026-08-08-m0-distill-backtest-industry-chain.md 中
下一个未完成任务的全文，从 T2 开始顺序执行。
约束：不用 subagent、逐任务按计划 commit（已授权）、不改 src/qing_investment/、
tests 子目录不放 __init__.py、用 .venv/bin/pytest。
分支 feat/m0-distill-backtest 已建好，先 git checkout 确认。
每完成一个任务，更新 docs/tasks/m0-execution-progress.md 的进度表并随任务 commit 一起提交。
```
