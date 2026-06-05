---
name: qing-stock-analysis
description: Use when the user asks to analyze an individual stock through the blogger framework, F10 fundamentals, GLM stock data workflow, stock reports, K-line review, or 个股分析.
---

# qing-stock-analysis

## 目标

基于 vendored `glmv-stock-analyst` 的真实数据采集和图表流程，叠加博主投资框架、历史 claims/cases 和 F10 基本面方法论，输出个股分析报告。

## 必读参考

1. `framework/stock-analysis-playbook.md`
2. `skills/qing-stock-analysis/references/data-source-strategy.md`
3. `skills/qing-stock-analysis/references/glmv-stock-analyst-workflow.md`
4. `skills/qing-stock-analysis/references/f10-financial-analysis.md`
5. `skills/qing-stock-analysis/references/qing-stock-framework.md`
6. `skills/qing-stock-analysis/references/report-contract.md`
7. `src/qing_investment/stock_monitor.py` — 监控脚本源码，包含 CLI flag、去重逻辑、板块轮动计算、大模型分析上下文格式。** cron 极简微信提醒的模板定义在源码中（搜索 `format_agent_analysis_context` 和 `请按本项目 AGENTS.md`），无独立参考文件。**
8. `skills/qing-stock-analysis/references/realtime-quote-fetch.md` — **实时行情 curl 兜底**：当 Python 包不可用时，用 curl + 腾讯财经 API 获取 A 股实时行情
9. `skills/qing-stock-analysis/references/tencent-api-field-guide.md` — **腾讯财经 API 字段解析参考**：`qt.gtimg.cn` 返回字段的索引会随买卖盘深度漂移，必须用手动计算（最新-昨收）/昨收 或动态定位时间戳，禁止硬编码索引
10. `skills/qing-stock-analysis/references/watchlist-theme-recovery.md` — **观察池 themes 恢复操作手册**：当用户要求恢复历史上被替换/移除的 themes 时，按此手册执行 Git 历史溯源、字段精简和验证
10. `skills/qing-stock-analysis/references/watchlist-bulk-update-from-raw.md` — **从复盘文档批量更新观察池**：提取 raw 文档中的标的提及，去重后按主题分组追加到 watchlist.yaml 的完整流程
11. `skills/qing-stock-analysis/references/stock-monitor-internals.md` — **监控脚本内部机制与状态文件结构**：收盘监控复盘时排查提醒来源、去重逻辑、漏报原因的参考手册
12. `skills/qing-stock-analysis/references/stock-monitor-cli-behavior.md` — **监控脚本 CLI 行为与状态文件**：`--status`、`--daily-review-context`、`--live-analysis-context` 等命令的输出格式和用途
12. `skills/qing-stock-analysis/references/stock-monitor-source-internals.md` — **监控脚本源码级技术参考**：通过直接阅读 `stock_monitor.py` ~1800行源码提取的完整数据流、函数详解、状态文件结构、CLI参数速查。当需要修改触发逻辑、排查bug、理解去重机制时读本文件；SKILL.md正文中的"监控脚本内部机制"是面向分析的用法参考。
15. `skills/qing-stock-analysis/references/daily-review-cases.md` — **收盘监控复盘案例库**：历史复盘典型案例，含有效性判断标准、开盘诱多识别 checklist、相对强弱伪信号识别方法、盘中配置更新时序陷阱、板块轮动标签语义混淆
16. `skills/qing-stock-analysis/references/index-etf-analysis-guide.md` — **指数/ETF买入分析指南**：当用户询问指数或ETF（如恒生科技、科创50）时使用，含时间窗口分析、ETF代码推荐、与个股分析的区别
17. `skills/qing-stock-analysis/references/qing-agent-lightweight.md` — **Qing-Agent零基础设施运行模式**：LangGraph多智能体系统可在无Docker容器的情况下运行，Neo4j/Qdrant自动降级，mem0有本地JSON fallback。含架构概览、降级机制证据、资源需求对比、CLI入口设计

## 双轨制兼容性

本项目采用 `qing-learning` 双轨制（市场认知层 vs 操作工具层）。`qing-stock-analysis` 在检索本地知识库时：

- **市场认知层 claims**（`claim_type` 为 `market-view`, `sector-theme`, `operation`, `market-cycle`, `risk` 等）：正常参与分析，用于判断市场周期、主线方向、板块轮动
- **技术工具层 claims**（`claim_type: technical-knowledge`, `timeframe: permanent`）：不参与 drift/contradiction 分析，但可作为技术分析方法的引用来源
- **检索时区分**：读取 `knowledge/claims/*.yaml` 时，检查 `claim_type` 和 `timeframe`。`technical-knowledge` + `permanent` 的 claims 只用于技术方法引用，不用于市场观点判断
- **F10 分析不受影响**：基本面分析（护城河、财务、估值）独立于双轨制，按 `f10-financial-analysis.md` 正常执行

## 流程

1. 搜索确认股票代码和上市市场。
2. 按 `data-source-strategy.md` 选择数据源：优先使用当前运行环境原生金融/股票/经济数据库能力；其次使用项目本地监控脚本 `qing_stock_monitor.py`（见 `src/qing_investment/stock_monitor.py`）；若均不可用，再调用 `skills/qing-stock-analysis/scripts/run_glm_fetch.py`（如存在）；若 Python 环境无法安装依赖包，使用 `references/realtime-quote-fetch.md` 中的 curl + 腾讯财经 API 兜底方案；若需要 K-line 历史数据或图表但 matplotlib 不可用，使用 `references/curl-kline-fetch-and-text-chart.md` 中的 curl + 文本图表方案。
3. 统一记录数据来源、查询时间、数据日期、缺失字段和可信度；不能把模型记忆当作行情数据。
4. 读取结构化数据，并查看 K 线和分时图；若原生工具未提供可视化图表，使用本地脚本补图。
5. 搜索精准新闻、公告和研报。
6. 检索本地 `knowledge/claims`、`knowledge/wiki`、`knowledge/cases`。
   - **区分市场认知 claims 与技术工具 claims**：`claim_type: technical-knowledge` 属于永久有效的技术分析知识，与市场周期/板块判断类 claims 分开引用，避免混淆时间敏感观点与永久工具知识。
7. 按博主框架判断市场、板块、个股地位。
8. 按 F10 方法论执行公司类型识别、报表质量、ROE/杜邦、现金流和估值方法选择。
9. 生成 `report.md`、`report.html` 和聊天窗口精简总结。
10. **观察池策略合成**：当用户要求基于博主复盘/动态/早盘/视频合成次日观察池时，参考 `skills/qing-stock-monitor-update/SKILL.md`（板块优先级、介入价位计算、实时行情获取）。

## 子任务：观察池量化策略更新（Observation Pool Quant Update）

当用户要求"将观察池策略写到量化配置里"、"更新观察池"、"修改操作量化策略"、"新增XX方向到观察池"、"使用qing stock monitor update"时，按以下流程执行。

### 执行流程

1. **拉取最新数据**：运行 `stock_monitor.py --live-analysis-context` 获取观察池所有标的实时行情
2. **数据分析**：基于收盘/实时数据，计算每只标的：
   - 涨跌幅、上影线/下影线比例
   - 板块内联动情况（组内是否同步涨跌）
   - 与大盘/防御板块的相对强度
