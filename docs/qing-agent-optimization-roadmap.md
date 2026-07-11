# Qing-Agent 盘中定时任务优化方向

> 对比材料：2026-07-07（周二）早盘、2026-07-08（周三）早盘+午盘+晚间复盘，与 Qing-Agent 盘中定时任务实际运行日志、prompt 模板、调度配置。
> 文档目的：不讨论单日行情判断，只从"分析逻辑是否自洽、节点设计是否闭环、执行链路是否可靠"三个维度，梳理当前可优化方向。

---

## 一、UP 复盘的逻辑结构（参考基准）

### 1.1 三层框架贯穿全天

UP 的早盘/复盘始终按同一套结构输出：

```
指数定环境 → 板块定方向 → 个股定时点
```

以 2026-07-08 为例：

- **指数定环境**：沪指失守 4000 点、成交 2.58 万亿缩量超 5000 亿、近 4800 只下跌 → 判定为"缩量冰点，抛压衰竭"。
- **板块定方向**：科技是唯一核心主线；半导体由 diverging 修复为 resuming；国产算力从明牌转向非明牌业绩验证。
- **个股定时点**：华天科技承接质量作为风向标、先导基电/瑞芯微/航天电器等新增映射。

### 1.2 关键分析方法

| 方法 | 说明 | 案例 |
|------|------|------|
| **情景推演 A/B/C** | 每种情景给出触发条件与对应动作 | 07-08 早盘给出"科技低开快速回稳 → 中阳共振" vs "利空继续发酵 → 缩量磨底" |
| **隔夜外盘映射** | 美股、日韩、地缘、产业催化共同决定开盘定价 | 07-08 提到 KOSPI 熔断、三星业绩、SK 海力士挂牌、伊朗油轮 |
| **产业链扩散** | 从龙头涨停向上游/替代找还没涨的环节 | 从交换机 → 晶圆厂/封测/设备/芯片设计 |
| **次日观察清单** | 明确给出下一交易日需要验证的变量 | 07-08 晚间列出"量能、WAIC 催化、中报预告"三维度 |
| **观点演进回顾** | 收盘复盘会回顾早盘假设是否被验证 | 07-08 晚间指出"缩量磨底中一次未能完成的情绪修复" |

### 1.3 信息源层次

UP 的输出混合了：

1. **实时盘面数据**（指数、量能、涨跌停家数）
2. **隔夜/盘前外部信息**（美股、日韩、期货、地缘、产业新闻）
3. **博主历史方法论**（冰点期、分歧/修复、产业链扩散等概念）
4. **次日验证框架**（把假设写成可证伪的条件）

---

## 二、Qing-Agent 定时任务分析逻辑（当前实现）

### 2.1 调度节点

当前 `strategy_pack.yaml` 配置的 `agent_analysis_schedule` 共 8 个节点：

| 时间 | ID | 名称 | 设计目标 |
|------|-----|------|---------|
| 09:26 | open_auction | 集合竞价后 | 剧本验证、核心假设、方向优先级初判 |
| 09:45 | open_confirm | 开盘15分钟确认 | 早盘定性、主线确认、机会模式初筛 |
| 10:00 | morning_confirm | 10点确认 | 早盘定性、09:45假设回顾、机会模式清单 |
| 10:30 | opportunity_scan | 30分钟确认 | 机会扫描、3-5只标的 |
| 11:20 | noon_review | 上午收盘前 | 上午定性 |
| 13:10 | afternoon_risk | 午后风险窗口 | 冲高回落监控 |
| 14:00 | mid_afternoon | 午盘监控 | 午后一小时验证 |
| 14:52 | tail_condition | 尾盘条件单 | 判断是否符合介入条件 |

> 注意：prompt 模板中设计了 `cron_closing.txt`（17:00 收盘复盘），但**调度配置里并没有 17:00 这个节点**，因此该 prompt 实际上从未被触发。

### 2.2 当前运行链路

1. `monitor/scheduler` 按时间生成 `AgentAnalysisTrigger`
2. 通过 `/analyze/trigger` 调用 LangGraph：`parse_query → retrieve_knowledge → market_summary → stock_scanner + stock_analyst → devils_advocate → synthesize → style_writer → citation_validator → reviewer → END`
3. 每个节点把 `daily_state` 写入 `config/stock_monitor/daily_state.json`
4. 收盘后由 `scripts/sync_config_from_review.py` 把 `daily_state` 同步到 `direction_pool.yaml` / `stock_pool.yaml`

### 2.3 当前暴露的问题（来自 07-07/07-08 日志）

