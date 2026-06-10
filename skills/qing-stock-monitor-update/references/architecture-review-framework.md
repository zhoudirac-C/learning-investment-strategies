# Architecture Review Framework — 配置架构系统性Review方法论

> 用于对 config/stock_monitor/ + cron 任务 + Agent 链路做**全链路架构Review**。
> 区别于 `config-health-check.md`（配置完整性检查清单）——本文件是 Review 的结构化框架，不是 lint 规则。

---

## 何时触发

- 用户说 "review 我的配置" / "看看我的系统设计" / "架构有什么问题"
- 用户质疑系统性能（"为什么总觉得不够好""粗糙在哪里"）
- 用户想系统性优化时

---

## Review 框架（四步法）

### Step 1：现状架构总览

画出当前系统的分层架构图（数据层→配置层→知识层→Agent层→Cron层），标注每层的职责和数据流。

**目的**：让所有参与者对齐"系统长什么样"，暴露出模块之间缺失的连接。

### Step 2：缺陷分析（按严重程度）

按以下维度逐一检查：

| 维度 | 检查问题 | 常见缺陷模式 |
|------|---------|-------------|
| Cron设计 | 任务数量是否合理？是否有重复？任务间是否有状态传递？ | 同一prompt跑多个时间点；任务间无状态共享 |
| Config膨胀 | watchlist是否超过1000行？是否有永不过期的数据？ | 历史数据堆积；缺少生命周期管理 |
| 手动链路 | Claims→操作之间有多少步是手动的？ | 多步手动操作链；更新容易遗漏 |
| 状态桥接 | entry_points 是否只是文档而非触发器？ | 缺少条件单自动触发机制 |
| 闭环反馈 | 复盘结果是否自动反馈到次日策略？ | 复盘→策略调整全手动 |

### Step 3：成熟方案设计

基于缺陷分析，设计改进架构。核心原则：
- **引入中间层**：当发现两层之间断裂时，通常需要新增一个持久化状态层
- **精简高频+增强低频**：减少高频重复任务，增强关键节点的分析深度
- **量化做量化的事，LLM做LLM的事**：价格触发用规则，方向判断用LLM

输出：改进后的架构图 + 每个改进项的具体设计。

### Step 4：实施优先级

按复杂度-收益矩阵排序：

| 优先级 | 判断标准 |
|--------|---------|
| P0 | 高收益 + 低复杂度 → 立即实施 |
| P1 | 高收益 + 高复杂度 → 列入计划 |
| P2 | 中等收益 → Next Quarter |

---

## 案例：2026-06-08 Review

本次Review发现5大缺陷，提出4项改进：

| # | 缺陷 | 改进方案 | 优先级 |
|---|------|---------|--------|
| 1 | Cron任务差异化不足（同一prompt跑9个时间点）| 9个节点各配独立prompt + 共享daily_state | P0 |
| 2 | Watchlist膨胀（3718行，无生命周期）| 增加lifecycle_stage字段+降级机制 | P1 |
| 3 | Claims→操作全手动（6-7步）| 自动桥接脚本 | P1-P2 |
| 4 | entry_points只是文档，无触发 | 条件单机制 | P1 |
| 5 | 复盘与盘中割裂 | daily_state.json状态机串联 | P0 |

核心方案：引入 **daily_state.json 状态机** 作为 Layer 1 中间层，串联所有cron任务和Agent。

完整文档：`docs/config-cron-architecture-review.md`

---

## 输出规范

架构Review必须**输出为项目文档**（`docs/` 目录下），原因：
- 用户明确偏好：分析结果落文档，方便后续继续讨论（"记忆不会丢失"）
- Git版本控制：可以追踪架构演进的每个版本
- 跨会话引用：后续cron任务或Agent可以引用这些文档

文档结构模板参见 `docs/config-cron-architecture-review.md`。

## 新增：实施状态核查（Implementation Audit）

当用户问"XX改造做完了吗""现在还有问题吗"时，必须执行**实施状态核查**——对比设计文档 vs 代码实际状态，找出"设计有但实现缺"的缺口。

### 核查方法论

