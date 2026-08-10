# 模式治理 v2.1 对齐实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.（本会话约束：不用 subagent，逐任务 commit，commit 已授权、push 等用户明说。）

**Goal:** 把 UP 教材复盘流与回测产出对齐到 v2.1 治理纪律：review skill 去掉"UP 优先"锚定、推理模式提名改走提案制（≥4 周窗口 + 跨 regime）、回测报告与 M0 验收补上"执行层规则回测"的定性说明。

**Architecture:** 全部是文档/skill 层对齐 + 一处报告生成逻辑补 caveat。不改 `src/qing_investment/`；不动推理引擎；不扩展 `apply_pattern_proposal.py`（提名提案人工评审后手工入库，YAGNI）。

**Tech Stack:** Markdown 文档编辑；Python（render_report）；pytest（`.venv/bin/pytest`，`tests/investment_engine/` 无 `__init__.py`）。

**背景（讨论结论，已核实）：**
- `skills/qing-learning-review/SKILL.md` Step 4 的 `agent-up-conflict` 条款写着"若仍矛盾→UP 优先"，与总计划 v2.1 第十一节"市场数据优先"正面冲突；`framework/contradiction-policy.md` 已核实无此条款，不用改。
- review skill 的 durable rule 目前只通向 framework 文档（trading-rules 等），推理模式类候选没有走 `framework/proposals/` 提案制，绕过 validation。
- `logs/m0-acceptance.md` 已有 caveat 节（条件冻结、"UP明确看好"恒 False 等），但缺两条：回测绕过 MarketGate/SectorGate 门控（`scripts/backtest_buy_signals.py` 调 `evaluate()` 未传 gate 结果）；stock_pool 为当前快照、套用历史日期存在前视偏差。`logs/backtest_buy_signals_20260808.md` 本身没有任何定性说明。
- `src/investment_engine/pattern_eval/apply.py` 只接受 validation 回填类提案（`changes` 列表 + SETTABLE 白名单），模式提名提案**不能**用它应用。

**验收标准：**
1. `grep -rn "UP 优先" skills/` 无命中（历史合并记录除外）；
2. review skill Step 5 含 A/B 分流、提名门槛（≥4 周 + ≥2 种市场阶段）、提案模板；
3. 新增 `tests/investment_engine/test_backtest_report.py` 通过，`tests/investment_engine` 全绿（当前 168 → 完成后 169）；
4. `logs/m0-acceptance.md` 与 `logs/backtest_buy_signals_20260808.md` 均含"执行层规则回测、无门控、config 前视、非方法论证据"定性说明；
5. `scripts/backtest_buy_signals.py` 新生成的报告自动带定性节。

**Out of scope：** `framework/learning-update-protocol.md` 的 prompt 同步条款（M4 范畴）；`apply.py` 支持提名提案自动应用；周五 validation 提案例行化（单独议题）。

---

### Task 1: review skill 删除"UP 优先"条款

**Files:**
- Modify: `skills/qing-learning-review/SKILL.md`（Step 4 矛盾分类表）

- [x] **Step 1: 改写 agent-up-conflict 行**

old_string（Step 4 表内唯一行）：

```
| agent-up-conflict | Qing-Agent 分析 vs UP 观点矛盾 | 检查知识库是否完整→补 claims→重新分析；若仍矛盾→UP 优先 |
```

new_string：

```
| agent-up-conflict | Agent 分析 vs UP 观点矛盾 | 检查知识库是否完整→补 claims→重新分析；若仍矛盾→**市场数据优先**（一级信息>二级>三级，价格/量能证据>任何观点——总计划 v2.1 第十一节），UP 观点仅作对照标签；无法裁决时标 true-conflict 高亮提醒用户 |
```

- [x] **Step 2: 核实无残留**

Run: `grep -rn "UP 优先" skills/`
Expected: 无输出（若仅剩"历史合并记录"类说明性提及，保留并注明）。

- [x] **Step 3: Commit**

```bash
git add skills/qing-learning-review/SKILL.md
git commit -m "docs: review skill 删除\"UP 优先\"条款，agent-up-conflict 改市场数据优先（v2.1 对齐）"
```

---

### Task 2: review skill Step 5——durable rule 分流 + 模式提名门槛 + 提案模板

**Files:**
- Modify: `skills/qing-learning-review/SKILL.md`（Step 5 整节改写；"关键坑"一节补一条）

- [x] **Step 1: Step 5 开头插入分流与门槛**

old_string：

```
### Step 5: Durable Rule 筛选

进 framework 条件（满足其一）：
```

new_string：

