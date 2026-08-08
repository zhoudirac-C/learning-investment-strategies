# M0 验收报告（2026-08-08）

## 验收标准对照（v2.1 第十四节）

| 标准 | 结果 | 证据 |
|---|---|---|
| 10 个框架全部带 validation 区块 | ✅ | `validate_patterns_file` 全量校验输出"全部 10 个框架通过来源中立校验"（T10，commit 329bea9；T15 复检仍通过） |
| 回放能跑出命中率 | ⚠️ 管线通、真实命中率为空 | 合成数据 e2e 跑通（T14，stats 含 5/10/20 三键）；真实数据回测见 `logs/backtest_buy_signals_20260808.md`——K 线缓存为空（0 标的 0 交易日），信号数 0、命中率 N/A |
| 产业链知识库 schema 落地并迁移 3 篇 | ✅ | `knowledge/industry-chains/{changxin-dram, domestic-compute, ai-infra-energy}/`；save/load 双向过 schema；人工抽查兆易创新/北方华创/雅克科技与原文表格一致（T5，commit 5b462d6） |
| 术语词典 | ✅ | `framework/up-glossary.md`（10 术语客观定义，与 market-cycle-framework.md / sector-diffusion-framework.md 原文用法核对无冲突，commit 9c59264） |

## 如实记录的缺口

- **K 线缓存为空**：`infra/data/kline_cache.db` 实际为 0 字节级空库（连表结构都没有，T15 先用 `init_db()` 幂等建表再跑），0 标的覆盖。无法定出真实回测窗口，真实命中率缺失。按约束未用网络补数据。回测管线本身经合成数据验证可用（T14），缓存回填后重跑 `scripts/backtest_buy_signals.py` 即可产出真实命中率。
- **validation 回填未做**：因真实回测样本 n=0，`technical_timing` / `operation_strategy` 的 `historical_hit_rate` 保持 `pending-m1`（校验器只允许 null/数值/pending-m1，n=0 无实测值可填，如实保持待测状态）。
- LLM 推理类模式的 historical_hit_rate 为 pending-m1（待盲测 eval）。
- knowledge/cases/ 案例库实际仅 2 篇，基准率检索样本不足（影响 M3 假设置信度）。
- 回测信号样本数 n=0，本轮命中率仅作"管线可用"证明，不作任何策略结论。

## 执行偏差记录

- T5 迁移时修正解析器 SKIP_WORDS：去掉 `催化`（误杀方向一"赛道一：股权关联方（IPO催化弹性最大）"标题），新增 `博主`/`视角`（跳过"博主方法论映射""Token经济学视角"等噪声章节）；改动随 T5 commit（5b462d6）。
- T4/T12 实测测试数（12/8）与计划预估（10/9）略有出入，以计划内嵌测试代码实际用例数为准。
- 会话期间为用户在 `~/.kimi-code/config.toml` 配置 Bash/Edit/Write 三条 allow 权限规则（用户主动要求的预授权，与仓库代码无关）。

## 回归

- `tests/investment_engine/` 54 passed（T15 Step 5 实测）。
- 全仓 `PYTHONPATH=third_party/chanpy .venv/bin/pytest tests/ -q`：**501 passed, 4 failed, 4 skipped**。
- 失败的 4 个均为基线 commit（12681b4）已存在的环境型失败，与本分支改动无关（已在基线 worktree 复跑验证，基线为 7 failed / 444 passed；本分支失败集是基线失败集的子集）：
  - `test_evaluate_agent_vs_up.py::TestCLI`（2 个）：子进程未继承 `src` 的 PYTHONPATH，`import qing_investment` 失败；
  - `test_kimi_code_cli_short_output.py::test_invoke_logs_short_raw`：依赖 kimi CLI 环境；
  - `test_pre_fetch_klines.py::TestPreFetchKlines::test_fail_rate_exit_code`：依赖外部数据环境。
- 附带发现：`tests/chan_engine/test_adapter_chanpy.py` 需要 `PYTHONPATH=third_party/chanpy` 才能收集（pyproject 的 pytest pythonpath 未含它，基线即如此）。
- 本分支 `init_db()` 初始化 K 线缓存 schema 后，`test_pre_fetch_klines` 的 3 个用例反而比基线多通过（基线 worktree 无缓存文件）。