| 步骤 | 操作 | 产出 |
|------|------|------|
| 1. 定位设计文档 | 读取 `docs/config-cron-architecture-review.md` 或相关设计文档 | 改造清单（含优先级） |
| 2. 逐条检查实现 | 对每条改造项，grep 代码库确认是否实现 | 实现/未实现/部分实现 |
| 3. 运行功能验证 | 检查关键文件是否存在、服务是否运行、数据是否生成 | 功能正常/异常 |
| 4. 分级输出 | P0=功能完全失效 / P1=功能受限 / P2=设计意图未达成 | 优先级缺口清单 |

### 关键核查点（基于2026-06-10实践）

**Prompt 层改造**：
- `market_analyst.txt` 是否包含交易者人格 + 反保守自检 + 赔率框架？
- `stock_analyst.txt` 是否包含赔率分析 JSON 字段？
- `style_writer.txt` 是否包含机会发现表达强化？
- `trader_mindset.txt` 是否独立承载人格定义（而非空壳指向）？

**Context Builder**：
- `context_builder.py` 是否存在且被 `retrieve_knowledge()` 调用？
- 方向关键词是否硬编码（vs 动态提取）？
- Qdrant 语义召回 query 是否利用当前技术面描述？

**Daily State 状态机**：
- `daily_state.json` 文件是否存在？（⚠️ 最常见失效点）
- `sync_daily_state.py` 是否成功解析 ````daily_state` 代码块？
- `stock_monitor.py::format_agent_analysis_context()` 是否注入 daily_state 摘要？
- 9 个 cron job 的差异化 prompt 文件（`cron_*.txt`）是否存在且被加载？

### §4.3 Context Builder 核查（2026-06-10 发现）

**背景**：`docs/config-cron-architecture-review.md` §4.3 仍标 ❌"未实现"，但代码实际已全部落地。

**核查方法**（当看到 ❌ 时，先查代码再下结论）：

```bash
# 1. 检查 context_builder.py 是否存在
ls src/qing_investment/agent/tools/context_builder.py

# 2. 检查 retrieve_knowledge 是否调用了它
grep -n "context_builder" src/qing_investment/agent/graph/nodes.py

# 3. 检查 Neo4j 调用的方法是否存在
grep -n "def get_claims_about_stock" src/qing_investment/agent/tools/neo4j_client.py
grep -n "def get_sector_themes" src/qing_investment/agent/tools/neo4j_client.py
```

**实际实现状态**：

| 功能 | 位置 | 状态 |
|------|------|------|
| Neo4j 图遍历（Stock→ABOUT→Claim） | `context_builder.py::build_stock_context()` → `neo4j_client.get_claims_about_stock()` | ✅ 已实现 |
| Qdrant 语义召回（动态 query 生成） | `context_builder.py::build_market_context()` 第 347-396 行 | ✅ 已实现 |
| 浓度控制（最多 3 条，每条约 50 字） | `build_stock_context(max_claims=3)` + `_summarize_claim(max_len=50)` | ✅ 已实现 |
| 集成到 retrieve_knowledge | `nodes.py` 第 1014-1096 行 | ✅ 已实现 |
| Reasoning pattern 排序 | `_score_claim_relevance(active_patterns=...)` 第 158-168 行 | ✅ 已实现 |
| 方向信号汇总 | `build_market_context()` 第 411-423 行 → `direction_signals` | ✅ 已实现 |

**更新设计文档**：确认代码已实现后，必须同步更新 `docs/config-cron-architecture-review.md` 的状态标记。

### 常见失效模式

| 失效模式 | 现象 | 排查命令 |
|---------|------|---------|
| daily_state.json 不存在 | 观点连续性完全失效，每个 cron 孤立运行 | `ls config/stock_monitor/daily_state.json` |
| sync_daily_state 解析失败 | LLM 输出不含 ````daily_state` 代码块，或格式错误 | `python scripts/sync_daily_state.py --dry-run` |
| cron_*.txt 未加载 | 所有节点输出风格一致，无差异化 | 检查 `stock_monitor.py` 中 `prompt_path.exists()` 日志 |
| trader_mindset.txt 空壳 | 人格定义内嵌在 market_analyst.txt，无法独立迭代 | `cat prompts/system/trader_mindset.txt` |

---

## 常见陷阱

### 陷阱1：把三条管线的修改混在一个地方提方案