```
### Step 5: Durable Rule 筛选

**候选分流（v2.1 对齐，2026-08-10 起）**：durable rule 候选先分两类，去向不同——

| 类型 | 例子 | 去向 |
|------|------|------|
| A. 操作纪律类 | 买卖条件、仓位、风控线（如"赚20%砍半仓"） | 原 Review→Write 管道（见 qing-learning 总入口），写 `framework/trading-rules.md` 等 |
| B. 推理模式类 | 可复用的分析/推导步骤（如"涨价链五步拆解"） | **禁止直接写 framework 文档或 `framework/reasoning-patterns.yaml`**；生成模式提名提案 `framework/proposals/YYYYMMDD-<name>.yaml`，经市场验证 + 人审后才入库 |

**推理模式提名门槛**（三条同时满足，否则留在 wiki/claims 层继续观察）：

1. 提名复盘窗口 **≥4 周**（drift/矛盾复盘仍默认 7 天，两者解耦——模式提名需单独拉长窗口汇总）；
2. 同一逻辑在 **≥2 种市场阶段**（主升/震荡/调整/恐慌）对应的复盘内容中出现（防单 regime 过拟合）；
3. 提案附证据：每次出现的日期 + 当日市场阶段 + 原文摘录（source path + quote）。

**提名提案模板**（不用 `scripts/apply_pattern_proposal.py` 应用——该脚本只接受 validation 回填；人审通过后手工入库 `framework/reasoning-patterns.yaml`）：

```yaml
proposal_id: YYYYMMDD-pattern-nomination-<slug>
source: up-review
generated_at: '<ISO timestamp>'
status: pending-review   # pending-review → approved → applied | rejected
evidence:
  window: {start: 'YYYY-MM-DD', end: 'YYYY-MM-DD'}
  occurrences:
    - date: 'YYYY-MM-DD'
      regime: 震荡        # 主升/震荡/调整/恐慌
      source: sources/raw/财经/<file>.md
      quote: "<原文摘录>"
candidate_pattern:
  pattern_id: <snake_case>
  name: <名称>
  description: <何时使用、解决什么问题>
  trigger: [<客观数据特征，不含"UP说">]
  data_requirements: [<每步所需数据及获取通道>]
  steps: [<推理步骤>]
  falsification: [<证伪条件>]
  validation:
    historical_hit_rate: null   # 入库前必须经回测/盲测回填
    applicable_regime: null
    known_failures: []
```

进 framework 条件（A 类操作纪律，满足其一）：
```

- [x] **Step 2: 改写 Step 5 第 6 条（方法论框架对比的对比目标）**

old_string：

```
6. **方法论框架对比**：将本次 review 窗口内的 methodology claims（claim_type=methodology, timeframe=permanent）与 `framework/market-breadth-framework.md` 和 `knowledge/wiki/投资方法论/大盘分析方法论.md` 交叉对比。标记状态：已收录 / 新方法论（建议追加）/ 矛盾（需人工裁决）。矛盾归入 contradiction 分类处理。若发现新方法论，在报告中标注"建议运行更新方法论"。
```

new_string：

```
6. **方法论框架对比**：将本次 review 窗口内的 methodology claims（claim_type=methodology, timeframe=permanent）与 `framework/reasoning-patterns.yaml`、`framework/market-breadth-framework.md` 和 `knowledge/wiki/投资方法论/大盘分析方法论.md` 交叉对比。标记状态：已收录 / 新方法论 / 矛盾（需人工裁决）。矛盾归入 contradiction 分类处理。**新方法论属推理模式类——按上方提名门槛生成 proposals 提案，不再直接追加进 framework 文档。**
```

- [x] **Step 3: "关键坑"一节补一条**

old_string：

```
- **Review 后的 Framework 写入**：本 skill 是只读分析，但用户 workflow 通常要求 review 后将 durable rules 写入 framework。写入操作不属于本 skill 职责——详见 `qing-learning` 总入口 skill 的「Review→Write 工作流」章节。本 skill 的输出（报告 + durable rule 候选列表）是下游写入操作的输入。
```

new_string：

```
- **Review 后的 Framework 写入**：本 skill 是只读分析，但用户 workflow 通常要求 review 后将 durable rules 写入 framework。写入操作不属于本 skill 职责——详见 `qing-learning` 总入口 skill 的「Review→Write 工作流」章节。本 skill 的输出（报告 + durable rule 候选列表）是下游写入操作的输入。
- **推理模式类不走 framework 文档**：UP 复盘提炼出的分析/推导步骤是模式提名，必须走 `framework/proposals/` 提案制（门槛见 Step 5），经市场验证 + 人审后才入 `reasoning-patterns.yaml`。直接写入 = 绕过 validation，回 v2.0 老路。
```

- [x] **Step 4: Commit**

```bash
git add skills/qing-learning-review/SKILL.md
git commit -m "docs: review skill durable rule 分流——推理模式类改走 proposals 提案制（≥4周+跨regime门槛）"
```

---

### Task 3: qing-learning 总入口 Review→Write 工作流增加提案分支

