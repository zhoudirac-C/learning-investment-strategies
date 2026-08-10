# M0 验收报告（2026-08-08，缓存回填后修订版）

## 验收标准对照（v2.1 第十四节）

| 标准 | 结果 | 证据 |
|---|---|---|
| 10 个框架全部带 validation 区块 | ✅ | `validate_patterns_file` 全量校验输出"全部 10 个框架通过来源中立校验"（T10，commit 329bea9；回填后复检仍通过） |
| 回放能跑出命中率 | ✅ | `logs/backtest_buy_signals_20260808.md`：窗口 2026-04-27~2026-08-07（71 交易日），标的池 212 只，信号 1507 个；5日前向命中率 51.8%（n=1403，均值 +1.11%）、10日 53.4%（n=1279，+1.15%）、20日 47.9%（n=1070，+0.33%） |
| 产业链知识库 schema 落地并迁移 3 篇 | ✅ | `knowledge/industry-chains/{changxin-dram, domestic-compute, ai-infra-energy}/`；save/load 双向过 schema；人工抽查兆易创新/北方华创/雅克科技与原文表格一致（T5，commit 5b462d6） |
| 术语词典 | ✅ | `framework/up-glossary.md`（10 术语客观定义，与 market-cycle-framework.md / sector-diffusion-framework.md 原文用法核对无冲突，commit 9c59264） |

## 回测口径与 caveat（如实标注）

- **数据**：K 线缓存 2026-08-08 由 `FORCE_KLINE_FETCH=1 scripts/pre_fetch_klines.py` 回填，217/217 成功（腾讯 API；TDX 因缺 pytdx 跳过），216 只覆盖 2026-04-27~2026-08-07、1 只自 2026-05-11。个股缺口（001270 缺 1 日、603137 缺 10 日、603407 缺 7 日）见回测报告末节。
- **条件冻结偏差**：引擎的"近3日缩量/MA20上方"两个条件由 qing_investment 内部读取**缓存最新窗口**（非信号日窗口），引擎非为历史回放设计且红线未改 qing_investment——因此这两个条件对每个标的是冻结常量，命中率为该口径下的近似值。
- **"UP明确看好"条件恒为 False**：stock_pool 配置的 claim_basis 为空，6 项条件实际可用 5 项，候选阈值为 ≥4。本轮回测本质是"介入区间+量价纪律"机械条件的来源中立回测。
- **门控绕过**（2026-08-10 补）：回测调 `BuySignalRuleEngine.evaluate()` 未传 MarketGate / SectorGate 结果（`src/qing_investment/monitor/rules/__init__.py` 中 None 不拦截），1507 个信号为无门控版，比生产环境宽松。
- **config 前视**（2026-08-10 补）：stock_pool 标的池与介入区间为当前快照，套用到 2026-04~08 历史日期，存在前视偏差（方向不定）。
- **定性**（2026-08-10 补）：本回测验证的是执行层规则，不是 UP 观点本身，也不是推理模式；结果**不能作为方法论有效的证据**。方法论验证以 M1 盲测（`logs/m1-baseline-20260808.md`）与影子双轨为准。
- 同一标的连续多日触发按多个信号日计（计划既定口径），未做去重。
- 20日 horizon 样本少于信号总数（窗口尾部前向数据不足），为正常截断而非错误。

## 如实记录的缺口

- LLM 推理类模式（其余 8 个框架）的 historical_hit_rate 保持 `pending-m1`（待 M1 盲测 eval）。
- knowledge/cases/ 案例库实际仅 2 篇，基准率检索样本不足（影响 M3 假设置信度）。
- K 线缓存历史仅 ~3.5 个月（90 根日 K 上限），更长的历史回测需后续另补历史数据；缓存连续性依赖每日 cron 续拉。

## 执行偏差记录

- T5 迁移时修正解析器 SKIP_WORDS：去掉 `催化`（误杀方向一"赛道一：股权关联方（IPO催化弹性最大）"标题），新增 `博主`/`视角`（跳过"博主方法论映射""Token经济学视角"等噪声章节）；改动随 T5 commit（5b462d6）。
- T4/T12 实测测试数与计划预估略有出入，以计划内嵌测试代码实际用例数为准。
- **缓存回填后发现并修复 4 个回测链路 bug**（均有回归测试或行为验证）：
  1. `history.py` 代码格式假设错误——pre_fetch 写入的是带后缀代码（`000636.SZ`），区间查询按裸码匹配导致全程 0 行（新增 `TestSuffixedCodeCompat` 回归）；
  2. `quote_from_kline` 按 e2e mock 契约把 secid 塞进 `code`，生产 fetcher 实为 `code=裸码 + secid 字段`，导致 `_quote_for_stock` 匹配失败、引擎恒 0 候选（以生产 fetcher 为准修正，并新增 `test_engine_alert_end_to_end` 行为测试）；
  3. 回测 CLI 取裸码用 `split(".")[-1]`，对 `002371.SZ` 得到 `SZ`（改为首段）；
  4. 计划代码仅用截至当日的 K 线计算前向收益，恒为 None（改为信号日起另取前向区间）。
- `technical_timing` / `operation_strategy` 的 `validation.historical_hit_rate` 已回填实测值（0.5182，5日前向），明细在新增 `hit_rate_note` 字段（校验器只允许数值/pending-m1，注解不落主字段）。
- 会话期间为用户在 `~/.kimi-code/config.toml` 配置 Bash/Edit/Write 三条 allow 权限规则（用户主动要求的预授权，与仓库代码无关；用户决定保留至 M1）。

## 回归

- `tests/investment_engine/` 57 passed（含缓存回填后新增的 3 个回归/行为测试）。
- 全仓 `PYTHONPATH=third_party/chanpy .venv/bin/pytest tests/ -q`：**504 passed, 4 failed, 4 skipped**。
- 失败的 4 个均为基线 commit（12681b4）已存在的环境型失败，与本分支改动无关（已在基线 worktree 复跑验证，基线为 7 failed / 444 passed；本分支失败集是基线失败集的子集）：
  - `test_evaluate_agent_vs_up.py::TestCLI`（2 个）：子进程未继承 `src` 的 PYTHONPATH，`import qing_investment` 失败；
  - `test_kimi_code_cli_short_output.py::test_invoke_logs_short_raw`：依赖 kimi CLI 环境；
  - `test_pre_fetch_klines.py::TestPreFetchKlines::test_fail_rate_exit_code`：依赖外部数据环境。
- 附带发现：`tests/chan_engine/test_adapter_chanpy.py` 需要 `PYTHONPATH=third_party/chanpy` 才能收集（pyproject 的 pytest pythonpath 未含它，基线即如此）。
- 本分支 `init_db()` 初始化 K 线缓存 schema 后，`test_pre_fetch_klines` 的 3 个用例反而比基线多通过（基线 worktree 无缓存文件）。