当系统有手动触发（skill）、定时触发（cron）、事件触发（ingestion pipeline）三条独立管线时，review 输出必须分别标注每条改动属于哪条管线。

**反面案例（2026-06-09）**：Agent 建议在 qing-stock-monitor-update skill 的 Step 0 加入 cron 管线的决策树 → 用户纠正："skill 不是只能手动触发吗？定时任务和事件驱动会调用 skill 吗？要改也是分别改三个地方"。

**正确做法**：
- 手动触发 → 改 skill 工作流（SKILL.md）
- 定时触发 → 改 cron prompt / cron 配置 / stock_monitor.py 代码
- 事件触发 → 改 qing-learning ingestion 流程

### 陷阱2：cron 命令子命令名

更新 cron job 的 prompt 字段使用 `hermes cron edit <job_id> --prompt "..."`，不是 `hermes cronjob update`（该子命令不存在）。

### 陷阱3：cron prompt vs schedule prompt 易混淆

- cron job 的 prompt 字段（`hermes cron edit --prompt`）= LLM 在 cron 运行时收到的指令
- strategy_pack.yaml 的 `agent_analysis_schedule` 中的 `prompt` 字段 = `stock_monitor.py::format_agent_analysis_context()` 读取并注入到上下文的节点专属指令文件名
- 两者互补但独立：cron prompt 告诉 LLM "读哪个文件"，schedule prompt 告诉 stock_monitor "注入哪个文件内容"

### 陷阱4：cron 走 qing-agent 时，system prompt 的正确位置

当 cron 任务通过 `qing_stock_monitor_agent.py` → `stock_monitor.py --agent-json-context` → POST qing-agent 的链路运行时：

- **LLM 调用发生在 qing-agent 内部**，使用的是 qing-agent 自己的 system prompt（`market_analyst.txt`、`style_writer.txt` 等）
- **cron job 的 prompt 字段和 cron_*.txt 不会被 qing-agent 读取**——它们只在 qing-agent 不可达时的 fallback 文本路径生效
- 需要注入 persona、赔率框架、daily_state 输出格式等系统级指令时，**必须修改 qing-agent 的 prompt 文件**（如 `prompts/system/market_analyst.txt`），而非 cron prompt

**反面案例（2026-06-09）**：Agent 在 9 个 cron prompt 中引用 cron_*.txt、在 cron_*.txt 中添加 daily_state 代码块要求，但这些改动对 LLM 路径完全无效——因为 qing-agent 不读 cron prompt。用户纠正："定时任务不应该直接调我们本地的 q-agent 吗？是直接调用大模型吗？那我们的设计不就全部没用了" → 修正：daily_state 指令移入 market_analyst.txt，cron prompt 恢复简洁 fallback 版本。

### 陷阱5：bare `except: pass` 隐藏了完全失效的功能

**反面案例（2026-06-10）**：`context_builder.py` 从第一天起 4 处 `max(dates)` / `datetime.strptime()` 因 Neo4j 返回 `neotime.Date` 对象统一抛 `TypeError`。但调用处都用裸 `except: pass` 捕获：

```python
try:
    dt = datetime.strptime(source_date, "%Y-%m-%d")
    ...
except Exception:
    pass  # ← 吞掉了 TypeErrors，context_builder 对 LLM 贡献为零
```

结果：429 行代码全部落地，**但没有一行真正工作**。文档标记 ✅"已实现"，但实际效果等于 ❌。

**核查清单**（当看到 `except Exception: pass` 时必查）：
1. 这个 `try` 块内的逻辑是否真的被完整执行过？
2. 如果失败，fallback 是什么？是功能受限还是功能消失？
3. 有没有办法给这个功能加一个单独的测试/验证路径？（如 `verify_context_builder()` 单节点测试）

**正确做法**：
- 宁可在临界点写多行类型处理，也不要裸 `except: pass`
- `except` 必须标注具体异常类型（`TypeError`, `ValueError` 等），至少要 `except Exception as e: logger.warning(...)`
- 对跨数据源（Neo4j vs Qdrant vs mem0）的字段，必须统一类型后再操作——不要假设返回值是某种类型
- 新增功能必须做端到端验证（如 `build_market_context()` 传入真实持仓 + Neo4j 客户端测试输出），不能只测"import 不报错"