**Files:**
- Modify: `skills/qing-learning/SKILL.md`（「Review→Write 工作流」节）

- [x] **Step 1: 改写流程图**

old_string：

```
qing-learning-review（只读）
  → 输出：review 报告 + durable rule 候选列表
  → 用户确认哪些规则写入 framework
  → Agent 执行写入（patch trading-rules.md / market-cycle-framework.md / stock-analysis-playbook.md）
  → git add + git commit
```

new_string：

```
qing-learning-review（只读）
  → 输出：review 报告 + durable rule 候选列表（按 A 操作纪律 / B 推理模式 分流标注）
  → 用户确认哪些规则写入 framework
  → A 类（操作纪律）：Agent 执行写入（patch trading-rules.md / market-cycle-framework.md / stock-analysis-playbook.md）
  → B 类（推理模式）：生成 framework/proposals/ 提名提案（模板见 review skill Step 5），市场验证 + 人审后才入 reasoning-patterns.yaml
  → git add + git commit
```

- [x] **Step 2: 写入目标文件表加一行**

old_string：

```
| 个股分析 playbook | `framework/stock-analysis-playbook.md` |
```

new_string：

```
| 个股分析 playbook | `framework/stock-analysis-playbook.md` |
| 推理模式（分析/推导步骤） | ❌ 不直接写文件——生成 `framework/proposals/` 提名提案，市场验证 + 人审后入 `framework/reasoning-patterns.yaml` |
```

- [x] **Step 3: "禁止"清单加一条**

old_string：

```
- review skill 直接修改 framework 文件（违反只读职责）
- 未确认就 commit（用户可能想先检查 diff）
```

new_string：

```
- review skill 直接修改 framework 文件（违反只读职责）
- 未确认就 commit（用户可能想先检查 diff）
- 推理模式类规则直接写 framework/*.md 或 reasoning-patterns.yaml（必须走提案制，v2.1 对齐）
```

- [x] **Step 4: Commit**

```bash
git add skills/qing-learning/SKILL.md
git commit -m "docs: qing-learning Review→Write 工作流增加推理模式提案分支"
```

---

### Task 4: 回测定性说明（脚本 caveat + 两份 log 补注）

**Files:**
- Test: `tests/investment_engine/test_backtest_report.py`（新建；目录无 `__init__.py`，保持如此）
- Modify: `scripts/backtest_buy_signals.py:126-131`（render_report 结尾）
- Modify: `logs/m0-acceptance.md`（「回测口径与 caveat」节补两条 + 一句定性）
- Modify: `logs/backtest_buy_signals_20260808.md`（末尾追加「定性补充」节）

- [x] **Step 1: 写失败测试**

新建 `tests/investment_engine/test_backtest_report.py`：

```python
"""render_report 必须带定性说明：执行层规则回测，非方法论有效证据。"""
from scripts.backtest_buy_signals import render_report


def _result() -> dict:
    return {
        "params": {"start": "2026-04-27", "end": "2026-08-07",
                   "horizons": (5,), "universe_size": 2, "trading_days": 3},
        "signals": [],
        "stats": {"5": {"samples": 1, "hits": 1, "hit_rate": 1.0,
                        "avg_return": 0.01}},
        "skipped_no_data": {},
    }


def test_report_contains_caveats():
    md = render_report(_result())
    assert "# 买入信号回测报告" in md
    assert "执行层规则" in md
    assert "MarketGate" in md and "SectorGate" in md
    assert "前视" in md
    assert "不能作为方法论有效的证据" in md
```

- [x] **Step 2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/investment_engine/test_backtest_report.py -q`
Expected: FAIL（`assert "执行层规则" in md` 不成立）

- [x] **Step 3: 改 render_report，结尾加定性节**

old_string（`scripts/backtest_buy_signals.py:126-131`）：

```python
    if result["skipped_no_data"]:
        lines += ["", "## 数据缺口（如实标注）", ""]
        for code, n in sorted(result["skipped_no_data"].items()):
            lines.append(f"- {code}: {n} 个交易日无缓存数据")
    lines += ["", "> 数据时间戳: K线缓存 infra/data/kline_cache.db；本报告不构成投资建议。"]
    return "\n".join(lines)
```

new_string：

```python
    if result["skipped_no_data"]:
        lines += ["", "## 数据缺口（如实标注）", ""]
        for code, n in sorted(result["skipped_no_data"].items()):
            lines.append(f"- {code}: {n} 个交易日无缓存数据")
    lines += [
        "",
        "## 定性说明（必读）",
        "",
        "- 本报告回测的是**执行层规则**（stock_pool 介入区间 + 量价条件），"
        "不是 UP 观点本身，也不是推理模式；结果**不能作为方法论有效的证据**"
        "（方法论验证以 M1 盲测 / 影子双轨为准）。",
        "- 回测未加载 MarketGate（大盘窗口）/ SectorGate（板块阶段）两道前置门控，"
        "信号比生产环境宽松。",
        "- stock_pool 为当前快照，套用到历史日期存在前视偏差（方向不定）。",
        "- 「近3日缩量 / MA20上方」读缓存最新窗口，对历史信号日为冻结常量。",
        "",
        "> 数据时间戳: K线缓存 infra/data/kline_cache.db；本报告不构成投资建议。",
    ]
    return "\n".join(lines)