| 问题 | 07-07 日志表现 | 07-08 日志表现 |
|------|---------------|---------------|
| **尾盘/收盘复盘缺失** | 最后一条为 16:17 买入信号，无 17:00 | 最后一条为 14:50 买入信号，无 17:00 |
| **09:45 节点偶发跳过** | 正常触发 | 09:27 后直接 10:01，09:45 未触发 |
| **14:32/14:52 退化** | 14:32、14:50 变成 generic "定时触发分析" | 14:32、14:50 变成 generic "定时触发分析" |
| **prompt 超长截断** | market_summary 71KB→55KB；stock_scanner 65KB→48KB | market_summary 94KB→58KB；stock_scanner 77KB→60KB |
| **citation 机制失效** | coverage=0.0%，claims_cited=0 | coverage=0.0%~3.4%，claims_cited=0 |
| **reviewer 反复失败** | 缺少数据来源/时间戳/参考来源 | 缺少赔率分析 |
| **devils_advocate 失败** | KIMI_API_KEY 缺失导致跳过 | 已改为 deepseek 成功 |
| **网络搜索超时** | 相对正常 | AI 昇腾/光刻/PCB 等搜索多次超时 |
| **买入信号过于频繁** | 全天 5 次触发 | 全天多次触发，机会状态管理混乱 |
| **daily_state 字段漂移** | position_stance 变成操作建议文本 | 方向优先级与 UP 复盘不一致 |

---

## 三、对比后的核心差距

### 3.1 分析结构：UP 是"连续叙事"，Agent 是"孤立节点"

- UP 从早到晚有一条明确的主线："缩量冰点 → 国产链共振修复 → 未能完成 → 明日继续观察"。
- Agent 每个节点输出独立 JSON，节点之间没有显式的"上一节点假设 → 本节点验证 → 修正假设"链条。
- 结果是：10:00 节点还在做"早盘定性"，但 09:45 已经做过一次；10:30 机会扫描和 10:00 机会模式清单重复。

### 3.2 信息源：UP 重"隔夜+产业链"，Agent 重"实时行情+知识库"

- UP 早盘大量引用隔夜外盘、产业催化、地缘等信息，这些是 Agent 的弱项。
- Agent 的 retrieve_knowledge 主要检索 claims/wiki，但 07-08 日志显示网络搜索超时严重，说明外部信息补充链路不可靠。
- Agent 的实时行情只到指数层面，缺少板块涨跌家数、涨跌停结构、龙虎榜等 UP 常用的情绪指标。

### 3.3 验证闭环：UP 有"预判-验证-修正"，Agent 没有

- UP 每晚复盘会明确说"今天这个判断对了/错了，为什么"。
- Agent 的 `cron_closing.txt` 设计了"今日预判准确性评估"，但因为没有 17:00 节点，这个闭环不存在。
- `daily_state` 被 market_summary/stock_scanner 随意覆盖，没有版本化，无法做"昨天预判 vs 今天实际"的对比。

### 3.4 输出可用性：UP 给出"次日观察清单"，Agent 的机会状态混乱

- UP 每晚给出 3-4 条次日观察清单，非常具体。
- Agent 的 `active_opportunities` 同时存在"候选"、"未触发"、"失效"，且不同节点写入的格式不统一（有的带 `.SZ` 后缀，有的没有），导致条件单检查困难。

---

## 四、可优化方向（按优先级排序）

### P0：修复"收盘复盘"闭环（结构层）

**问题**：`cron_closing.txt` 设计了完整收盘复盘，但 `agent_analysis_schedule` 没有 17:00 节点，导致全天最重要的"观点演进回顾 + 预判准确性 + 明日假设"缺失。

**建议**：
1. 在 `strategy_pack.yaml` 的 `agent_analysis_schedule` 增加 17:00 收盘复盘节点：
   ```yaml
   - id: closing_review
     time: '17:00'
     name: 收盘复盘
     focus: 全天观点演进回顾、预判准确性评估、方向优先级重新排序、active_opportunities更新、明日核心假设与tomorrow_scenarios输出。
   ```
2. 将 `cron_closing.txt` 与 `tail_condition`（14:52）解耦：14:52 专注尾盘条件单，17:00 专注全天复盘。
3. 收盘复盘必须读取当天所有 `intraday_narrative` 和 `active_opportunities`，生成"预判 vs 实际"对比表。

### P0：拆分股票列表，分片请求（工程层）

**问题**：market_summary/stock_scanner prompt 超过 64KB 被截断，关键上下文可能丢失。直接压缩上下文会损失 P1 核心股和持仓股的细节，不可取。

