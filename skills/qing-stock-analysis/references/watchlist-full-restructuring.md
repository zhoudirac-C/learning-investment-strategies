# UP 观点驱动的全量观察池重构

> 区别于增量新增（保留旧 theme，追加新 theme），全量重构用于 UP 方向发生重大变化时的观察池重置。

## 触发条件

- 用户要求"根据 UP 最新复盘重新整理观察池"
- UP 明确切换主线方向（旧方向退潮，新方向崛起）
- 持仓清零后重新规划观察方向

## 执行流程

### Step 1：归档旧配置

```bash
cd ~/learning-investment-strategies/config/stock_monitor
cp watchlist.yaml "watchlist_YYYYMMDD_archive.yaml"
cp strategy_pack.yaml "strategy_pack_YYYYMMDD_archive.yaml"
```

### Step 2：多源读取 UP 最新观点

**必须同时读取两类来源**（互相补充）：

| 来源 | 方法 | 覆盖内容 |
|------|------|---------|
| Neo4j claims | `mcp_neo4j_get_recent_claims(days=2)` | 结构化观点（claim_type/confidence/intensity） |
| Raw 文档 | 读取 `sources/raw/财经/` 最近 2 天的复盘/早盘/动态 | 原文语言强度、具体标的提及、操作纪律 |

**⚠️ 只用 claims 不够**：claims 是经过提取的结构化摘要，可能：
- 缺失具体股票代码（充电专属内容不公开代码）
- 语言强度被压缩（"类比上一轮牛市锂电池" → "积极观察"）
- 操作纪律细节缺失（"能做T做T，反弹减仓，等黄金坑补" → "持有观察"）

### Step 3：语言强度排序

按 UP 原话的语言强度对方向排序：

| 强度 | UP 典型表述 | 优先级 |
|------|------------|--------|
| 🔥🔥🔥 | "类比锂电池""可以格局""确定性很高""#1主线""板块阵型最好" | P1-核心 |
| 🔥🔥 | "最确定方向""重心放""#2主线" | P2-重点 |
| 🔥 | "逢低关注""值得观察""有消息刺激" | P3-观察 |
| ⚠️ | "做T→反弹减仓→等补""短期告一段落""差不多了" | 退潮/规避 |

### Step 4：生成新 watchlist

输出结构：
- `updated_at` + `monitor_only_note`（市场定性摘要）
- 每个方向一个 theme，含 `id/name/source_docs/market_checks/stocks`
- 每只标的含 `code/name/role/segment/priority/watch_reason/buy_setup/invalidation_setup`
- 优先级分配：P1 不超过 3 只，P2 不超过 5 只，其余 P3
- 操作基调写入 `monitor_only_note`（如"做T为主，等右侧确认"）

### Step 5：同步更新 strategy_pack.yaml

- `market_framework.current_stage`：匹配 UP 最新市场定性
- `market_framework.core_question`：匹配 UP 的核心验证点
- `market_framework.up_quote`：直接引用 UP 原话
- `market_framework.invalidation_conditions`：基于 UP 的证伪条件
- `sector_groups`：基于新 theme 重新分组

### Step 6：检查其他配置

```bash
ls config/stock_monitor/
```

需检查的文件：
- `positions.yaml`：持仓是否与新方向一致，已清仓标的是否移除
- `strategy_pack.yaml`：`sector_groups` 成员是否与 `positions.yaml` 同步
- `daily_state.json`：是否需要重置（新旧 direction 切换时）
- `watchlist_hot_scores.json`：重新计算热度（可选）

## 常见陷阱

1. **只读 claims 不读 raw**：claims 的 statement 可能缺失操作纪律细节
2. **忽略 UP 的操作基调**：UP 说"冷眼旁观"时，watchlist 应该是 monitor_only，不应设激进买入触发
3. **用户只交易主板**：标的 code 必须是 sh6xxxxx / sz0xxxxx，排除 688/300
4. **保留已退潮方向**：UP 明确说退潮的方向（如燃气轮机），不应仍在进攻组
5. **不区分强弱修复**：UP 的"若能XX则XX"是条件化判断，watchlist 的 buy_setup 应反映条件