3. **板块强度排序**：按组内平均涨幅、领涨标的表现、联动程度排序
4. **量化介入点计算**：
   - 涨停/大涨标的 → 等分歧回踩，计算回踩区间（今日低点~实体中位）
   - 温和上涨 → 等分时均线附近
   - 弱势/下跌 → 等企稳信号，暂不参与
5. **更新三个配置文件**：
   - `watchlist.yaml`：更新 themes/stocks 结构（新增/移除板块，更新 buy_setup/invalidation_setup）
   - `strategy_pack.yaml`：更新 market_framework、position_rules、sector_groups、sector_rotation_rules、quant_entry_strategy
   - `positions.yaml`：更新仓位建议、target_ratio、sector_allocation
6. **Git 提交**：`git add config/stock_monitor/ && git commit && git push`

### 新增主题/方向到观察池（用户常用简写）

用户可能说"新增AIPC方向""加入端侧AI""使用qing stock monitor update新增XX"，触发本流程：

1. **读取现有 watchlist.yaml**：确认当前 themes 结构和已有标的，避免重复
2. **搜索本地知识库**：在 `knowledge/wiki/市场分析/`、`knowledge/claims/`、`sources/raw/财经/` 中搜索该方向的标的和逻辑
3. **构建主题 YAML 块**：
   - `id`: 小写下划线命名（如 `aipc_edge_ai`）
   - `name`: 中文描述（如 "AIPC/端侧AI（英伟达AI PC+端侧推理扩散）"）
   - `source_docs`: 关联的 wiki 文档和 raw 文档路径
   - `market_checks`: 该方向的关键观察指标
   - `stocks`: 标的列表，每只含 `code`、`name`、`role`、`segment`、`priority`（P1/P2/P3）、`watch_reason`、`confirm_with`、`buy_setup`、`invalidation_setup`
4. **追加到 themes 列表末尾**：新 theme 追加，旧 theme 保留（除非用户明确说移除）
5. **移除旧重复条目**：若某标的已在其他 theme 中存在（如美格智能原在"上游涨价链"下），从旧 theme 中移除，避免同一标的在不同 theme 中重复出现
6. **验证**：运行 `stock_monitor.py --status` 确认主题数和标的数正确增加
7. **Git 提交并推送**

**标的优先级分配原则**：
- P1-核心：产业链最核心、资金最认可、博主明确主推的标的
- P2-重点：细分方向龙头、已进入量产/有订单验证的标的
- P3-观察：弹性标的、跟随型标的、逻辑较远的标的

**主题命名规范**：
- `id` 使用小写下划线格式（如 `aipc_edge_ai`、`cpu_self_research`）
- `name` 包含中文描述和括号内的催化事件（如 "AIPC/端侧AI（英伟达AI PC+端侧推理扩散）"）
- 同一标的在不同 theme 中重复出现时，保留在最新/最相关的 theme 中，从旧 theme 移除

### 介入点计算规则

| 标的当日表现 | 策略 | 介入区间计算 |
|-------------|------|-------------|
| 涨停(≥9.5%) | 等分歧回踩 | 今日低点 ~ (开盘价+收盘价)/2 |
| 大涨(5-9.5%) | 等分歧 | 今日低点 ~ 开盘价 |
| 小涨(0-5%) | 分时均线附近 | 收盘价×0.98 ~ 收盘价 |
| 收跌/大跌 | 暂不参与 | 等企稳信号 |

### 仓位分配原则

- 第一优先级板块：总仓位3-4成，单标的不超过2成
- 第二优先级板块：总仓位2-3成
- 第三优先级板块：总仓位1-2成
- 规避方向：0仓位
- 空仓可上5成，满仓应降仓留空间

### 关键发现必须记录

在 `quant_entry_strategy.key_findings` 中记录：
- 组内是否联动（如万通涨停但得润大跌 = CPU链证伪）
- 大涨标的是否有长上影线（抛压信号）
- 板块与大盘/防御的相对强弱

## 子任务：午盘监控极简微信提醒（14:00 Cron 触发）

当 cron job 在 14:00 触发并要求输出极简微信提醒时，按以下固定模板执行：

### 输入
- 脚本已预运行并注入 `[Hermes股票监控大模型分析上下文]`，包含规则信号、实时行情快照、板块连续信号。
- 可选补充：`python -m qing_investment.stock_monitor --live-analysis-context` 获取最新持仓和行情。

### 输出结构（固定四段，禁止 Markdown 表格/分级标题/长篇数据罗列）

```
【盘面】一句话定性（如"上证+0.8%逼近4130，量能2.8万亿，AI硬件领涨"）。
【持仓池】
- 标的(代码)：动作=持有/做T/减仓观察/风控观察；触发=当前价X.XX/涨跌幅+X.X%/关键位置状态；证伪=具体价位或板块信号导致判断失效
- 标的(代码)：动作=...；触发=...；证伪=...
（每只触发/重点持仓必须单独一行，最多8行，禁止把多只股票写成同一段）
【观察池】
- 可买：最多3个满足/接近买入条件的标的和买点（价格区间+确认信号）。
- 暂不买：一句话说明主因（如"大盘未止跌企稳，全部进攻组跌幅>1.5%"）。
【脚注】数据源=腾讯财经实时接口；时间=YYYY-MM-DD HH:MM；异常=无/某票数据未提供。不要给无条件买卖指令。
```

### 关键约束
- **总字数 ≤ 450 字（中文）**。
- **Focus**：午后一小时盘面验证，只讲当下，不预判尾盘，不做次日预案。
- **持仓池每只股票必须单独一行**，动作从 {持有, 做T, 减仓观察, 风控观察} 中选择。
- **触发字段必须包含完整原文**：当前价格、涨跌幅、关键位置状态（如"距成本线+5%""跌破20日线"），不能只写"触发=..."让LLM自己填。
- **证伪字段必须包含具体价位**：如"跌破42且30分钟不能收回""板块涨幅<1%"，不能只写"证伪=..."。
- 观察池"可买"最多 3 个，写清买点（价格区间 + 确认信号）；无可买则写"暂无可买"。
- 观察池"暂不买"一句话说明主因。
- 脚注必须包含：数据源、时间戳、行情异常；不要给无条件买卖指令。
- **数据验证（防幻觉）**：所有股价、涨跌幅数字必须来自脚本提供的 `[Hermes股票监控大模型分析上下文]`。禁止编造任何数字。若上下文未提供某票数据，写"数据未提供"而非猜测。
- **持仓池只包含有持仓标的**：`positions.yaml` 中 `shares > 0` 的标的才列入持仓池。已清仓（`shares == 0`）的标的不得在持仓池中列出，也不得给出操作建议。
- **板块涨跌数据必须来自脚本提供的 sector_groups 计算结果**：不得凭记忆或推测填写板块涨跌。若脚本未提供板块数据，使用"数据未提供"或跳过。
- **脚本失败时的数据补全**：若 `--live-analysis-context` 因路径拦截/模块缺失无法运行，必须按"脚本执行失败时的降级路径"执行 curl 腾讯 API 获取实时数据，禁止跳过数据验证或编造数字。

### 持仓动作决策树
```
当前价 vs 风险线?
├── 跌破风险线 → 风控观察（必须写收回条件）
├── 接近成本/减亏区 → 减仓观察或做T
├── 强于板块且趋势未破 → 持有
└── 弱于板块但趋势未破 → 持有观察（注明弱于板块）

当前框架阶段?
├── 情绪拐点确认期 + 做T节点 → 止跌企稳低吸，涨起来卖出
├── 退潮/鱼尾/强修复验证期 → 优先保护利润，不追高，不新开仓
└── 主升/混沌轮动 → 按正常做T和持仓纪律
```

