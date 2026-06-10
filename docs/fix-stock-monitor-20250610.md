# Stock Monitor 修复记录 — 2025-06-10

> 基于 cron job 报告问题（job_id: 41c8e6da0e65）的修复

---

## 问题清单

| # | 问题 | 严重度 | 根因 |
|---|------|--------|------|
| 1 | 数据源限流：东财 API 对服务器 IP 严格限流，导致行情获取失败 | 🔴 高 | 单数据源，无降级 |
| 2 | 持仓幻觉：AI 将观察池标的当作持仓分析 | 🟡 中 | prompt 未明确区分 positions vs watchlist |
| 3 | daily_state.json 不存在，节点间无观点连续性 | 🟡 中 | AI 不输出 daily_state 代码块，prompt 要求不够强制 |

---

## 修复 1：数据源降级（已完成 ✅）

### 修改文件
- `src/qing_investment/stock_monitor.py`

### 变更内容

#### 1.1 新增 `fetch_sina_quotes()` 函数
- 新浪财经备用接口：`https://hq.sinajs.cn/list=sh600519,sz000001`
- 支持批量查询（chunk_size=80）
- 解析格式：`var hq_str_sh600519="贵州茅台,1740.00,...";`

#### 1.2 重写 `fetch_quotes_with_fallback()` 降级逻辑

**旧逻辑（问题）：**
```
东财优先 → 腾讯回退
- 东财 0 quotes + errors 时，不会触发降级
- 腾讯即使能返回数据也被跳过
```

**新逻辑（修复）：**
```
腾讯优先 → 新浪备用 → 东财兜底 → 合并兜底
1. 腾讯(gtimg): 最稳定，对服务器IP友好
   - 成功条件：返回 ≥80% 标的 且 无错误
2. 新浪(hq.sinajs.cn): 备用
   - 成功条件：返回数据且 无错误
   - 若腾讯已返回部分数据，合并补充
3. 东财(push2.eastmoney.com): 数据最全但限流严格
   - 最后尝试
4. 兜底：合并所有可用数据源的数据 + 汇总错误信息
5. 完全失败：返回 all_failed + 详细错误
```

#### 1.3 新增 `_merge_quotes()` 辅助函数
- 合并两个 quote 列表，以 base 为主，extra 补充缺失的 secid

### 测试验证

```bash
# 测试1: 正常场景（腾讯优先）
184 个标的 → 数据源: tencent_gtimg, 返回: 184/184, 耗时: 156ms ✅

# 测试2: 新浪接口
3 个标的 → 数据源: sina_hq, 返回: 3/3 ✅

# 测试3: 东财失败场景（模拟）
184 个标的 + 东财限流 → 腾讯返回 162/184 ✅
```

---

## 修复 2：持仓/观察池区分（已完成 ✅）

### 修改文件
1. `src/qing_investment/stock_monitor.py`
2. `src/qing_investment/agent/prompts/system/cron_*.txt` (9个文件)

### 变更内容

#### 2.1 `format_analysis_context()` — 明确标注持仓状态

**新格式：**
```
=== 持仓池（positions.yaml）===
状态：【空仓】当前无持仓

重要区分：
- 持仓池 = 你当前实际持有的股票（来自 positions.yaml）
- 观察池 = 你关注但尚未买入的股票（来自 watchlist.yaml）
- 严禁将观察池标的当作持仓分析！

持仓明细：
  （无持仓）

=== 观察池（watchlist.yaml）===
这些标的尚未买入，仅作观察：
- ...
```

#### 2.2 `format_live_analysis_context()` — 注入持仓状态提醒

在输出模板前增加：
```
【重要】当前持仓状态：空仓
【重要】观察池标的 ≠ 持仓，严禁混淆！
```

#### 2.3 所有 cron prompt 增加区分说明

在每个 prompt 文件开头插入区分说明段落。

---

## 修复 3：daily_state 集成（已完成 ✅）

### 架构全景

