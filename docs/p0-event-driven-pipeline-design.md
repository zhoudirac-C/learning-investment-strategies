# P0 事件驱动管线 + 双人工门禁设计文档

> 版本: 2026-06-11 v1.0
> 触发: 用户要求实现方案 A（微信交互式确认），且 claims 和 config 建议都必须经人工审核

---

## 一、核心约束（不可违背）

1. **Claim 门禁**: 所有新提取的 claims 必须经用户审核后才能写入 knowledge/claims/ 和入库（Neo4j/Qdrant）
2. **Config 门禁**: 所有 config 更新建议（watchlist/entry_points）必须经用户审核后才能写入 YAML
3. **自动执行范围**: 用户确认后，脚本自动完成 discover → Neo4j → Qdrant → Agent 重启 → Git commit

---

## 二、管线架构（五段式）

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        P0 事件驱动管线 v1.0                              │
│                                                                         │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────────────┐ │
│  │ 触发层      │    │ 采集层      │    │ 【门禁 1】Claim 审核         │ │
│  │ (B站监控)   │───▶│ (拉取+保存) │───▶│ 用户审核 claims 准确性       │ │
│  └─────────────┘    └─────────────┘    └─────────────────────────────┘ │
│                                                   │ 确认后              │
│                                                   ▼                     │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ 处理层: C2 编排提取 claims → discover → Neo4j → Qdrant         │   │
│  │ (现有流程，全自动)                                               │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                   │                     │
│                                                   ▼                     │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ 桥接层: sync_claims_to_config.py --preview                      │   │
│  │ 扫描新 claims → 生成 watchlist + entry_points 建议              │   │
│  │ 写入待审核队列（SQLite）→ 微信推送摘要                          │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                   │                     │
│                                                   ▼                     │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ 【门禁 2】Config 审核                                            │   │
│  │ 用户微信回复: 确认 / 修改 / 跳过 / 查看详情                      │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                   │ 确认后              │
│                                                   ▼                     │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ 执行层: 自动写入 config → Agent 重启 → Git commit + push       │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 三、各层详解

### 3.1 触发层（已有 ✅）

| 组件 | 文件 | 状态 |
|------|------|------|
| B站动态监控 | `scripts/bilibili_notify.py` | ✅ 每 10 分钟运行 |
| 微信通知 | stdout → Hermes cron | ✅ 新内容到达时推送 |

**当前行为**: B站新内容 → 保存到 `sources/raw/财经/` → 微信推送原文+OCR+评论

**需要改造**: 微信消息末尾增加指令提示：
```
📢 青枫浦上Q 新动态
...
━━━━━━━━━━━━━━━━━━━━
💡 回复「提取claims」开始提取观点
💡 回复「跳过」忽略本条
```

### 3.2 【门禁 1】Claim 审核

**这是新增的核心流程**。

#### 3.2.1 用户交互流程

```
你收到 B站新动态通知
    │
    ▼
回复「提取claims」
    │
    ▼
Hermes 触发 C2 编排管线（qing-learning-claim skill）
    │
    ▼
生成 claims（YAML 格式，含 claim_id/statement/type/confidence/source_date）
    │
    ▼
微信推送 claims 摘要：
━━━━━━━━━━━━━━━━━━━━
📋 提取到 3 条 claims，请审核：

【claim-20260611-001】sector-theme
• 燃气轮机方向类比上一轮锂电池，机构都要买
• 置信度: high | 来源: 2026-06-11 动态
• 相关标的: 杰瑞股份(002353), 万泽股份(000534)

【claim-20260611-002】operation
• 万泽股份回调到30.5-31.0是买点，0.5成仓
• 止损: 跌破30且30分钟不能收回
• 置信度: high

【claim-20260611-003】market-cycle
• 当前处于调整第17天，接近尾声
• 置信度: medium

回复：
• 「确认」→ 全部入库
• 「确认 1 2」→ 只入库 claim 1 和 2
• 「修改 2 仓位 1成」→ 修改 claim 2 后入库
• 「跳过」→ 全部丢弃
• 「查看 1」→ 显示 claim 1 完整内容
━━━━━━━━━━━━━━━━━━━━
```