### 数据源优先级
1. 脚本预注入的 `[Hermes股票监控大模型分析上下文]`（优先使用，不重复拉取）。
2. `python -m qing_investment.stock_monitor --live-analysis-context`（补充最新持仓和行情）。
3. `config/stock_monitor/positions.yaml`（读取真实持仓、成本、风险线）。
4. `config/stock_monitor/strategy_pack.yaml`（读取当前市场框架、板块规则）。
5. `config/stock_monitor/watchlist.yaml`（读取观察池定义和买入/证伪条件）。
6. **curl 腾讯财经 API 实时行情**（当脚本路径被拦截或模块不可用时，作为降级数据源）：
   ```bash
   # 指数查询
   curl -s 'https://qt.gtimg.cn/q=sh000001,sz399001,sz399006,sh000688' | iconv -f gbk -t utf-8 | awk -F'~' '{print $2, $4, $5, $33, $34}'
   # 个股查询（逗号分隔，最多约50只）
   curl -s 'https://qt.gtimg.cn/q=sz000969,sz000066,sh600487' | iconv -f gbk -t utf-8 | awk -F'~' '{print $2, $4, $5, $33, $34}'
   ```
   - `$4` = 最新价，`$5` = 昨收，`$33` = 涨跌额，`$34` = 涨跌幅
   - 涨跌幅计算验证：`($4-$5)/$5*100` 应与 `$34` 一致（允许四舍五入误差）
   - 若 `awk` 输出为空或乱码，检查 `iconv` 是否成功转换（GBK→UTF-8）

### 脚本执行失败时的降级路径

当 cron 任务报告脚本路径错误（如 `Blocked: script path resolves outside the scripts directory`）或脚本无法运行时，按以下降级路径获取数据：

1. **优先尝试模块方式**：`cd $HERMES_REPO_ROOT && python -m qing_investment.stock_monitor --live-analysis-context`
2. **若模块方式失败**：直接调用 `python -m qing_investment.stock_monitor --live-analysis-context`（假设当前目录为项目根目录或模块在 PYTHONPATH 中）
3. **若 Python 环境不可用**：使用 curl + 腾讯财经 API 兜底（见 `references/realtime-quote-fetch.md`）
4. **数据到手后**：继续按极简微信提醒模板输出，不因为脚本失败而中断分析流程

**关键原则**：脚本执行失败 ≠ 数据不可获取。必须尝试至少一种降级路径获取实时行情，禁止因脚本失败而编造数据或跳过数据验证。

**curl 腾讯财经 API 快速查询命令（用于极简微信提醒数据补全）**：
```bash
# 指数批量查询
curl -s 'https://qt.gtimg.cn/q=sh000001,sz399001,sz399006,sh000688' | iconv -f gbk -t utf-8 | awk -F'~' '{print $2, $4, $5, $33, $34}'
# 个股批量查询（示例）
curl -s 'https://qt.gtimg.cn/q=sz000969,sz000066,sh600487' | iconv -f gbk -t utf-8 | awk -F'~' '{print $2, $4, $5, $33, $34}'
```
- `a[4]` = 最新价，`a[5]` = 昨收，`($4-$5)/$5*100` = 涨跌幅
- 字段索引漂移：不同股票买卖盘深度不同导致 `split('~')` 后字段数不一致，涨跌幅**禁止硬编码索引**，必须用 `(最新-昨收)/昨收` 计算

## 子任务：指数/ETF买入分析（Index/ETF Buy Analysis）

当用户询问指数（恒生科技、科创50、创业板指等）或ETF是否可以买入时，触发本流程。用户可能使用表述如"恒生科技指数ETF适合买入吗""最近可以买入恒生科技吗""帮我看看恒生科技指数"等。

### 与个股分析的区别

| 维度 | 个股分析 | 指数/ETF分析 |
|------|----------|-------------|
| 核心依据 | 公司基本面 + 产业逻辑 | 宏观框架 + 资金流向 + 时间窗口 |
| Claims来源 | `knowledge/claims/` 中的个股相关claims | `knowledge/claims/` 中的宏观/市场周期claims |
| 数据源 | 个股行情 + F10 + 新闻 | 指数走势 + 成分股资金流向 + 宏观数据 |
| 决策框架 | 产业逻辑是否成立 + 技术面是否破位 | 时间窗口是否合适 + 资金结构是否支撑 + 宏观拐点是否确认 |

### 执行流程

1. **确认用户问的是指数/ETF还是个股**：若用户明确说"指数ETF""指数基金"或指数名称（如恒生科技、科创50），使用本流程；若问具体股票代码或公司名称，使用个股分析流程。
2. **收集博主相关Claims**：
   ```bash
   cd ~/learning-investment-strategies
   grep -rn "恒生科技\|港股.*买入\|港股.*配置\|港股.*窗口" \
     sources/raw/财经/ knowledge/claims/ | grep -v "Binary"
   ```
   按时间排序，提取关键判断。
3. **构建时间线**：将claims按时间顺序排列，标注风险窗口、配置窗口、估值修复期。
4. **判断当前位置**：当前日期 vs 时间线 → 确定处于哪个窗口。
5. **ETF vs 个股优劣分析**：ETF分散解禁风险、捕获板块Beta、适合左侧分批；但无法捕获Alpha、包含弱势成分股、有管理费。
6. **输出分析**：按固定结构输出（见下方"输出结构"）。
7. **衔接持仓分析**：若用户后续询问具体持仓，从指数分析自然过渡到个股/持仓分析。

### 输出结构

```
## [指数名] 买入分析（基于博主框架）

### 一、核心结论
[一句话结论：当前是否建议买入，最佳窗口何时，推荐仓位]

### 二、博主关键 Claims（按时间排序）
| 日期 | 来源 | 核心观点 | 置信度 |

### 三、时间线推演
[图形化时间线，标注当前位置]

### 四、操作策略（分情景）
| 情景 | 仓位 | 标的 | 时间 | 条件 |

### 五、ETF选择建议（如适用）
[场内ETF代码、场外基金代码、流动性对比]

### 六、风险与不确定性
[3-5个关键风险]

### 七、关键观察指标
[需要跟踪的指标和数据源]
```

### 核心原则

- **时间窗口优先**：博主对指数的判断高度依赖时间窗口（解禁高峰、美联储议息、财报季）。当前处于风险窗口时，即使估值低也不建议重仓。
- **区分A股和港股生态**：港股80%机构适合左侧，A股适合右侧。ETF在港股生态中更适合左侧分批。
- **不只看估值**：博主明确说"港股从来不是因为便宜而上涨的"，必须看盈利预期和资金结构。
- **ETF是配置工具**：博主认可ETF作为风险偏好下降时的防御工具和过渡期核心配置，但不认可无条件重仓。
- **给出具体ETF代码**：当用户问ETF时，必须给出具体场内ETF代码（如513130、513180）和场外基金代码（如012348），并说明流动性差异。

### 常见陷阱

