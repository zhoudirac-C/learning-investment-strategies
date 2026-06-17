---
name: qing-fupan-morning-usage
description: "Use when the user asks how to use UP's daily 复盘 (evening review) or 早盘 (morning report), how to update direction_pool/stock_pool from claims, or how the three-layer funnel works. PREREQUISITE: claims must already be ingested via qing-learning-claim pipeline."
---

# qing-fupan-morning-usage

## 定位

**这个 skill 是 claims 的下游消费者。** 它的输入不是原始复盘文件，而是已经入库的 claims（Neo4j 895条 + Qdrant 645条观点 + 10880篇知识文档）。

```
你的工作流:
  qing-learning-claim            qing-fupan-morning-usage（你在这里）
  ──────────────                 ──────────────────────────
  sources/raw/财经/*.md           claims 已在 Neo4j/Qdrant
      ↓                               ↓
  extract_claims_pipeline         mcp_qdrant_search_claims()
      ↓                               ↓
  knowledge/claims/*.yaml         mcp_qdrant_search_knowledge()
      ↓                               ↓
  discover → Neo4j → Qdrant       → 更新 direction_pool
      ↓                               ↓
  ✅ claims入库                   → 更新 stock_pool
                                      ↓
                                  → 设条件单，等三重过滤
```

> 如果 claims 还没提取，先跑 `qing-learning-claim`，不要在这个 skill 里从零开始。

## 核心矛盾

```
UP复盘点名标的 → 用户直接加watchlist → 次日已涨停 → 上不了车 → 困惑
```

**根因**：UP点名的个股往往是**信号确认**而非起涨点，窗口极短（0-1天）。

## UP输出的价值分层

| 价值 | 内容类型 | 操作 |
|------|---------|------|
| ⭐⭐⭐⭐⭐ | 大盘方向判断、操作纪律、仓位信号 | **立即执行** |
| ⭐⭐⭐⭐ | 板块方向预判、扩散路径推演、情绪周期定性 | **研究后等时机** |
| ⭐⭐ | 具体标的点名、产业新闻、机构研报线索 | **二次加工**（找上下游） |
| ⭐ | 大涨后复盘、翻倍股回顾 | **纯学习**，不行动 |

---

## 流程总览：三层漏斗（claims 驱动版）

```
claims 数据库 (Neo4j/Qdrant)
    │
    ├── 第一层：mcp_qdrant_search_claims → 提取方向与阶段 → direction_pool
    │
    ├── 第二层：mcp_qdrant_search_knowledge → 扩散产业链找低位 → stock_pool
    │
    └── 第三层：设置条件单，等三重条件同时满足 → 入场
```

---

## 第一层：提取方向与阶段 → direction_pool

### 用 claims 数据库定位 UP 最新观点

```python
# 不是读原始文件，而是查已有 claims：
mcp_qdrant_search_claims("复盘 方向预判 板块 current_stage", limit=10)
mcp_qdrant_search_claims("MLCC 风华高科 分歧", limit=5)
mcp_neo4j_search_claims_graph("风华高科")  # 查观点是否被取代/矛盾
```

### direction_pool 结构

```yaml
# config/stock_monitor/direction_pool.yaml
directions:
  - id: unique_identifier
    name: 方向全称
    current_stage: early_direction  # 仅用5个标准值
    industry_chain:
      upstream:
        - segment: 上游环节名
          stocks:
            - code: 000000.SZ
              name: 股票名
          pumped: false
      midstream: ...
      downstream: ...
    diffusion_path:
      - "A→B→C"
    pre_condition:
      market: "全A量能>2.5万亿+非破位状态"
      sector: "板块首次分歧（连续上涨后1-2日调整）"
      timing: "非连续涨停日"
```

### current_stage 阶段定义（5个标准值）

| 阶段 | 含义 | SectorGate 行为 | 操作 |
|------|------|:--:|------|
| `early_direction` | UP刚提方向，尚未发酵 | ✅ 通过 | 只研究，建产业链图谱 |
| `first_pump` | 方向内个股开始涨停 | ❌ 跳过 | 跟踪不追，等分歧 |
| `diverging` | 板块出现分歧/回调 | ✅ 通过 | **关注第一次分歧尾盘** |
| `resuming` | 分歧后修复走强 | ✅ 通过 | 有底仓持有，无底仓等二次分歧 |
| `ending` | 退潮/资金撤离 | ❌ 跳过 | 不再建仓 |