```

- [x] **Step 4: 跑测试确认通过 + 全量回归**

Run: `.venv/bin/pytest tests/investment_engine/test_backtest_report.py -q`
Expected: 1 passed

Run: `.venv/bin/pytest tests/investment_engine -q`
Expected: 169 passed（168 + 新增 1）

- [x] **Step 5: `logs/backtest_buy_signals_20260808.md` 末尾追加**

在文件末尾（"> 数据时间戳" 行之后）追加：

```markdown

## 定性补充（2026-08-10）

- 本报告回测的是**执行层规则**（stock_pool 介入区间 + 量价条件），不是 UP 观点本身，也不是推理模式；结果**不能作为方法论有效的证据**（方法论验证以 M1 盲测 / 影子双轨为准）。
- 回测未加载 MarketGate / SectorGate 两道前置门控，信号比生产环境宽松。
- stock_pool 为当前快照，套用到历史日期存在前视偏差（方向不定）。
- 「近3日缩量 / MA20上方」为缓存最新窗口的冻结常量（详见 `logs/m0-acceptance.md` caveat 节）。
```

- [x] **Step 6: `logs/m0-acceptance.md` caveat 节补两条 + 定性句**

old_string（「回测口径与 caveat」节第 3 条）：

```
- **"UP明确看好"条件恒为 False**：stock_pool 配置的 claim_basis 为空，6 项条件实际可用 5 项，候选阈值为 ≥4。本轮回测本质是"介入区间+量价纪律"机械条件的来源中立回测。
```

new_string：

```
- **"UP明确看好"条件恒为 False**：stock_pool 配置的 claim_basis 为空，6 项条件实际可用 5 项，候选阈值为 ≥4。本轮回测本质是"介入区间+量价纪律"机械条件的来源中立回测。
- **门控绕过**（2026-08-10 补）：回测调 `BuySignalRuleEngine.evaluate()` 未传 MarketGate / SectorGate 结果（`src/qing_investment/monitor/rules/__init__.py` 中 None 不拦截），1507 个信号为无门控版，比生产环境宽松。
- **config 前视**（2026-08-10 补）：stock_pool 标的池与介入区间为当前快照，套用到 2026-04~08 历史日期，存在前视偏差（方向不定）。
- **定性**（2026-08-10 补）：本回测验证的是执行层规则，不是 UP 观点本身，也不是推理模式；结果**不能作为方法论有效的证据**。方法论验证以 M1 盲测（`logs/m1-baseline-20260808.md`）与影子双轨为准。
```

- [x] **Step 7: Commit**

```bash
git add tests/investment_engine/test_backtest_report.py scripts/backtest_buy_signals.py logs/backtest_buy_signals_20260808.md logs/m0-acceptance.md
git commit -m "fix: 回测报告与 M0 验收补定性说明——执行层规则回测（无门控+config前视），非方法论证据"
```

---

## Self-Review 记录

- Spec 覆盖：三事项 → Task 1+2+3（事项 1、2 拆三个文件）、Task 4（事项 3）。✅
- 占位符：无 TBD/TODO；文档改动均给出 old/new 原文；代码改动给出完整代码。✅
- 一致性：提案模板字段与 M1 提案（`framework/proposals/20260809-pattern-validation-m1.yaml`）风格一致（proposal_id/source/generated_at/evidence），新增 `candidate_pattern` 与 `status` 为提名类专有，已注明不走 apply.py。测试断言字符串与实现文本逐字一致。✅

## 执行记录（2026-08-10）

| Task | Commit | 结果 |
|---|---|---|
| 1 | f192c81 | review skill "UP 优先"已删；计划外发现 `qing-fupan-morning-usage/references/ops-traps.md` 陷阱1 有同条款，保留历史案例并标注废止（同 commit） |
| 2 | 381e26b | Step 5 分流+门槛+模板、第 6 条改写、关键坑补一条，一次 commit |
| 3 | 3794b7c | 流程图/目标文件表/禁止清单三处 |
| 4 | 00451c7 | TDD：新测试先红后绿；`tests/investment_engine` 169 passed（168+1） |

验收复核：`grep -rn "UP 优先" skills/` 仅剩 ops-traps.md 历史引文（下方已标注废止）；定性说明四处（脚本 render_report、新测试、两份 log）均已落地。