#### 3.2.2 技术实现

- **待审核队列**: SQLite 数据库 `~/.hermes/pending_claims.db`
- **表结构**:
  ```sql
  CREATE TABLE pending_claims (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      batch_id TEXT NOT NULL,          -- 批次ID（对应一次B站动态）
      claim_index INTEGER,             -- 批次内序号（1,2,3...）
      claim_yaml TEXT NOT NULL,        -- 完整 YAML 内容
      source_file TEXT,                -- 来源 raw 文件路径
      status TEXT DEFAULT 'pending',   -- pending | approved | rejected | modified
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      decided_at TIMESTAMP,
      user_decision TEXT               -- 用户原始回复
  );
  ```
- **C2 编排触发**: Hermes 识别用户回复「提取claims」→ 调用 `qing-learning-claim` skill → 提取完成后写入 pending_claims 表 → 微信推送摘要

#### 3.2.3 审核后自动执行

用户确认后：
1. 将 approved claims 写入 `knowledge/claims/`
2. 自动执行 `discover → Neo4j → Qdrant`（现有脚本）
3. 完成后微信通知：「✅ 3 条 claims 已入库，Neo4j + Qdrant 同步完成」

### 3.3 桥接层（改造现有脚本）

#### 3.3.1 sync_claims_to_config.py --preview 改造

新增 `--preview` 模式，输出结构化 JSON：

```python
# 命令: python scripts/sync_claims_to_config.py --preview --days 1
# 输出 JSON:
{
  "batch_id": "20260611_143052",
  "generated_at": "2026-06-11T14:30:52",
  "new_claims_count": 3,
  "watchlist_updates": [
    {
      "index": 1,
      "code": "002353",
      "name": "杰瑞股份",
      "action": "add_linked_claim",
      "claim_id": "claim-20260611-001",
      "current_linked_claims": 2,
      "suggested_linked_claims": 3,
      "rationale": "新 claim 提及该标的"
    }
  ],
  "entry_points_suggestions": [
    {
      "index": 2,
      "code": "000534",
      "name": "万泽股份",
      "action": "create",  // 或 "update"
      "entry_zone": "30.5-31.0",
      "position_ratio": "0.5成",
      "stop_loss": "跌破30且30分钟不能收回",
      "odds_ratio": "3:1",
      "claim_basis": "claim-20260611-002: 万泽股份回调到30.5-31.0是买点",
      "rationale": "UP明确给出介入区间和仓位",
      "conflict_check": null  // 或 "与现有 entry 冲突: ..."
    }
  ],
  "conflicts": [],  // 与现有 config 的冲突列表
  "summary_for_wechat": "📋 3条claims → 1只watchlist更新 + 1个entry_point建议"
}
```

#### 3.3.2 待审核队列（Config 审核）

SQLite 表：
```sql
CREATE TABLE pending_config_updates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id TEXT NOT NULL,
    update_index INTEGER,
    update_type TEXT,        -- 'watchlist' | 'entry_point'
    target_code TEXT,
    current_value TEXT,      -- JSON 序列化
    suggested_value TEXT,    -- JSON 序列化
    rationale TEXT,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    decided_at TIMESTAMP,
    user_decision TEXT
);
```

### 3.4 【门禁 2】Config 审核

#### 3.4.1 用户交互流程