1. **混淆个股和指数分析**：用户问"恒生科技"可能指指数也可能指成分股，需确认。若问ETF，明确使用指数框架。
2. **忽略时间窗口**：只看估值低就推荐买入，忽略解禁高峰、美联储周期等时间因素。
3. **给出无条件买卖指令**：必须附带条件（"若X则Y"），如"若8-9月解禁结束后可加仓至30%"。
4. **不区分ETF和个股优劣**：ETF分散风险但无法捕获Alpha，需向用户说明。
5. **遗漏ETF代码**：用户问ETF时必须给出具体可交易的代码。

### 数据源

- 指数行情：Yahoo Finance (^HSTECH)、腾讯财经
- 资金流向：南向资金日净流入（东方财富、Wind）
- 解禁数据：港交所披露易、券商研报
- 宏观数据：美联储议息会议、中国PMI、人民币汇率
- 博主Claims：`sources/raw/财经/`、`knowledge/claims/`

## 子任务：持仓更新（Position Update）

当用户要求"更新我的持仓""分析我的持仓""帮我看看持仓"或类似表述时，触发本流程。用户可能使用简写如"使用qing-stock-monitor-update更新"。

### 执行流程

**⚠️ Step 0：多源交叉排序（必须先执行，防止单一 source 误导优先级）**

在给出配置建议前，必须读取**近期所有 UP 内容**（早盘、复盘专栏、视频录音、动态），按语言强度进行方向优先级交叉排序。

**反面案例（2026-06-05）**：只读了 6-5 早盘得出"AI 上游材料最确定"并重仓配置。后来读 6-4 视频发现 UP 对燃气轮机的评价语言强度远超 AI 上游材料（"类比上一轮牛市的锂电池""可以格局""机构都要买"），漏掉了真实的第一优先级方向。

**强制流程**：

1. 扫描 `sources/raw/财经/` 中最近 **2 天**的所有 UP 内容（早盘/复盘/视频/动态）
2. 逐篇提取 UP 对**每个方向的定调语言**，按语言强度排序：
   - 🔥🔥🔥 "类比锂电池""可以格局""确定性很高""机构都要买" → 最高优先级
   - 🔥🔥 "最确定方向""重心放" → 高优先级
   - 🔥 "赔率升高""逢低关注" → 中等优先级
   - ⚠️ "短期告一段落""差不多了" → 规避
3. **交叉比较**：若多个 source 对不同方向的评级不一致，使用语言强度更高的那个作为该方向的真实定级。例如：6-5 早盘说 AI 上游材料"最确定"(🔥🔥)，6-4 视频说燃气轮机"类比锂电池"(🔥🔥🔥) → 燃气轮机 > AI 上游材料。
4. **汇总输出**方向优先级排名表，包含每个方向的 source 引用和语言强度引用。
5. 基于此排名表确定仓位分配比例，再进入后续流程。

1. **拉取行情数据**：运行 `fetch_stock_data.py` 或 `stock_monitor.py --live-analysis-context` 获取持仓标的实时行情
2. **计算盈亏**：基于用户提供的持仓（股数、成本），计算每只标的的浮动盈亏和盈亏比例
3. **Claims 关联分析**：在 `knowledge/claims/` 和 `knowledge/wiki/` 中搜索每只持仓标的的关联 claims，提取：
   - 产业逻辑（claim subject + statement）
   - 置信度（confidence）
   - 角色定位（P1-核心 / P2-重点 / P3-观察 / 弹性标的）
   - 相关主题（超级电容、纳米晶、CPU自研链等）
4. **同板块验证（Sector Peer Verification）**：当某只持仓大跌（尤其跌停）时，必须检查同板块其他标的：
   - 从 claims 的 `related_stocks`、watchlist.yaml 的 `confirm_with`、博主 raw 文档的"核心标的"列表获取同板块标的
   - 查询这些标的的实时行情
   - 判断是板块系统性回调还是个股独立利空
   - 详见 `references/sector-peer-verification.md`
5. **市场环境定位**：读取当日大盘指数（科创50、创业板指、上证指数），判断是系统性回调还是个股问题
6. **逐只分析**：对每只持仓输出结构化分析：
   - 产业逻辑摘要（1-2句）
   - 今日表现（开盘/高/低/收、涨跌幅）
   - 技术面关键位（成本线、今日高低点、近期支撑/压力）
   - 与 claims 的一致性（逻辑是否仍然成立）
   - 同板块验证结果（如适用）
   - 风险等级（🟢低 / 🟡中 / 🔴高）
   - 具体操作建议（持有/观察/止损/加仓，含具体价位条件）
7. **组合层面风险**：评估单票集中度、主题集中度、总盈亏比例
8. **明日操作预案**：分情景（修复/继续调整/高低切换）给出操作矩阵
9. **关键观察指标**：列出明日开盘需要验证的3-5个信号（同板块标的联动、指数方向、claims验证点）
10. **更新 watchlist.yaml**：将分析结果写入 `today_snapshot`，包括持仓数据、市场判断、overall_action

### 输出结构

```
## 持仓更新完成
[盈亏汇总表：标的/持仓/成本/最新/涨跌/盈亏/市值]
[组合合计：总成本/总市值/总盈亏]

### 关键观察
[1-3句核心判断，如"X跌停最危险，需确认是板块回调还是个股利空"]

---

### 持仓逐一分析

#### 1. 标的名（代码）— 账户X，N股，成本X.XXX
**产业逻辑**（claim-YYYYMMDD-NNN，置信度）：...
**今日表现**：...
**关键判断**：
- ✅ 逻辑未变/⚠️ 需确认/❌ 技术面破位
**风险等级**：🔴/🟡/🟢
**操作建议**：持有/观察/止损/加仓（含具体价位）

[重复每只持仓]

---

### 同板块验证（Sector Peer Verification）
[当某只持仓大跌时，列出同板块其他标的今日表现]
| 标的 | 涨跌 | 判断 |
|------|------|------|
| 目标股 | -9.99% | 跌停 |
| 同板块A | -7.41% | 同步大跌 → 板块回调 |
| 同板块B | +5.10% | 逆势涨 → 方向仍有资金 |

**结论**：板块系统性回调 / 个股独立问题

---

### 组合层面风险
[集中度、主题集中、总亏损比例]

---

### 明日操作预案
| 情景 | 条件 | 操作 |
|------|------|------|
| 情景A：科技修复 | ... | ... |
| 情景B：继续调整 | ... | ... |
| 情景C：高低切换 | ... | ... |

---

### 关键观察指标（明日开盘）
1. ...
2. ...
3. ...
```

### 核心原则

- **区分系统性回调与个股问题**：科创50跌>3%时，个股大跌大概率是系统性，不是逻辑证伪
- **Claims 是判断锚点**：持仓是否有博主认可的产业逻辑支撑，是区分"持有等修复"和"止损离场"的核心依据
- **成本线不是止损线**：操作建议基于 claims 逻辑是否成立 + 技术面是否破位，不是简单"跌破成本就割"
- **同板块验证（Sector Peer Verification）**：单只持仓大跌时，必须检查同板块其他标的来确认是板块回调还是个股利空。这是区分"持有等修复"和"止损离场"的关键技术。
  - **操作方法**：在 `fetch_stock_data.py` 输出中查找同板块其他标的（通过 claims 中的 `related_stocks` 或 watchlist.yaml 中的 `confirm_with`）
  - **判断标准**：
    - 同板块多股同步大跌（如东睦股份-7.41% + 安泰科技-9.99%）→ 板块系统性回调，非个股利空 → **持有等修复**
    - 同板块其他股平稳或上涨，仅目标股跌停 → 可能存在未公告个股利空 → **考虑止损**
  - **数据获取**：使用 `python3 -c "import json; ..."` 从 `/tmp/stock_data_*.json` 中提取同板块标的行情