**建议**：
1. **P1 核心股 + 持仓股单独一次完整请求**：保留 watchlist 中 `priority: P1-核心` 的标的以及 `positions.yaml` 中的持仓股的完整上下文，不截断、不摘要。
2. **其他股票按组拆分多次请求**：把剩余股票按行业/主题拆成多组（如存储组、MLCC组、光通信组、国产算力组），每组触发一次独立的 `/analyze/trigger` 请求。
3. **聚合分片结果**：在 graph 外增加一个轻量级聚合节点，把各分片的分析结果合并成统一的市场摘要和机会列表，再写入 `daily_state`。
4. **控制并发与调度**：分片请求在 09:26~09:45、10:00~10:30 等窗口内串行或限并发执行，避免同时占用过多 LLM 配额，并确保下一节点开始前全部完成。
5. **保留 claims/framework 完整加载**：不再为了省长度而截断 claims 或 framework；分片后单次请求的上下文自然下降，无需额外压缩。

### P0：修复 citation / 参考来源机制（输出层）

**问题**：citation_validator coverage 长期为 0，reviewer 反复因"缺少数据来源/参考来源/赔率"失败，说明 LLM 不知道该引用什么、怎么引用。

**建议**：
1. **给 claims 增加显式引用格式**：在 prompt 中要求"引用观点时必须用 `[claim-xxx]` 格式"，并在输入里把 claim ID 放在每条条目开头（当前是放在 statement 后面，容易被截断丢失）。
2. **简化 citation 规则**：先做到"所有 UP 方法论概念和方法论引语必须标注来源"，行情数据默认来自 snapshot 可不用逐条引用，避免 reviewer 过度敏感。
3. **把 citation_validator 前置到 style_writer 之前**：当前是 style_writer → citation_validator → reviewer，应该在 style_writer 的 prompt 里直接注入 citation 要求，而不是事后校验。
4. **为每个持仓/候选标的强制要求赔率**：在 stock_scanner prompt 中增加 `"对每个具体标的必须给出：upside/downside/ratio"`，避免 reviewer 反复拦截。

### P1：重构早盘节点，减少重复（结构层）

**问题**：09:26、09:45、10:00 三个节点都在做"早盘定性/主线确认/假设"，功能重叠。

**建议**：
1. **09:26 只做剧本验证**：输入昨日复盘的 `tomorrow_scenarios`，输出"今日匹配哪个情景、核心假设"。
2. **09:45 只做假设验证**：对比 09:26 的核心假设与开盘 15 分钟实际，输出"哪些假设成立/被推翻"。
3. **10:00 只做结论固化**：输出"今日基调、方向优先级、机会模式清单"，不再重复定性。
4. 三个节点的 `daily_state` 写入不同的 `intraday_narrative` key，避免互相覆盖。

### P1：9:00 亚洲盘前信息聚合（数据层）

**问题**：UP 早盘大量依赖隔夜外盘、产业新闻，Agent 实时搜索不稳定；且 8:30 节点只能拿到美股收盘和日韩盘前，无法反映日韩开盘后 1 小时的实际走势。

**建议**：
1. 增加一个 **09:00 亚洲盘前信息聚合节点**，聚合三类信息：
   - **美股隔夜**：收盘指数、科技股/半导体板块表现、重要个股或 ETF 异动、CSP/AI 相关新闻。
   - **日韩开盘后 1 小时**：KOSPI、日经 225、三星/SK 海力士/东京电子等核心半导体标的走势，判断亚洲盘对隔夜美股的反馈。
   - **期货与地缘**：A50 期指、原油、黄金、美元/美债、地缘冲突等风险事件。
2. 把聚合结果写入 `daily_state.pre_market_brief`，供 09:26 集合竞价后节点直接读取，避免 09:26 再临时联网搜索。
3. **严格时限**：09:00 节点必须在 09:25 前完成并写入 `daily_state`，否则 09:26 节点无法消费。若超时，降级为仅使用已入库 claims/wiki，并在输出中标注"外部数据不可用"。
4. 对外部搜索设置 fallback：若某个数据源超时，则跳过该数据源，不阻塞整个节点。

### P1：统一机会生命周期管理（状态层）

**问题**：买入信号候选全天多次触发，daily_state 中机会状态混乱（候选/未触发/失效并存，code 格式不统一）。

**建议**：
1. 给 `active_opportunities` 增加统一 schema：
   ```json
   {
     "stock": "通富微电",
     "code": "002156.SZ",
     "pattern": "先进封装补涨回踩",
     "trigger": "回踩10日线企稳",
     "status": "未触发",
     "upside": 11,
     "downside": 5,
     "ratio": "2.2:1",
     "entry_zone": [69.0, 72.5],
     "stop_loss": null,
     "first_seen_at": "2026-07-08T10:30:00+08:00",
     "last_checked_at": "2026-07-08T15:55:00+08:00",
     "source_node": "opportunity_scan"
   }
   ```
2. 在 17:00 收盘复盘统一刷新状态：触发的标记为"已触发"，未触发的保留或移到"明日继续观察"，失效的清理。
3. 避免同一标的在不同节点重复添加，用 code 去重。

### P1：校准 Agent 输出与 UP 复盘的一致性（评估层）