```
┌─────────────────────────────────────────────────────────────────┐
│  Cron Job (9个节点: 09:26/09:45/10:00/10:30/11:20/13:10/14:00/14:55/15:20)  │
│  └─→ qing_stock_monitor_agent.py                                │
│      └─→ stock_monitor.py --agent-json-context                  │
│          ├─→ format_agent_analysis_context()                    │
│          │   ├─→ load_daily_state() → 注入 state_summary        │
│          │   ├─→ load cron_prompt.txt → 注入节点专属指令        │
│          │   └─→ format_hot_score_summary() → 注入热度排行      │
│          └─→ 返回完整 context → AI 分析                          │
├─────────────────────────────────────────────────────────────────┤
│  AI 分析输出                                                     │
│  └─→ 包含 ```daily_state 代码块（prompt 强制要求）              │
├─────────────────────────────────────────────────────────────────┤
│  Cron Job: Daily State 同步扫描 (*/5 9-15 * * 1-5)              │
│  └─→ sync_daily_state.py                                        │
│      ├─→ 扫描 ~/.hermes/cron/output/ 下 9 个 job 的最新输出     │
│      ├─→ extract_daily_state_blocks() → 提取 ```daily_state    │
│      ├─→ merge_daily_state() → 合并到当前状态                   │
│      └─→ save_daily_state() → 写入 daily_state.json            │
├─────────────────────────────────────────────────────────────────┤
│  次日开盘前                                                      │
│  └─→ daily_state 日期过期检查 → 自动重建新日状态                │
│  └─→ archive_daily_state() → 归档昨日状态到 daily_state_archive/│
└─────────────────────────────────────────────────────────────────┘
```

### 组件状态

| 组件 | 文件 | 状态 | 说明 |
|------|------|------|------|
| daily_state 核心 | `src/qing_investment/agent/tools/daily_state.py` | ✅ 已存在 | load/save/update/get_state_summary API 完整 |
| Context 注入 | `stock_monitor.py::format_agent_analysis_context()` | ✅ 已集成 | 第1053-1056行，注入 state_summary |
| Prompt 要求 | `cron_*.txt` (9个) | ✅ 已强化 | 新增【⚠️ 强制要求：daily_state 输出】段落 |
| 同步扫描器 | `scripts/sync_daily_state.py` | ✅ 已存在 | 提取/合并/保存逻辑完整 |
| Cron 任务 | job_id: `0a62d01fbd45` | ✅ 已配置 | `*/5 9-15 * * 1-5`，每5分钟扫描 |

### 修复内容

#### Step 1: Context 注入（已存在，无需修改）

`format_agent_analysis_context()` 已包含：
```python
from qing_investment.agent.tools.daily_state import load_daily_state, get_state_summary
daily_state = load_daily_state()
state_summary = get_state_summary(daily_state)
# ... 注入到 context 的 "=== daily_state 当前状态 ===" 段落
```

#### Step 2: 强化 Prompt 输出要求（本次修复）

**问题**：旧 prompt 的 daily_state 要求在文件末尾，AI 经常忽略。

**修复**：
1. 将 daily_state 输出要求移到【输出要求】段落之后，更显眼
2. 增加 "⚠️ 强制要求" 标题和 "不可省略！" 强调
3. 提供完整的 JSON 示例，降低 AI 输出难度
4. 添加字段说明，确保 AI 理解每个字段含义

**涉及文件**：
- `cron_opening.txt` — 09:26
- `cron_open_confirm.txt` — 09:45
- `cron_morning_confirm.txt` — 10:00
- `cron_opportunity_scan.txt` — 10:30
- `cron_noon_review.txt` — 11:20
- `cron_afternoon_risk.txt` — 13:10
- `cron_midday.txt` — 14:00
- `cron_tail_condition.txt` — 14:55
- `cron_closing.txt` — 15:20