- **不给出无条件买卖指令**：所有操作建议必须附带条件（"若X则Y"）
- **LLM 幻觉识别**：当用户指出 cron 任务报告中的数据错误（如"万通发展没有涨停"），按以下流程处理：
  1. 验证 `state.json` 或实时行情（`curl qt.gtimg.cn`）获取真实数据
  2. 确认是 LLM 幻觉后，向用户说明"这是 LLM 生成的虚假数据，state.json/实时行情显示实际为 X.XX"
  3. 建议更新 cron 任务的 prompt，增加数据约束（见 `qing-stock-monitor-update/references/llm-hallucination-prevention.md`）
  4. 不要试图为幻觉数据找合理解释（如"可能是盘中瞬间涨停"），直接承认是生成错误
- **账户命名灵活性**：用户可能使用任意账户名称（如"大同账号""华宝账号"）。更新 `positions.yaml` 时以用户提供的名称为准，不强制使用固定命名。
- **ETF分析输出结构**：见 SKILL.md 子任务"指数/ETF买入分析"中的"输出结构"章节，必须包含：核心结论、博主关键Claims时间线、时间线推演、操作策略（分情景）、风险与不确定性、关键观察指标。

### 数据源优先级

1. `fetch_stock_data.py` / `stock_monitor.py --live-analysis-context` — 实时行情
2. `knowledge/claims/*.yaml` — 产业逻辑claims
3. `knowledge/wiki/` — 专题wiki（如AI电源与超级电容、CPU自研链）
4. `config/stock_monitor/watchlist.yaml` — 观察池中的标的定义（role、segment、buy_setup、invalidation_setup）
5. `sources/raw/财经/` — 最新博主复盘/早盘/动态（用于判断市场环境）
6. `references/realtime-quote-fetch.md` — 同板块验证方法
7. `skills/qing-stock-analysis/SKILL.md` — 指数/ETF分析框架（当用户询问指数时，见子任务"指数/ETF买入分析"）

### 用户持仓更新触发词

用户可能使用以下简写或变体触发持仓分析流程，需识别并执行：
- "使用qing-stock-monitor-update更新"
- "使用qing stock monitor update"（空格分隔，无连字符）
- "更新我的持仓"
- "分析我的持仓"
- "帮我看看持仓"
- "持仓更新"
- 任何包含"持仓"+"更新/分析/看看/查"的表述

### 新增主题/方向触发词

用户可能使用以下简写或变体触发观察池新增流程，需识别并执行：
- "新增XX方向到观察池"
- "加入XX到观察池"
- "使用qing stock monitor update新增XX"
- "使用qing-stock-monitor-update新增XX"
- 任何包含"新增"+"方向/主题/标的"+"观察池"的表述
- 或包含"qing stock monitor update"的任意变体（连字符/空格均可）

---

## 子任务：收盘监控复盘（Daily Review）

当用户要求按 `AGENTS.md` 与 `qing-stock-analysis` 框架输出**收盘监控复盘**时，遵循以下结构化格式：

- **输出五段结构**：
  1. **核心结论**（3-5条）：先给结论，再展开。区分有效提醒、存疑提醒、误报。
  2. **提醒质量评估**：逐条分析今日提醒，用表格或分点列出标的、时间、动作、价格、收盘、有效性判断（✅有效 / ⚠️存疑 / ❌误报）。
  3. **漏报检查**：指数、板块、持仓、观察池是否有该提醒而未提醒。用表格列出条件、是否该提醒、实际状态、漏报原因。
  4. **去重合理性**：总结被去重压制的信号是否合理，对存疑的去重给出时间窗口调整建议。
  5. **YAML配置调整建议**：明确文件和字段，给出可直接应用的配置片段。必须覆盖以下五类：
     - `positions.yaml`：补充 `reduce_zone` 和 `risk_zone`（含具体价格区间计算逻辑）。**新增**：若同一持仓在4小时内触发3次以上同类型提醒，建议将 `reduce_zone` 拆分为 `t_zone`（做T区间，较宽）和 `reduce_zone`（真正减仓区，较窄），或上调 `reduce_zone` 下限以减少盘中波动误触。
     - `strategy_pack.yaml`：`index_rules` 格式修复（通用格式 vs legacy 格式兼容性）、`sector_rotation_rules` 阈值调整（`min_spread_pct`/`min_red_ratio_spread` 上调建议）、`sector_groups` 清理已清仓标的。**新增**：若发现防御组涨幅<0却被标记为"强于"某方向，建议在 `sector_rotation_rules` 中增加防御组涨幅>0的前置条件，或标记为伪信号。
     - `watchlist.yaml`：观察池更新（如有）。
     - 去重窗口/轮询频率调整建议。
     - 新增规则建议（如"指数中间档位"`close_between`、板块轮动`min_duration_seconds`）。
  6. **下一交易日观察条件**：最重要的3条观察条件，含触发条件和证伪条件。
- **数据源**：优先读取 `config/stock_monitor/state.json` 的 `alert_decision_log`、`alert_history`、`last_quote_snapshot`；其次读取 `positions.yaml`、`strategy_pack.yaml`。
- **关键核查点**：
  - `reduce_zone` 和 `risk_line`/`risk_zone` 的触发价格是否与 `positions.yaml` 一致；若不一致，标记为"配置来源不明"需排查。
  - **已清仓标的残留**：检查 `positions.yaml` 的 `closed_positions` 中已清空的标的是否仍在 `positions` 列表中，或监控脚本是否读取了缓存版本。若已清仓标的仍触发减仓/风控提醒，标记为"配置滞后误报"。
  - **sector_groups 同步检查**：检查 `strategy_pack.yaml` 的 `sector_groups` 成员是否与 `positions.yaml` 的实际持仓一致。若已清仓标的仍留在 `offensive_tech` 等进攻组中，会导致该组平均涨幅被拖累，产生**错误的"进攻回流观察"信号**。
  - 板块轮动提醒（进攻回流/防御切换）的 `min_spread_pct` 阈值是否导致尾盘回流信号被压制；同时检查"进攻回流"是否由子链（如电源/MLCC）驱动而核心方向（PCB/半导体）实际在调整——标签与微观结构可能存在偏差。
  - 去重窗口 `dedupe_minutes` 是否过度压制了价格快速波动时的重复提醒。
  - **盘中配置更新时序陷阱**：检查 `positions.yaml` 是否在交易时段内被修改。若修改时间（`stat`）落在 09:30-15:00 之间，且前后提醒阈值不一致（如安泰科技风控线从"21.5-22"变为"21.00-21.50"），标记为"盘中配置更新导致的时序性误报/存疑"，并建议在 YAML 建议中增加"交易时段内禁止修改风险阈值"的纪律条款。
  - **sector_groups 标签语义混淆**：当 `price_increase_vs_cpo` 等规则比较的两个 group 均为 offensive style 时，系统仍可能输出"防御切换观察"。复盘时必须核对触发规则中两组各自的 `style` 属性，若两组均为 offensive 则标记为"标签语义错误——实为进攻板块内部轮动，非防御切换"。
