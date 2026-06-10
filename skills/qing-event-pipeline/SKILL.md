---
name: qing-event-pipeline
description: P0 事件驱动管线 — B站新内容 → 双人工门禁 → 自动执行
version: 1.0.0
triggers:
  - "提取claims"
  - "跳过"
  - "确认"
  - "修改"
  - "查看"
  - "状态"
  - "event pipeline"
  - "审核"
references:
  - docs/p0-event-driven-pipeline-design.md
  - scripts/event_pipeline_trigger.py
  - scripts/apply_pending_updates.py
  - src/qing_investment/agent/tools/pending_review_queue.py
---

# P0 事件驱动管线 Skill

## 概述

管理 UP（青枫浦上Q）新内容到 config 更新的全链路：

```
B站新动态 → 【门禁1: Claim 审核】→ 入库 → 【门禁2: Config 审核】→ 自动执行
```

## 触发词

用户消息匹配以下任一即触发本 skill：

| 触发词 | 含义 |
|--------|------|
| `提取claims` / `提取 claims` | 对当前/最近 B站内容提取 claims |
| `确认` / `确认 N` / `确认 N M` | 批准 pending items |
| `修改 N 字段 值` | 修改 pending item 后批准 |
| `跳过` | 拒绝全部 pending items |
| `查看 N` | 显示 pending item 完整内容 |
| `状态` / `审核状态` | 查询待审核队列 |
| `event pipeline` / `管线` | 询问管线状态 |

## 指令解析规则

### 1. Claim 审核阶段（B站新内容后）

用户收到 claims 摘要后回复：

| 用户输入 | 动作 |
|----------|------|
| `确认` | 批准该 batch 全部 claims |
| `确认 1 2` | 只批准序号 1 和 2 |
| `修改 2` + 新 YAML | 替换 claim 2 的内容后批准 |
| `跳过` | 拒绝该 batch 全部 claims |
| `查看 1` | 显示 claim 1 的完整 YAML |

**执行流程**：
1. 解析用户指令 → 调用 `pending_review_queue.approve/reject/modify`
2. 获取 approved claims → 写入 `knowledge/claims/`
3. 自动执行 `discover → Neo4j → Qdrant`
4. 生成 config preview → 写入 pending queue → 微信推送 config 建议

### 2. Config 审核阶段（claims 入库后）

用户收到 config 建议后回复：

| 用户输入 | 动作 |
|----------|------|
| `确认` | 执行该 batch 全部 config updates |
| `确认 1` | 只执行序号 1 |
| `修改 2 仓位 1成` | 修改 entry 2 的仓位后执行 |
| `跳过` | 拒绝该 batch 全部 updates |
| `查看 2` | 显示建议 2 的完整 YAML |

**执行流程**：
1. 解析用户指令 → 调用 `pending_review_queue.approve/reject/modify`
2. 获取 approved updates → 调用 `apply_pending_updates.py --batch-id <id>`
3. 自动执行：写入 YAML → Git commit → 重启 Agent

### 3. 状态查询

| 用户输入 | 响应 |
|----------|------|
| `状态` | 显示所有 pending batch 的汇总 |
| `状态 <batch_id>` | 显示指定 batch 的详情 |

## 微信消息格式

### Claims 审核摘要示例

```
📋 提取到 3 条 claims，请审核：

【claim-20260611-001】sector-theme
• 燃气轮机方向类比上一轮锂电池，机构都要买
• 置信度: high
• 相关标的: 杰瑞股份(002353)

【claim-20260611-002】operation
• 万泽股份回调到30.5-31.0是买点，0.5成仓
• 置信度: high

【claim-20260611-003】market-cycle
• 当前处于调整第17天，接近尾声
• 置信度: medium

━━━━━━━━━━━━━━━━━━━━
回复：
• 「确认」→ 全部入库
• 「确认 1 2」→ 只入库指定序号
• 「跳过」→ 全部丢弃
• 「查看 1」→ 显示完整内容
```

### Config 审核摘要示例

```
📋 配置更新建议（2条）：

【建议 1】watchlist 更新
• 002353: 新增 linked_claims claim-20260611-001
• 当前: 2条关联claims → 建议: 3条

【建议 2】entry_points 新增
• 000534 万泽股份
• 介入区间: 30.5-31.0
• 仓位: 0.5成 | 止损: 跌破30
• 赔率: 3:1
• 依据: claim-20260611-002: 万泽股份回调到30.5-31.0是买点

━━━━━━━━━━━━━━━━━━━━
回复：
• 「确认」→ 全部执行
• 「确认 1」→ 只执行指定序号
• 「修改 N 字段 值」→ 修改后执行
• 「跳过」→ 全部忽略
```

## 错误处理

| 场景 | 响应 |
|------|------|
| 无 pending batch | "📭 当前无待审核任务" |
| batch_id 不存在 | "❌ 未找到该批次，请用「状态」查看待审核列表" |
| 序号超出范围 | "❌ 序号 N 不存在，该 batch 只有 M 条" |
| Neo4j 连接失败 | "❌ 知识库连接失败，请检查 Neo4j 是否运行" |
| Git 冲突 | "⚠️ Git 提交冲突，请手动解决后重试" |

## 安全规则

1. **positions.yaml 永远不自动更新** — 真实持仓必须手动维护
2. **--auto-merge 禁止在生产环境使用** — 所有更新必须经过用户确认
3. **修改指令只支持简单字段** — 复杂结构调整需用户手动编辑 YAML
4. **每次执行前自动 git stash** — 防止未提交的本地改动丢失
5. **边界约束（硬性）**: 管线只自动建议 `entry_points` 和 `watchlist.linked_claims`。`market_framework` / `index_rules` / `sector_groups` / `positions.yaml` 永不纳入自动建议范围

## 自动建议范围

| 字段 | 自动建议？ | 说明 |
|------|-----------|------|
| `entry_points` | ✅ | operation claims 直接映射 |
| `watchlist.linked_claims` | ✅ | 机械关联 |
| `market_framework` | ❌ | 需综合判断，留给 15:20 复盘 |
| `index_rules` | ❌ | 非 claim 驱动 |
| `sector_groups` | ❌ | 需实时数据验证 |
| `positions.yaml` | ❌ **硬约束** | 永远手动 |