> ⚠️ 只使用这5个值。`divergence_verification`、`catalyst_window` 等非标值会导致 SectorGate 静默拦截。

### 从 claims 提取到 direction_pool 的映射

| 在 claims 中查到什么 | 更新 direction_pool 什么字段 |
|---------------------|---------------------------|
| market-cycle 类 claim 的 statement | `pre_condition.market` |
| sector-theme 类 claim | 新增 direction 或更新 `current_stage`、`industry_chain` |
| methodology 类 claim 的扩散预测 | `diffusion_path` |
| risk 类 claim | `pre_condition` 补充风险条件 |

### 从早盘 claims 提取

早盘的核心价值是**情绪方向确认**和**今日验证框架**，不是买入信号。

| 早盘 claim 内容 | 怎么用 |
|----------------|-------|
| "三看"框架 | 验证或修正 `current_stage` |
| 情景推演 A/B/C | 对应不同 `pre_condition` 分支 |
| 机构研报/产业新闻 | `mcp_qdrant_search_knowledge("产业链 上游")` 补充研究 |
| "如果XX→则XX" | 条件触发后再评估 |

---

## 第二层：扩散产业链找低位 → stock_pool

### 核心原则：永远向前置一步

```
UP点名A（已涨了）
    ↓
你的工作：找A的产业链上下游 —— 谁还没涨？
```

### 用知识库辅助产业链研究

```python
# 不是手工推，而是查知识库：
mcp_qdrant_search_knowledge("MLCC产业链 上游 陶瓷粉体 镍粉", limit=5)
mcp_qdrant_search_knowledge("铜箔 HVLP4 产业链 下游 CCL PCB", limit=5)
```

### stock_pool 结构

```yaml
# config/stock_monitor/stock_pool.yaml
stocks:
  - code: 000636.SZ
    name: 风华高科
    direction: mlcc_super_cycle
    chain_position: midstream
    human_note:                    # 不进 LLM，仅人类参考
      date: '2026-06-15'
      type: signal_confirmation
      context: "MLCC情绪核心候选"
    entry:
      primary_zone: [57.8, 62.7]
      method: "涨停回踩法"
      hard_stop: 54.0
    pre_condition:                 # LLM 终判用
      sector_diverged: true
      market_actionable: true
      no_consecutive_limit_up: true
```

### 扩散示例

```
claims 中点名的板块/标的       →    扩散到（mcp_qdrant_search_knowledge 辅助）
光芯片（永鼎涨停）             →    光芯片衬底：有研新材、云南锗业
MLCC（风华涨停）              →    上游陶瓷粉体：国瓷材料(300不可交易) / 镍粉：博迁新材
PCB油墨（容大感光彩涨）        →    PCB上游：生益科技、华正新材
玻璃基板（台积电首披露）       →    沃格光电（603773 主板可交易）
3D打印（华曙高科+14.94%）     →    主板无对标，跳过
```

---

## 第三层：条件单——三重过滤

**三个前置条件必须同时满足：**

```
条件1：大盘可操作窗口
    └── 全A非破位 + 量能>2.5万亿 + 非清仓信号期

条件2：板块出现首次分歧
    └── 连续上涨后1-2日回调 + 缩量企稳（不是退潮）

条件3：个股价格到位
    └── 价格在 primary_zone 内 + 缩量 + 非连续涨停中
```

### 等不到怎么办

```
龙头不给回踩 → 放弃 → 切产业链上游（还没涨的）
上游也不给 → 放弃这个方向 → 等 UP 提下一个方向
宁可错过，不可追高
```

---

## 每日操作清单

### 复盘 claim 提取完成后（如 17:00-18:00）