- **index_rules 通用格式兼容性**：`strategy_pack.yaml` 使用 `trigger_condition: close_below` 等通用格式时，代码可能未完整支持。复盘时若发现指数已跌破阈值但未触发提醒，建议：①运行 `--ignore-trading-time` 测试；②若不触发，增加 legacy 格式（`- trend_defense: 4070`）作为兜底。
- **index_rules 中间档位漏报**：`valid_close_level`（如4080）和 `weak_close_level`（如4070）仅在 interpretation 文本中描述，代码可能未实现中间档位的主动提醒。若指数收盘处于中间档位（如4080-4070）且无提醒，需在复盘中手动指出此为**规则缺失型漏报**，建议增加 `close_between` 规则或中间档位 `trigger_condition`。
- **持仓漏报（高危）**：`positions.yaml` 中若未配置 `reduce_zone` 或 `risk_zone`/`risk_line`，`evaluate_position_alerts()` 将完全跳过该持仓，导致跌停/大跌无任何提醒。复盘时必须逐条检查每个持仓是否配置了价格区间字段。
- **板块轮动阈值过低导致开盘诱多误报**：`min_spread_pct=1.0` 在开盘竞价/高开瞬间极易触发"进攻回流"，但随后市场可能迅速回落。复盘时需交叉核对：①该信号出现后 15-30 分钟内市场是否维持方向；②进攻组内部是否由子链驱动而非核心方向；③指数是否同步站稳。若三者任一不满足，标记为"时间维度不足的伪信号"。
- **尾盘回流信号的时间维度验证**：尾盘（14:30-15:00）的"进攻回流"或"防御切换"信号同样存在时间维度不足的问题。若信号仅在最后15分钟内出现，且收盘后指数/板块方向与信号相反，应标记为"尾盘伪信号"，建议增加 `min_duration_seconds` 或 `min_consecutive_ticks` 过滤。
- **去重与轮询频率**：`state.json` 中若出现同一指纹在 30 秒内重复触发（如 09:17:10 与 09:17:28），说明监控轮询间隔过密（可能为 15-20 秒）。复盘时建议将 cron/调度间隔调整为不低于 60 秒，或在 `filter_new_alerts()` 中增加"价格变化率<0.1% 且间隔<60秒"的二次过滤。
- **盘中配置更新时序陷阱（高危）**：`positions.yaml` 在交易时段内被修改（如调整 `risk_zone`/`reduce_zone`）会导致前后提醒阈值不一致。复盘时若发现同一标的的提醒阈值前后矛盾（如安泰科技风控线从"21.5-22"变为"21.00-21.50"），必须：①检查 `positions.yaml` 文件修改时间（`stat`）；②对比 `state.json` 中该指纹的触发价格与新配置阈值；③若修改发生在交易时段内，标记为"盘中配置更新导致的时序性误报/存疑"，并在 YAML 建议中增加"交易时段内禁止修改风险阈值"的纪律条款。
- **sector_groups 标签语义混淆**：当 `price_increase_vs_cpo` 等规则比较的两个 group 均为 offensive style 时，系统仍可能输出"防御切换观察"。复盘时必须核对：①触发规则中两组各自的 `style` 属性；②若两组均为 offensive，标记为"标签语义错误——实为进攻板块内部轮动，非防御切换"，并建议在 `strategy_pack.yaml` 中重命名规则或修改输出标签。
- **sector_groups 标签语义混淆（防御组弱于大盘的伪信号）**：当防御组（如防御稳定线）本身涨幅<0且弱于大盘，却被系统标记为"强于"某进攻方向时，应标记为"弱于大盘的伪信号——防御组未真正走强"。例如2026-06-03防御稳定线涨幅-0.187%却被输出"防御切换观察"，实为伪信号。
- **持仓减仓区密度过高**：当同一持仓在4小时内触发3次以上同类型提醒（如安泰科技减仓观察×3），需检查 `reduce_zone` 是否过宽。建议将 `reduce_zone` 拆分为 `t_zone`（做T区间，较宽）和 `reduce_zone`（真正减仓区，较窄），或上调 `reduce_zone` 下限以减少盘中波动误触。
- **禁止**：无条件买卖指令、预测次日涨跌、给出具体买卖价格。

## 常见陷阱与防循环指南

1. **引用文件不存在时不要反复读取**：本 skill 历史上列出过多个未落地的 reference 文件（如 `stock-monitor-internals.md`、`cron-alert-format.md` 等）。若 `skill_view` 返回的 `linked_files` 或 SKILL.md 正文引用某文件但实际不存在，**立即停止尝试**，改用源码或替代数据源。极简微信提醒模板直接查 `src/qing_investment/stock_monitor.py`（搜索 `请按本项目 AGENTS.md`）。
2. **区分 SKILL.md 中内嵌的知识与外部 reference**：监控脚本机制、YAML 合约、板块轮动逻辑等知识已完整内嵌在 SKILL.md 正文中，不需要再读外部文件。
3. **positions.yaml 是私有文件（gitignored）**：更新持仓分析时以实际文件内容为准，不依赖记忆中的旧持仓。
4. **Skill 同步**：当需要更新本 skill 时，优先更新项目内版本 `~/learning-investment-strategies/skills/qing-stock-analysis/`，而非 Hermes 全局副本。详见 `qing-learning/references/skill-sync-workflow.md`。
5. **positions.yaml 是私有文件，禁止强制提交**：`positions.yaml` 在 `.gitignore` 中，包含持仓成本、股数等敏感数据。`git add -f` 会绕过 gitignore 将私有数据推送到公开仓库。若已误推送：① `git reset --hard <safe-commit>` 回退到误推送前的 commit；② `git push --force` 从远端清除历史；③ 检查本地文件仍完好（gitignored 文件不受 reset 影响）。**任何时候修改 positions.yaml 都只做本地修改，不提交**。复盘报告中建议的 YAML 配置调整涉及 `positions.yaml` 时，只输出建议文本，由用户手动应用。
6. **Qing-Agent 零基础设施模式**：项目内的 LangGraph 多智能体系统（`src/qing_investment/agent/`）可在无 Docker 容器的情况下运行。Neo4j/Qdrant 连接失败时自动降级为空列表（不阻断流程），mem0 有本地 JSON fallback。只有 LLM API key 是硬依赖。详见 `references/qing-agent-lightweight.md`。
5. **避免工具调用死循环**：当同一 curl/API 调用连续失败或返回相同数据超过 3 次时，**立即停止重试**。常见原因：
   - `run_glm_fetch.py` 因缺失 matplotlib/akshare/yfinance/tushare 而失败 → 改用 curl + 腾讯财经 API 兜底（见 `references/curl-kline-fetch-and-text-chart.md`）
   - 已获取 K-line 数据但反复执行相同 fetch 命令 → 检查是否已满足分析需求，转向分析而非继续拉取
   - 用户要求 分时图 但环境无绘图库 → 生成文本 K-line 摘要（高低点、关键位、量价变化）而非反复尝试画图
6. **脚本依赖缺失时的快速降级路径**：
   - 优先尝试：`python -c "import akshare, matplotlib"` 快速检测
   - 若缺失 → 直接 curl 腾讯 API，不尝试 pip install（可能超时或权限不足）
   - 数据到手后 → 用纯 Python 文本分析，不依赖 pandas/numpy（若可用则用，不可用则手写解析）