```
Claims 入库完成后
    │
    ▼
自动运行 sync_claims_to_config.py --preview
    │
    ▼
微信推送 config 建议摘要：
━━━━━━━━━━━━━━━━━━━━
📋 基于新 claims 的配置建议（2条）：

【建议 1】watchlist 更新
• 杰瑞股份(002353): 新增 linked_claims claim-20260611-001
• 当前: 2条关联claims → 建议: 3条

【建议 2】entry_points 新增
• 万泽股份(000534)
• 介入区间: 30.5-31.0
• 仓位: 0.5成 | 止损: 跌破30
• 赔率: 3:1
• 依据: claim-20260611-002
⚠️ 注意: 万泽已有 active entry（add_zone 30.5-31.0），
   建议更新 claim_basis，不新增重复 entry

回复：
• 「确认」→ 全部执行
• 「确认 1」→ 只执行建议 1
• 「修改 2 仓位 1成」→ 修改后执行
• 「跳过」→ 全部忽略
• 「查看 2」→ 显示建议 2 完整 YAML
━━━━━━━━━━━━━━━━━━━━
```

#### 3.4.2 支持的指令

| 指令 | 含义 | 示例 |
|------|------|------|
| `确认` | 执行全部 pending 建议 | `确认` |
| `确认 1 2` | 执行指定序号 | `确认 1 2` |
| `修改 N 字段 值` | 修改后执行 | `修改 2 仓位 1成` |
| `跳过` | 全部忽略 | `跳过` |
| `查看 N` | 显示完整内容 | `查看 2` |
| `状态` | 查看当前待审核队列 | `状态` |

### 3.5 执行层

用户确认后自动执行：

```bash
# 1. 更新 watchlist.yaml
# 2. 更新 strategy_pack.yaml（entry_points）
# 3. Git commit
# 4. 重启 Qing-Agent
# 5. 微信通知结果
```

---

## 四、数据流时序图

```
B站监控cron          Hermes(微信)         用户              C2编排            审核队列           执行脚本
    │                   │                 │                 │                 │                 │
    │──新动态──────────▶│                 │                 │                 │                 │
    │                   │──微信通知──────▶│                 │                 │                 │
    │                   │                 │                 │                 │                 │
    │                   │◀─「提取claims」─│                 │                 │                 │
    │                   │──触发C2────────▶│                 │                 │                 │
    │                   │                 │                 │──提取claims────▶│                 │
    │                   │                 │                 │                 │──写入pending───▶│
    │                   │◀──────────────────────────────────│                 │                 │
    │                   │──claims摘要────▶│                 │                 │                 │
    │                   │                 │                 │                 │                 │
    │                   │◀────「确认」────│                 │                 │                 │
    │                   │──写入claims────▶│                 │                 │                 │
    │                   │                 │                 │                 │                 │
    │                   │──discover──────▶│                 │                 │                 │
    │                   │──Neo4j─────────▶│                 │                 │                 │
    │                   │──Qdrant────────▶│                 │                 │                 │
    │                   │                 │                 │                 │                 │
    │                   │──桥接preview───▶│                 │                 │                 │
    │                   │                 │                 │                 │──写入pending───▶│
    │                   │◀─────────────────────────────────────────────────────│                 │
    │                   │──config建议────▶│                 │                 │                 │
    │                   │                 │                 │                 │                 │
    │                   │◀────「确认」────│                 │                 │                 │
    │                   │──执行更新──────▶│                 │                 │                 │
    │                   │                 │                 │                 │                 │
    │                   │──Git commit────▶│                 │                 │                 │
    │                   │──重启Agent─────▶│                 │                 │                 │
    │                   │                 │                 │                 │                 │
    │                   │◀───────────────│                 │                 │                 │
    │                   │──完成通知──────▶│                 │                 │                 │
```

---

## 五、文件清单（需新建/改造）

### 5.1 新建文件

| 文件 | 用途 | 行数预估 |
|------|------|---------|
| `tools/pending_review_queue.py` | SQLite 队列管理（claims + config 统一接口） | ~200 |
| `scripts/event_pipeline_trigger.py` | B站新内容 → 触发 claim 提取 → 写入队列 → 微信通知 | ~150 |
| `scripts/apply_pending_updates.py` | 用户确认后执行 config 更新 + Git + Agent 重启 | ~200 |
| `skills/qing-event-pipeline/SKILL.md` | Hermes skill：识别用户指令 → 调用对应脚本 | ~100 |

