# Prompt 工程模式库（2026-06-12）

> 本文件记录 Qing-Agent 提示词工程中经过验证的模式，避免每次重头调试。

---

## 模式1：三步共振法 — 多指标整合结论

### 问题

LLM 拿到 MACD、九转、斐波那契三个数据源后，只会罗列信号（"60分钟底背离、日线低9已兑现、21天窗口到位"），不会整合成结论。

### 根因

Prompt 只教了"每个指标怎么看"，没教"把指标合在一起得出什么结论"。

### 修复

在 `market_analysis_framework.txt` Step 2 末尾新增「三步共振法」：

```
**第1步：找共振**
- MACD 多级别方向是否一致？
- 九转是否与MACD方向匹配？
- 斐波那契窗口是否与结构同步到位？
- 全A趋势与顶底结构是否矛盾？

**第2步：下结论**
- 用一句话说出组合含义
- ✅ "60分底背离+日线绿柱缩短+低9+21天→四维共振，底部确认中"
- ❌ "60分底背离，日线绿柱缩短，低9，21天窗口"（这是罗列信号）

**第3步：定操作**
- 底部共振→可试错；顶部共振→减仓；分歧→多看少动
```

### 关键要点

- 三条规则必须成组出现，缺一不可
- 必须给出 FAIL 示例（罗列信号）和 PASS 示例（整合结论）
- 第2步的结论要写在 `market_summary` 字段中（非单独段落）

---

## 模式2：数据使用边界声明

### 问题

LLM 把大盘用的 MACD/九转/斐波那契指标应用到个股分析上（如"雅克科技30分钟MACD红柱缩短"）。

### 修复

在每个可能产生混淆的规则前加边界声明：

```
⚠️ **MACD/九转/斐波那契数据只用于大盘（全A指数/上证指数）顶底判断，严禁用于个股分析**
```

在个股分析 prompt（`stock_analyst.txt`）中同样声明：

```
⚠️ 严禁在个股分析中使用MACD/九转/斐波那契
个股技术分析使用：成交量、换手率、支撑位、压力位、K线形态、分时图
```

### 关键要点

- 边界声明必须放在**规则前**（先声明再用规则），而非末尾
- 个股和市场的 prompt 都要声明，LLM 不会跨文件推理
- 每条规则头部加 `——仅用于大盘` 标签

---

## 模式3：动作绑定价格

### 问题

"减仓观察"没有写价格，用户不知道是现价减还是等某个价格减。

### 修复

在 `market_analysis_framework.txt` 的持仓操作计划中增加：

```
11. 持仓操作计划：必须包含 建议动作 + **执行价格** + 触发条件 + 失效条件
   ⚠️ "减仓"→必须写"现价减仓"或"反弹到135减仓"
   ⚠️ 默认按发消息时的最新价执行，如需等特定价格需写明
```

### 关键要点

- 价格要用 `**加粗**` 标记（Markdown格式）
- 默认语义：不写明价格 = 按发送消息时的最新价执行
- 在 `stock_analyst.txt` 的个股技术分析中也同样要求

---

## 模式4：Markdown 输出格式

### 问题

默认输出是 `【盘面】` 自定义标题格式，不是 Markdown。微信支持 `##` 和 `**加粗**`。

### 修复

修改 `style_writer.txt` 的输出指令：

```
请把以下草稿改写成UP风格，输出Markdown格式的纯文本（不要JSON）：

**格式要求：**
- 使用 ## 和 ### 代替【】标题（如 ## 盘面）
- 价格、百分比、操作动作用 **加粗** 标记
- 支撑/压力位等关键数字用 **加粗**
- 不要表格，保持紧凑适合微信阅读
```

### 关键要点

- style_writer 接收 synthesize 的 `【】` 格式草稿，输出 `##` 格式
- reviewer 必须兼容两种格式（见模式5），否则会导致无限打回循环

---

## 模式5：Reviewer 格式兼容

### 问题

reviewer 只认 `【参考来源】` 格式，style_writer 输出 `## 参考来源` 后，reviewer 认为"段落被删了"反复打回，形成死循环（6-7轮，每条请求12-15次LLM调用）。

### 修复

在 `reviewer.txt` 中修改第7条检查规则：

```
7. [ ] 【参考来源】/`## 参考来源`段落是否被删除？两种格式都算有效
```

### 关键要点

- 这是修复 reviewer 打回循环的最简单改动（一行）
- 日志特征：`review_round` 在 0→1→2 之间循环，且 `draft_len` 不变
- 完整的 reviewer 检查清单（10条）见 `prompts/system/reviewer.txt`

---

## 模式6：关键节点日志

### 问题

出问题时只能靠猜——不知道哪里慢、reviewer为什么打回、循环了几次。

### 修复

在 pipeline 的5个关键节点加日志：

| 节点 | 日志内容 | 位置 |
|------|---------|------|
| `analyze_trigger` | 总耗时 + review_passed + output_len + claims数 | `main.py` trigger端点 |
| `market_analyst` | 输入数据量(quotes/claims/positions) + LLM调用耗时 | `nodes.py` market_analyst |
| `reviewer` | pass/fail + retry轮次 + issues数 + 耗时 + 具体打回原因 | `nodes.py` reviewer |
| `review_router` | retry计数 + 路由决策（→end / →style_writer） | `edges.py` review_router |
| `style_writer` | draft_len + market_phase + review_round | `nodes.py` style_writer（已有） |

### 关键要点

- `_retry_count` 在 `AgentState` 中定义（`state.py`），review_router 读取它
- reviewer 日志中输出前3个 issues 的具体内容（`logger.info(f"reviewer_issues: ...")`）
- market_analyst 的 LLM 耗时是排查慢请求的第一线索

---

## 模式7：价格区间偏离度保护

### 问题

机会候选标的现价 58 远超 `entry_zone` 上限 53（偏离度 > 5%），系统仍因 `zone[0] <= latest <= zone[1]` 返回 true，导致误报。

### 修复

在 `stock_monitor.py` 的 `evaluate_buy_signal_candidates()` 中增加：

```python
price_in_zone = zone[0] <= latest <= zone[1]
# 价格偏离度保护：现价 > 区间上限×1.05 时强制判定为"偏离，不触发"
price_deviated = latest > zone[1] * 1.05
if price_deviated:
    price_in_zone = False
```

### 关键要点

- 偏离度阈值 5%（1.05）是基于连板票常见偏离范围的经验值
- 配合 watchlist.yaml 的 `paused` lifecycle 状态使用：价格严重偏离时直接暂停候选
- 偏离度触发时留日志：`buy_signal_deviation: 标的名 new=58.3 > zone_upper=53.0×1.05=55.7`