- [ ] `mcp_qdrant_search_claims("今日复盘 盘面定调 情绪阶段", limit=5)` → 更新 `pre_condition.market`
- [ ] `mcp_qdrant_search_claims("板块方向 主线", limit=10)` → 识别 2-3 个主线方向 → 更新 direction_pool
- [ ] `mcp_qdrant_search_claims("扩散 展望 明日", limit=5)` → 找还没涨的产业链环节 → 更新 `diffusion_path`
- [ ] `mcp_qdrant_search_knowledge("XX产业链 上游", limit=5)` → 补充 stock_pool 低位标的
- [ ] 检查已有持仓是否与最新 claims 一致
- [ ] [级联更新](#config-变更纪律) direction_pool/stock_pool 变更后的所有下游

### 早盘前（8:30-9:00）

- [ ] `mcp_qdrant_search_claims("早盘 三看 今日验证", limit=5)` → 验证 direction_pool 的 `current_stage`
- [ ] 对每个方向确认"今天可以买"还是"继续等"
- [ ] 记下今日验证变量（什么确认/什么推翻）
- [ ] 检查昨晚设的 entry_zone 是否因隔夜消息需调整

### 盘中（cron 自动处理）

现有 cron 任务线：
```
09:26 → 集合竞价后（qing_stock_monitor_agent.py）
14:00 → 午盘监控（qing_stock_monitor_agent.py）
14:30 → 尾盘前扫描（qing_stock_monitor_agent.py）
14:50 → 条件单检查（check_entry_conditions.py）
17:00 → 收盘复盘（hermes_stock_monitor_daily_review.py）
```

引擎会自动跑 MarketGate → SectorGate → Stock Conditions → LLM 终判。条件全满足时提醒，不全满足时静默。

---

## Config 变更纪律（6步完整版）

修改 `direction_pool.yaml` 或 `stock_pool.yaml` 后必须同步更新 **6层**：

```
config 变更
    ├── 1. 更新对应的 strategy_pack.yaml（如有依赖条件）
    ├── 2. 验证 format_agent_json_context() 能正确读取新字段
    ├── 3. 更新所有 cron task 的 prompt（含市场阶段描述）
    │      └── ⚠️ 框架条件一旦兑现（如"中阳已出现"），必须从所有下游 prompt 中移除
    │         不能让它继续出现在市场阶段描述中——否则 LLM 会一直当待办事项处理
    ├── 4. 清理已兑现的框架条件（从 market_framework 和所有 prompt 中删除）
    ├── 5. 重启 Qing-Agent（gunicorn reload）
    └── 6. 记录变更到 daily_state.json
```

> 参见 `docs/config-data-contract.md` 完整字段映射。

---

## 关键参考

### 数据源（claims 驱动）
- **Neo4j** — 895条 claims 图谱，`mcp_neo4j_search_claims_graph` / `mcp_neo4j_get_claim_relations`
- **Qdrant qing_claims** — 645条 claims 语义搜索，`mcp_qdrant_search_claims`
- **Qdrant qing_knowledge** — 10880篇知识文档，`mcp_qdrant_search_knowledge`
- **复盘原始文件** — `sources/raw/财经/`（claims 提取时使用，本 skill 不直接读）

### Config 文件
- `config/stock_monitor/direction_pool.yaml` — 方向池（当前21个活跃方向）
- `config/stock_monitor/stock_pool.yaml` — 标的池（50+主板可交易标的）
- `config/stock_monitor/strategy_pack.yaml` — 监控策略包
- `config/stock_monitor/watchlist.yaml` — ⚠️ 旧系统（21 themes/59 stocks），与 direction_pool/stock_pool 并行运行中，逐步迁移

### 方法论文档
- `docs/UP-usage-learning-guide.md` — 完整方法论（含5步发现法、产业链调查）
- `docs/UP-daily-verification-0608-0616.md` — 实证验证数据
- `docs/qing-agent-config-reconstruction.md` — direction_pool + stock_pool 架构设计
- `docs/config-data-contract.md` — 字段消费端映射和 LLM 可见性

### 相关 Skill（不要混用）
- `qing-learning-claim` — claims 提取管线（上游，先跑这个）
- `qing-learning-sync` — discover → Neo4j → Qdrant 同步（上游）

### 相关脚本

| 脚本 | 用途 | 调用方式 |
|:-----|:-----|:-----|
| `scripts/sync_config_from_review.py` | 从 17:00 复盘 daily_state JSON 同步到 config YAML | cron 自动调用 |
| `scripts/sync_claims_to_config.py` | Claims→Config 差异报告，输出建议不自动执行 | 手动运行 |
| `scripts/pre_fetch_klines.py` | K线批量预拉取（用于 entry_zone 计算） | `python3 scripts/pre_fetch_klines.py` |
| `scripts/validate_watchlist.py` | Watchlist 字段校验 | `python3 scripts/validate_watchlist.py` |

### 运维陷阱
- `references/ops-traps.md` — 6 个踩坑记录（Agent-UP 矛盾、entry_zone 生命周期、cron 超时等）