**新格式示例**（cron_opening.txt）：
```
【⚠️ 强制要求：daily_state 输出】
分析完成后，必须在回复末尾输出以下代码块（不可省略！系统会自动解析此代码块记录观点连续性）：

```daily_state
{"market_stage":{"phase":"等修复","detail":"竞价低开，机器人抗跌"},"direction_priority":[{"direction":"机器人","intensity":"🔥🔥"},{"direction":"燃气轮机","intensity":"🔥"}],"position_stance":"空仓等待","intraday_narrative":[{"time":"09:26","summary":"竞价低开，机器人方向相对抗跌，判断今日等修复"}]}
```

说明：
- `phase`: 周期判断（如"等修复"/"强修复"/"弱修复"/"分歧"/"防御"）
- `direction_priority`: 方向优先级数组，最多3个
- `position_stance`: 持仓态度（空仓等待/轻仓试探/重仓持有）
- `intraday_narrative`: 观点演进记录，time=节点时间，summary=一句话总结
```

#### Step 3: 同步扫描器（已存在，无需修改）

`sync_daily_state.py` 功能：
- 扫描 9 个看盘 cron job 的输出目录
- 提取 ```daily_state 代码块中的 JSON
- 合并到 `daily_state.json`（按 code 去重、追加 narrative）
- 追踪文件修改时间，避免重复处理

**Cron 配置**：
- job_id: `0a62d01fbd45`
- schedule: `*/5 9-15 * * 1-5`
- script: `sync_daily_state.py`
- deliver: `local`（静默运行，不发送消息）

### 验证测试

```bash
# 测试1: daily_state 加载和摘要生成
>>> from qing_investment.agent.tools.daily_state import load_daily_state, get_state_summary
>>> state = load_daily_state()
>>> print(get_state_summary(state))
今日尚未建立市场判断。

# 测试2: sync_daily_state 提取逻辑
>>> from scripts.sync_daily_state import extract_daily_state_blocks
>>> blocks = extract_daily_state_blocks(test_output_with_daily_state_block)
>>> print(f"提取到 {len(blocks)} 个代码块")
提取到 1 个代码块

# 测试3: sync_daily_state 干运行
>>> cd ~/learning-investment-strategies && python3 scripts/sync_daily_state.py --dry-run
# 当前无 daily_state 代码块（因旧 prompt 未强制要求），扫描后无更新
```

### 预期行为（修复后）

1. **09:26 开盘**：AI 分析后输出 daily_state 代码块 → sync 扫描提取 → 写入 daily_state.json
2. **09:45 确认**：AI 分析时 context 已包含 09:26 的 daily_state → 输出更新后的 daily_state → sync 合并
3. **...全天节点**：每个节点都能看到之前节点的观点，实现连续性
4. **次日开盘**：daily_state 日期过期 → 自动初始化新日状态 → 旧状态归档

---

## 提交记录

### Commit 1: 数据源降级 + 持仓观察池区分
```
commit 3bcc561
fix(stock-monitor): 多数据源降级 + 持仓观察池区分

11 files changed, 465 insertions(+), 13 deletions(-)
```

### Commit 2: daily_state prompt 强化（待提交）
```
fix(stock-monitor): 强化 daily_state 输出要求，实现节点间观点连续性

- 9个 cron prompt 增加【⚠️ 强制要求：daily_state 输出】段落
- 提供完整 JSON 示例和字段说明
- 将 daily_state 要求从文件末尾移到输出要求段落之后
- 增加"不可省略！"强调，提高 AI 遵从率

Fixes: daily_state.json 为空，节点间无观点连续性
```

---

## 验证清单

- [x] 修复1：腾讯接口返回 184/184 标的
- [x] 修复1：新浪接口返回 3/3 标的
- [x] 修复1：东财限流时降级到腾讯
- [x] 修复2：context 显示 "【空仓】当前无持仓"
- [x] 修复2：9个 cron prompt 包含区分说明
- [x] 修复2：live context 包含 "观察池标的 ≠ 持仓" 提醒
- [x] 修复3：stock_monitor.py 已注入 daily_state 到 context
- [x] 修复3：9个 cron prompt 已强化 daily_state 强制输出
- [x] 修复3：sync_daily_state.py 已配置为 cron 任务（*/5 9-15 * * 1-5）
- [ ] 修复3：待验证 — 下一交易日观察 AI 是否输出 daily_state 代码块
- [ ] 修复3：待验证 — daily_state.json 是否正确创建和更新
- [ ] 修复3：待验证 — 跨节点观点连续性是否正常工作
