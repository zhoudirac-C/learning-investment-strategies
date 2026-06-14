# Project Instructions For Hermes

This repository is a personal investment research and learning system. For any
stock analysis, trading monitor, market review, portfolio review, or intraday
alerting task, use the local project framework before giving conclusions.

## Required Workflow

1. **Superpowers 强制**: 所有对该项目的代码/文档改动，必须先加载对应的 superpower skill。Hermes 会自动从 `skills/` 目录加载。

2. Read `skills/qing-stock-analysis/SKILL.md`.

3. Follow these references when relevant:
   - `framework/stock-analysis-playbook.md`
   - `skills/qing-stock-analysis/references/data-source-strategy.md`
   - `skills/qing-stock-analysis/references/glmv-stock-analyst-workflow.md`
   - `skills/qing-stock-analysis/references/f10-financial-analysis.md`
   - `skills/qing-stock-analysis/references/qing-stock-framework.md`
   - `skills/qing-stock-analysis/references/report-contract.md`
3. Use local knowledge before generic market reasoning:
   - `knowledge/claims`
   - `knowledge/wiki`
   - `knowledge/cases`
   - `sources/raw/财经`
   - `docs/标的深度研究`
   - `framework/reasoning-patterns.yaml` — 推理模式库（按 UP 的推理步骤分析）
4. For real-time market data, follow
   `skills/qing-stock-analysis/references/data-source-strategy.md`.
5. Distinguish evidence, interpretation, and inference.
6. Do not provide unconditional buy/sell commands. Always include trigger
   conditions, invalidation conditions, and data timestamp.

## Stock Monitor Context

The stock monitor configuration lives in `config/stock_monitor/`.

- `watchlist.yaml`: stock universe, themes, roles, and linkage checks.
- `positions.yaml`: private current holdings and costs. This file is ignored by
  Git.
- `positions.example.yaml`: safe template for positions.
- `strategy_pack.yaml`: reusable monitoring rules extracted from the local
  methodology and recent reviews.

When running from Hermes cron, always set the workdir to this repository root.
For local and cloud installs, prefer setting `HERMES_REPO_ROOT` to that path and
using it as the cron workdir.

## Git Discipline

- **Never use `git add -f` / `--force`** to bypass `.gitignore`. Files in
  `.gitignore` are excluded for a reason — `positions.yaml` contains private
  holding data, `storage/` and `.qdrant_data*` are auto-generated binaries.
- Use `git add -A` or `git add <file>` for staged changes.
- Before committing, verify with `git status --short` that no gitignored files
  are staged.

## Cron Script Architecture

Cron jobs reference scripts under `~/.hermes/scripts/` (the Hermes system scripts
directory). These are thin wrappers that delegate to the project's scripts:

```
~/.hermes/scripts/qing_stock_monitor_agent.py  →  project/scripts/hermes_stock_monitor_agent.py
~/.hermes/scripts/qing_stock_monitor_daily_review.py → project/scripts/hermes_stock_monitor_daily_review.py
~/.hermes/scripts/qing_stock_monitor_poll.py   →  project/scripts/qing_stock_monitor_poll.py
```

**Rule**: The `qing_` prefix files in `~/.hermes/scripts/` are STABLE entrypoints.
Never rename them. The `hermes_` files in the project can evolve freely. When
updating scripts, only modify the `hermes_` project versions — the wrappers
auto-delegate.

## Knowledge Maintenance

After adding new claims or updating existing ones (via raw document extraction),
run the full pipeline to sync Neo4j and Qdrant:

```
discover → Neo4j migrate → Qdrant rebuild → restart Agent
```

Full workflow documented in
[`docs/neo4j-relation-pipeline.md`](docs/neo4j-relation-pipeline.md).

## Task Decomposition: Pre-flight Check Protocol

**背景**: 2026-06-14 监控引擎瘦身 Subtask 4 中，Agent 陷入 `git show` 提取死循环（重复调用 >50 次），根因是未检查目标模块是否已存在，直接跳入执行模式。

**适用范围**: 任何"将函数/文件/代码从 A 迁移/拆分到 B"的任务场景（代码迁移、模块拆分、功能重构等）。

### 核心原则

> **先检查再动手** — 每次开始一个子任务前，必须先验证当前状态，识别已完成的 work，只做缺失的部分。

### 标准流程（3步）

```
Step 1 ── 检查目标是否存在
Step 2 ── 验证已有内容（如有）
Step 3 ── 只做缺失的部分
```

#### Step 1：检查目标

用最轻量的方式确认目标文件/模块当前状态：

```python
# ✅ 正确：先检查文件是否存在
ls path/to/target/module/__init__.py

# ✅ 正确：验证是否能导入
python -c "from project.module import func_a, func_b"
```

#### Step 2：验证已有内容

| 场景 | 验证方法 |
|------|---------|
| 目标文件存在 | `python -c "from ... import func1, func2, ..."` 逐个验证 |
| 全部导入成功 | ✅ 标记完成，跳过整个子任务 |
| 部分缺失 | 只提取缺失函数（`diff` 出差量） |
| 全部缺失 | 继续执行正常提取流程 |

#### Step 3：只做缺失的部分

- 用 `git log -S <function_name>` 找到含原实现的提交
- 用 `git show <commit>:<file>` 提取，不要自己重写
- 验证新实现的导入

### 死循环熔断机制

**检测条件**: 同一个 shell command（如 `git show`、`git log`）在同一个子任务中重复调用 ≥ 3 次，且每次返回相同或相近结果。

**触发动作**:
1. 立即停止当前命令调用
2. 打印 WARNING 日志（"疑似死循环，已熔断"）
3. 切换方案：
   - `git show` 卡住 → 用 `git diff` 或 `git log -p` 定位
   - 提取函数卡住 → 直接用 `import` 验证目标模块已有哪些函数
   - 参数不对 → 先 `git log --oneline` 看清提交列表再选 commit

### 案例复盘

```
❌ 错误模式（Subtask 4 死循环）:
  1. 目标: "创建 monitor/output/__init__.py，添加 alert_fingerprint"
  2. 直接执行: git show <commit>:<file> → 失败
  3. 重试: 换个 commit hash → 还是不对
  4. 再重试: 换个参数... → 无限循环，从未检查文件是否已存在

✅ 正确模式:
  1. 目标: 同上
  2. 预检: ls monitor/output/__init__.py → ✅ 已存在
  3. 验证: python -c "from monitor.output import alert_fingerprint" → ✅ 可用
  4. 结论: 跳过 Subtask，标记完成
```