7. **腾讯财经 API 字段索引陷阱**：`qt.gtimg.cn` 返回的字段中，涨跌幅不在固定索引位置。不同股票的买卖盘深度不同，导致 `split('~')` 后的字段数不一致。**涨跌幅字段必须动态定位**：先找到时间戳字段（格式 `YYYYMMDDhhmmss`，如 `20260602112927`），其后的第 2 个字段为涨跌额、第 3 个字段为涨跌幅。或者直接用 `a[5]`（昨收）和 `a[4]`（最新）手动计算：`(最新-昨收)/昨收*100`。推荐后者，避免索引漂移。
   - 错误做法：`awk` 硬编码 `a[32]` 或 `a[34]` 作为涨跌幅 → 不同股票返回不同值
   - 正确做法：`curl -s 'https://qt.gtimg.cn/q=sz000969' | iconv -f gbk -t utf-8 | awk -F'~' '{print ($4-$5)/$5*100}'`

## YAML 合约与同步规范

修改 `positions.yaml`、`watchlist.yaml`、`strategy_pack.yaml` 时，必须遵守字段契约并同步相关文件。核心要点：
- `positions.yaml` 与 `positions.example.yaml` 必须结构同步（后者是版本控制模板）
- `sector_groups` 成员必须与实际持仓同步（清仓→移除，新增→加入）
- `watchlist.yaml` 的 theme 结构必须一致，否则 `watchlist_stock_rows()` 静默跳过
- 价格区间字段：`risk_line: 44.5` 解析为单点 `(44.5, 44.5)`，区间必须用 `risk_zone: "44.5-45.5"`
- **`positions.example.yaml` 中必须使用 `risk_zone` 而非 `risk_line`**：虽然代码兼容 `risk_line` 作为 `risk_zone` 的 fallback，但示例文件作为模板应使用推荐字段名，避免用户复制后形成旧习惯
- `sector_rotation_rules` 支持 `require_offensive_positive: true`（可选）：防止"跌得少"被误判为"进攻回流"
- `index_rules` 支持 legacy 格式兜底：`trend_defense: 1750` 作为 `trigger_condition: close_below` 的兼容备选

## 监控脚本内部机制（必读）

监控脚本 `src/qing_investment/stock_monitor.py` 的核心行为：

### 持仓提醒触发逻辑
- `evaluate_position_alerts()` 遍历 `positions.yaml` 中的每个持仓。
- **减仓观察**：当 `latest` 价格落入 `reduce_zone` 区间时触发。`reduce_zone` 通过 `parse_price_zone()` 解析，支持 `"41.15-42.5"` 或单点数值。
- **风控观察**：当 `latest <= risk_zone[1]` 时触发。`risk_zone` 优先取 `risk_zone` 字段，其次取 `risk_line` 字段。单点数值会被解析为 `(price, price)` 区间。
- **关键陷阱**：`positions.yaml` 中若只配置 `risk_line: 44.5`，代码会解析为 `(44.5, 44.5)`，触发条件为 `latest <= 44.5`。若用户期望区间触发（如 `44.5-45.5`），必须使用 `risk_zone: "44.5-45.5"` 格式。

### 去重机制
- `filter_new_alerts()` 使用 `alert_fingerprint()` 生成唯一键，格式为 `"action|stock_code|stock_name|trigger"`。
- **差异化去重（`dedupe_by_type` 已代码实现）**：`strategy_pack.yaml` 的 `notification_policy.dedupe_by_type` 配置生效，支持风控/减仓/板块轮动不同去重窗口 + 价格突破逻辑。详见 `qing-stock-monitor-update/references/dedupe-by-type-implementation.md`。
- **重要**：fingerprint 包含完整的 `trigger` 文本。因此 `"触及或跌破风险线44.5"` 和 `"触及或跌破风险线44.5-45.5"` 被视为不同指纹，不会互相去重。
- **状态持久化**：已发送提醒的时间戳保存在 `state.json` 的 `alert_history` 中，跨进程/跨会话有效。

### 板块轮动提醒
- `evaluate_sector_rotation_alerts()` 计算 `offensive_groups` 和 `defensive_groups` 的均涨幅差和红盘率差。
- 当 `pct_spread >= min_spread_pct` 且 `red_ratio_spread >= min_red_ratio_spread` 时触发"进攻回流观察"。
- 当 `-pct_spread >= min_spread_pct` 且 `-red_ratio_spread >= min_red_ratio_spread` 时触发"防御切换观察"。
- 若两组差值均未达阈值，**不触发任何提醒**——这意味着盘中若双方势均力敌，用户不会收到板块状态信号。

### 指数提醒
- `evaluate_market_alerts()` 检查 `strategy_pack.yaml` 中 `market_framework.index_rules` 的阈值。
- 当前仅支持 `trend_defense`（跌破趋势防线）和 `weak_close_level`（低于弱修复阈值）两种触发。
- **不支持**"站稳修复位"的正面提醒，只触发负面/观察类提醒。
- **已知限制**：`valid_close_level`（如4080）和 `weak_close_level`（如4070）仅在 interpretation 文本中描述，代码可能未实现中间档位的主动提醒。复盘时若发现指数处于中间档位但无提醒，需手动指出此为规则缺失型漏报。建议增加 `close_between` 规则或中间档位 `trigger_condition`。
- **通用格式兼容性风险**：`trigger_condition: "close_below"` 等通用格式在代码中可能未完整实现。实际测试方法：运行 `python -m qing_investment.stock_monitor --ignore-trading-time` 模拟非交易时段触发，观察 `alert_decision_log` 是否生成对应记录。若未生成，说明通用格式未被支持，需改用 legacy 格式（`- trend_defense: 4070`）作为兜底。

### 已清仓标的残留陷阱
- `positions.yaml` 中若将已清仓标的移入 `closed_positions` 但原 `positions` 列表未删除，或监控脚本读取了缓存版本，会导致**已清仓标的继续触发减仓/风控提醒**。
- 复盘时若发现已清空标的（如华正新材、金安国纪、彤程新材）仍有提醒，标记为"配置滞后误报"，优先建议清理 `positions.yaml` 并重启监控进程。
- **sector_groups 同步检查**：`strategy_pack.yaml` 的 `sector_groups` 成员必须与 `positions.yaml` 的实际持仓同步。已清仓标的若仍留在 `offensive_tech`、`avoid_semiconductor` 等组中，会拖累该组平均涨幅，产生**错误的板块轮动信号**。复盘时必须逐组核对：
  - `avoid_semiconductor` 组是否仍包含已清仓的通富微电(002156)等
  - 持仓标的（如安泰科技 000969）是否已加入其所属方向的 sector_group（如 `upstream_price_increase`）
  - 未加入任何 sector_group 的持仓标的不会被纳入板块轮动计算，导致持仓与板块信号脱节

### 大模型分析触发
- `find_agent_analysis_trigger()` 在两种情况下触发：
  1. **事件驱动**：当有新的规则信号（`new_alerts` 非空）且该指纹组合今日未分析过。
  2. **定时驱动**：在 `agent_analysis_schedule` 配置的时间点（如 09:26、09:45、10:30、11:20、13:30、14:00、14:50、15:05）触发。
- **14:00 午盘监控极简微信提醒**：当 cron job 在 14:00 触发时，脚本已预运行并注入 `[Hermes股票监控大模型分析上下文]`。按固定四段模板输出：【盘面】一句话定性；【持仓池】动作+触发+证伪（每只股票单独一行，最多8行）；【观察池】可买/暂不买+买点；【脚注】数据源/时间/异常。总字数≤450字，禁止Markdown表格/分级标题/长篇数据罗列。模板定义在 `src/qing_investment/stock_monitor.py` 中（搜索 `format_agent_analysis_context` 和 `请按本项目 AGENTS.md`）。
- 分析上下文通过 `format_agent_analysis_context()` 生成，包含规则信号、市场状态、板块连续信号、行情快照。