### 5.2 改造文件

| 文件 | 改造内容 |
|------|---------|
| `scripts/bilibili_notify.py` | 微信消息末尾增加「提取claims/跳过」指令提示 |
| `scripts/sync_claims_to_config.py` | 新增 `--preview` 模式，输出结构化 JSON |
| `scripts/sync_claims_to_config.py` | 新增 `--apply-batch` 模式，从队列读取并执行 |
| `src/.../tools/claims_to_entry.py` | 增加冲突检测（与现有 entry_points 对比） |

### 5.3 数据库

| 文件 | 用途 |
|------|------|
| `~/.hermes/pending_review.db` | SQLite，含 pending_claims + pending_config_updates 两张表 |

---

## 六、实施优先级

| 优先级 | 任务 | 工时 | 依赖 |
|--------|------|------|------|
| 🔴 P0 | `pending_review_queue.py` 队列管理模块 | 3h | 无 |
| 🔴 P0 | `sync_claims_to_config.py --preview` 改造 | 2h | 无 |
| 🔴 P0 | Hermes skill 指令解析（确认/修改/跳过/查看） | 3h | 队列模块 |
| 🟡 P1 | `event_pipeline_trigger.py` B站后链路触发 | 2h | bilibili_notify |
| 🟡 P1 | `apply_pending_updates.py` 执行脚本 | 3h | 队列模块 |
| 🟡 P1 | Claim 审核交互流程（C2 编排 → 队列 → 微信） | 3h | skill |
| 🟢 P2 | 冲突检测增强（entry_points 重复检测） | 2h | claims_to_entry |
| 🟢 P2 | 端到端测试 | 2h | 全部 |
| **总计** | | **~20h** | |

---

## 七、风险与缓解

| 风险 | 缓解 |
|------|------|
| 用户错过审核通知 | 未审核任务每日 09:00 汇总提醒 |
| 队列堆积 | 超过 7 天的 pending 自动标记过期 |
| 并发冲突（用户同时回复两条） | batch_id 隔离，每次只处理一个 batch |
| 修改指令解析错误 | 提供「查看」指令让用户确认后再修改 |
| Git 冲突 | 执行前自动 git pull --rebase |

---

## 八、与现有系统的关系

```
现有系统（不变）:
  B站监控 → 保存 raw → 微信通知
  C2 编排 → 提取 claims → 写入 knowledge/claims/
  discover → Neo4j → Qdrant（手动触发）
  sync_claims_to_config.py → 生成建议（手动运行）

P0 事件驱动管线（新增）:
  B站监控 → 【用户确认】→ C2 编排 → 【用户确认】→ 自动入库
  ↓
  自动生成 config 建议 → 【用户确认】→ 自动更新 config → 自动重启

关键区别: 两次人工审核门禁，中间步骤全自动。
```

---

## 九、自动建议范围（明确边界）

| 字段 | 来源 | 自动建议？ | 原因 |
|------|------|-----------|------|
| `entry_points` | operation claims | ✅ | 明确映射（介入区间/仓位/止损） |
| `watchlist.linked_claims` | 所有 claims | ✅ | 机械关联 |
| `market_framework` | 多条 claims + 盘面 | ❌ | 需综合判断，留给 15:20 收盘复盘 |
| `index_rules` | 市场走势 | ❌ | 非 claim 驱动 |
| `sector_groups` | 盘面 + claims | ❌ | 需实时数据验证 |
| `position_rules` | 方法论文档 | ❌ | 稳定，不常变 |
| `positions.yaml` | 真实交易 | ❌ **硬约束** | 永远手动 |

> 若 UP 新内容涉及市场阶段判断，由 15:20 收盘复盘 cron 的 LLM 分析后输出建议，不走事件驱动管线。

---

*文档版本: v1.0*
*设计: 2026-06-11*
