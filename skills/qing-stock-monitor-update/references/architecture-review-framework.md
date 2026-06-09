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