### 常见排查命令
```bash
# 查看监控配置状态
python -m qing_investment.stock_monitor --status

# 查看收盘复盘上下文
python -m qing_investment.stock_monitor --daily-review-context

# 查看实时分析上下文（带行情）
python -m qing_investment.stock_monitor --live-analysis-context

# 调整去重窗口测试
python -m qing_investment.stock_monitor --dedupe-minutes 15
```

### Cron 任务脚本路径验证

当 cron 任务报告 `can't open file '/home/ubuntu/.hermes/scripts/stock_monitor.py': [Errno 2] No such file or directory` 时，按以下顺序排查：

1. **检查 `~/.hermes/scripts/` 中的实际文件名**：`ls ~/.hermes/scripts/` — 文件名可能是 `qing_stock_monitor.py`、`hermes_stock_monitor.py` 或 `qing_stock_monitor_agent.py`，而非 `stock_monitor.py`
2. **检查项目 repo 中的脚本**：`ls $HERMES_REPO_ROOT/scripts/` — 确认 `stock_monitor.py` 存在于项目目录
3. **确认 wrapper 脚本的行为**：读取 `~/.hermes/scripts/qing_stock_monitor.py`（或实际存在的 wrapper）确认它如何设置 `HERMES_REPO_ROOT` 和调用项目内的 `stock_monitor.py`
4. **手动运行验证**：`cd $HERMES_REPO_ROOT && HERMES_REPO_ROOT=$HERMES_REPO_ROOT python scripts/stock_monitor.py --status`
5. **修复 cron 配置**：将 cron 任务的 `script` 字段改为实际存在的 wrapper 文件名（如 `qing_stock_monitor.py`），或改用 `prompt` 字段直接调用项目内的脚本

**常见命名混淆**：
- `stock_monitor.py` — 项目 repo 内的实际模块（`$REPO_ROOT/scripts/stock_monitor.py`）
- `qing_stock_monitor.py` — Hermes wrapper，设置 `HERMES_REPO_ROOT` 后调用 `uv run python scripts/stock_monitor.py`
- `hermes_stock_monitor.py` — 替代 wrapper，功能类似但路径解析逻辑不同
- `qing_stock_monitor_agent.py` — 带 agent 分析上下文的 wrapper

### Cron 脚本路径安全拦截（Blocked: script path resolves outside the scripts directory）

当 cron 任务报告 `Blocked: script path resolves outside the scripts directory (/home/ubuntu/.hermes/scripts): 'qing_stock_monitor_agent.py'` 时：

**原因**：Hermes cron 调度器的 `script` 字段要求脚本必须位于 `~/.hermes/scripts/` 目录下。若 `script` 指向的文件名在 `scripts/` 目录中不存在（或被解析为相对路径时指向了外部），调度器会拒绝执行。

**排查与修复步骤**：
1. **确认 scripts 目录中是否存在该文件**：`ls -la ~/.hermes/scripts/ | grep qing_stock_monitor`
2. **若文件不存在**：
   - 检查项目 repo 的 `scripts/` 目录：`ls $HERMES_REPO_ROOT/scripts/`
   - 若文件在项目 repo 中，创建符号链接或复制到 `~/.hermes/scripts/`：
     ```bash
     ln -s $HERMES_REPO_ROOT/scripts/qing_stock_monitor_agent.py ~/.hermes/scripts/qing_stock_monitor_agent.py
     ```
3. **若文件存在但仍报错**：检查文件权限（需可执行）和文件名大小写是否匹配
4. **替代方案（推荐）**：不依赖 `script` 字段，改用 `prompt` 字段直接调用项目内模块：
   ```yaml
   # cronjob 配置示例
   prompt: |
     cd $HERMES_REPO_ROOT && python -m qing_investment.stock_monitor --live-analysis-context
   ```
   或设置 `workdir` 为项目根目录，在 `prompt` 中直接调用模块
5. **验证修复**：手动运行 `cd ~/.hermes/scripts && python qing_stock_monitor_agent.py --status` 确认脚本可正常执行

**关键区分**：
- `script` 字段：要求文件物理存在于 `~/.hermes/scripts/`，调度器会做路径安全检查
- `prompt` 字段：LLM 驱动执行，不限制路径，适合调用项目内模块或外部命令

**cron 触发时的实际执行顺序**：
1. Hermes cron 先尝试运行 `script` 字段指定的脚本
2. 若 `script` 被拦截（路径安全/文件不存在），cron 会回退到 `prompt` 字段，由 LLM 驱动执行
3. LLM 收到 "脚本执行失败" 的提示后，应按本 skill 的降级路径（模块方式 → curl 兜底）获取数据并输出提醒
4. **禁止因 script 失败而输出空内容或 [SILENT]** —— 降级路径必须被执行

### 复盘报告输出规范

收盘监控复盘的最终输出必须写入项目文档目录，文件命名格式：
```
docs/收盘监控复盘_YYYY-MM-DD.md
```

报告必须包含以下七段（与上述五段结构对应，增加数据附录和元信息）：
1. **核心结论**（3-5条）：先给结论，区分有效/存疑/误报。
2. **提醒质量评估**：分类统计表（动作类型/数量/时间分布/有效性）+ 重点信号的深度分析（误报证据链或有效验证）。
3. **漏报检查**：分指数/持仓/观察池三张子表，每行包含"规则/标的→阈值→收盘值→是否应触发→实际状态→漏报原因"。
4. **去重合理性**：被压制信号明细表（时间/动作/内容/与上条间隔/判断）。
5. **YAML配置调整建议**：按文件分类，给出可直接粘贴的配置片段。必须包含 `positions.yaml` 的 `reduce_zone`/`risk_zone` 补充、`strategy_pack.yaml` 的阈值调整和格式修复、`sector_groups` 清理。
6. **下一交易日观察条件**：3条，每条含触发条件+证伪条件+意义说明。
7. **附：今日关键数据速查**：收盘行情关键指标速查表。

报告末尾必须标注：*数据时间戳、数据源*。

## 禁止事项

- 不编造价格、财务、新闻或博主观点。
- 不假设任何运行环境的金融数据工具名称固定；由当前模型自行识别可用原生工具。
- 不跳过看图步骤。
- 不把"买/卖"作为无条件结论。
- 缺字段时必须输出分析降级说明。

## 用户交互风格

执行本 skill 相关任务时，遵守以下交互规范：

- **用户说"停" / "stop" / "不要改" / "don't change"时**：立即停止当前操作，不完成剩余步骤，不解释为什么停止。
- **用户要求"直接执行"或表现出对冗长解释的不耐烦时**：跳过逐步说明，直接执行操作，完成后给极简结果摘要。
- **用户要求"先不改脚本，先处理文档"时**：优先处理文档/分析任务，脚本修复延后，不争论顺序。
- **用户偏好简化逻辑**：当用户明确拒绝区分逻辑（如"不用区分置顶评论和普通评论，只看用户名"），立即按简化方案执行，不保留原复杂逻辑。
- **用户独立验证文件操作**：用户会通过 SSH 登录服务器直接检查文件。每次写入操作后，主动提供文件路径和关键内容摘要，方便用户核对。