**问题**：没有机制对比 Agent 的预判和 UP 实际复盘观点，无法知道 Agent 是否"学对了"。

**建议**：
1. 每晚/次日早晨增加一个离线评估任务：读取 UP 最新复盘 claims，对比 Agent 前一天 `daily_state` 中的 `direction_priority`、`tomorrow_assumption`、`tomorrow_scenarios`。
2. 输出一致性报告：方向优先级重合度、假设验证准确率、机会触发命中率。
3. 把一致性结果反馈到 prompt few-shot 中：Agent 表现差的方向，下次减少权重或增加反例。

### P2：优化模型路由与降级（工程层）

**问题**：07-07 `devils_advocate` 因 `KIMI_API_KEY` 缺失跳过；citation/reviewer 反复 retry 浪费 token。

**建议**：
1. `devils_advocate` 默认使用与主链路相同的 provider（deepseek），不要硬编码 kimi。
2. reviewer 的 citation 问题不要触发重试，而是把修改建议直接传给 style_writer 作为下一轮约束。
3. 对超时/失败的节点增加降级：market_summary 失败时返回"数据不可用，跳过本次分析"。

### P2：增加板块/情绪数据（数据层）

**问题**：Agent 只看指数，缺少 UP 常用的情绪指标（涨跌停家数、连板高度、一进二晋级率、板块涨跌分布）。

**建议**：
1. 在 `market_snapshot` 中补充：
   - 涨跌家数、涨跌停家数、连板高度、炸板率
   - 重点板块（存储/MLCC/光通信/国产算力）的板块指数涨跌幅、领涨股
   - 科创50/中证2000 相对全A 的强弱
2. 这些数据可以从东方财富/同花顺板块接口获取，不需要等龙虎榜。

---

## 五、建议的近期执行顺序

### 第一阶段（1-2 天）：让闭环先跑通

1. 在 `strategy_pack.yaml` 增加 17:00 收盘复盘节点，并确认 scheduler 会触发。
2. 修复 `cron_closing.txt` 被调用的问题，确保收盘复盘读取当天所有 `daily_state` 记录。
3. 给 `daily_state.json` 增加版本化写入：每个节点只追加/更新自己负责的字段，不覆盖其他节点。

### 第二阶段（3-5 天）：提升输出质量

4. 拆分股票列表分片请求：实现 P1/持仓股单独请求 + 其他股票按主题分组多次请求，单次请求不再超过 64KB。
5. 修复 citation 机制：在 style_writer prompt 中注入引用格式要求，简化 reviewer 规则。
6. 为每个持仓/候选标的强制输出 upside/downside/ratio。

### 第三阶段（1-2 周）：对齐 UP 分析风格

7. 增加 09:00 亚洲盘前信息聚合节点：聚合美股收盘 + 日韩开盘后 1 小时 + 期货/地缘，确保 09:25 前写入 `daily_state.pre_market_brief`。
8. 重构早盘节点：09:26 剧本验证、09:45 假设验证、10:00 结论固化。
9. 增加离线一致性评估任务，对比 Agent 预判与 UP 复盘。

---

## 六、验收标准

| 优化项 | 验收标准 |
|--------|---------|
| 收盘复盘闭环 | 每天 17:00 稳定触发，输出包含"观点演进回顾 + 预判准确性 + 方向优先级 + 机会更新 + 明日假设 + tomorrow_scenarios" |
| 分片请求 | P1/持仓股单次请求完整无截断；其他分组单次 prompt 不超过 64KB；所有分片在下一节点前完成 |
| citation | style_writer 输出中至少 50% 的关键判断带有 `[claim-xxx]` 或明确数据来源 |
| 早盘节点 | 09:26/09:45/10:00 三个节点输出不再重复，且 10:00 能引用 09:26 的假设 |
| 机会管理 | daily_state 中同一标的只保留一条记录，状态随节点更新而非重复追加 |
| 一致性评估 | 每周生成一次 Agent vs UP 复盘一致性报告 |

---

## 附录：关键文件路径

- 复盘参考：`/home/ubuntu/learning-investment-strategies/knowledge/wiki/每日复盘/2026-07-07.md`、`2026-07-08.md`
- 定时任务 prompt：`/home/ubuntu/learning-investment-strategies/src/qing_investment/agent/prompts/system/cron_*.txt`
- 调度配置：`/home/ubuntu/learning-investment-strategies/config/stock_monitor/strategy_pack.yaml`（`agent_analysis_schedule`）
- 调度实现：`/home/ubuntu/learning-investment-strategies/src/qing_investment/monitor/scheduler/__init__.py`
- 状态持久化：`/home/ubuntu/learning-investment-strategies/src/qing_investment/agent/tools/daily_state.py`
- 运行日志：`/home/ubuntu/learning-investment-strategies/logs/qing-agent.2026-07-07.log`、`qing-agent.2026-07-08.log`
