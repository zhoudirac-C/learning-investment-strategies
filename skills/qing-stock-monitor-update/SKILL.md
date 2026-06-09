---
name: qing-stock-monitor-update
description: |
  Update stock monitor configuration (watchlist, strategy_pack, positions) based on
  real-time market data and blogger (UP) latest views. Handles observation pool updates,
  position management, and technical inference when UP has not explicitly commented.
  Use when the user asks to update watchlist, observation pool, position strategy,
  or stock monitor configuration.
---

# qing-stock-monitor-update

## 目标

基于真实股价数据和博主最新观点，更新 `config/stock_monitor/` 下的三个配置文件：
- `watchlist.yaml` — 观察池 themes 和 stocks
- `strategy_pack.yaml` — 市场框架、指数规则、量化策略
- `positions.yaml` — 持仓管理、做T计划、风控

## 触发条件

- "更新观察池"
- "更新 stock monitor"
- "把新 theme 加到 watchlist"
- "看看持仓要不要调整"
- "今天收盘后更新策略"
- "生成明天的交易计划"

## 必读参考

1. `skills/qing-stock-monitor-update/references/qualitative-fields-spec.md` — 描述型字段规范
2. `skills/qing-stock-monitor-update/references/data-fetch-script.md` — 数据获取脚本规范（含输出数据读取方法）
3. `skills/qing-stock-monitor-update/references/yaml-update-protocol.md` — YAML 更新协议
4. `skills/qing-stock-monitor-update/references/technical-inference.md` — 无 UP 观点时的技术推断规则
5. `skills/qing-stock-monitor-update/references/technical-analysis-scan.md` — **全项目标的扫描 + 技术分析**：`scripts/scan_all_stocks.py` 的详细使用说明，含均线/支撑压力/量价/K线形态/综合评分等6个技术分析维度。**新增 `--json-summary` 标志**（2026-06-06）：输出紧凑 JSON 供 agent/cron 消费，包含 tech_score、tech_signal、ma_summary + entry 信息。
6. `skills/qing-stock-monitor-update/references/entry-points-generation.md` — **Entry Points 生成规范**：基于技术分析生成介入区间的4种方法（均线法/低点法/回撤法/分时法），仓位配置原则，触发/失效条件规范
7. `skills/qing-stock-monitor-update/references/patch-disambiguation-pitfall.md` — Patch 工具歧义匹配陷阱与解决
8. `skills/qing-stock-monitor-update/references/narrative-bulk-update-from-review.md` — 从复盘文档批量更新 narrative 的规范流程与常见陷阱
9. `skills/qing-stock-monitor-update/references/data-source-fallback-chain.md` — 数据源降级时的备用获取方案（腾讯 API、venv pip 修复、glmv 脚本）
10. `skills/qing-stock-monitor-update/references/claims-consistency-check.md` — **Claims 一致性校验**：更新 strategy_pack 前必须与 claims 交叉验证，防止策略与博主纪律矛盾。含全项目标的扫描工具 `scripts/scan_all_stocks.py` 使用说明
11. `skills/qing-stock-monitor-update/references/sector-rotation-rules-format.md` — **sector_rotation_rules 格式规范**：list of dicts 格式，引用 sector_groups 的 id
12. `skills/qing-stock-monitor-update/references/daily-review-cases.md` — **收盘监控复盘案例库**：历史复盘典型案例，含有效性判断标准、开盘诱多识别 checklist、相对强弱伪信号识别方法、盘中配置更新时序陷阱、板块轮动标签语义混淆、用户反馈驱动的配置调整流程、去重机制设计（"用户已执行"状态跟踪）
15. `skills/qing-stock-monitor-update/references/bilibili-top-comment-workaround.md` — **Bilibili 置顶评论获取**：当前抓取脚本不抓置顶评论，需浏览器手动查看或后续开发 API 抓取
16. `skills/qing-stock-monitor-update/references/hermes-cron-output-access.md` — **Hermes Cron Job 输出访问**：当用户引用 cron job ID 时，如何找到并读取 `~/.hermes/cron/output/<job_id>/` 下的复盘报告
17. `skills/qing-stock-monitor-update/references/bilibili-notify-maintenance.md` — **Bilibili 动态通知脚本维护**：`bilibili_notify.py` 的常见问题（函数名不匹配、专栏类型未处理、cron cookie 缺失）、修复方案、部署同步纪律
16. `framework/technical-analysis-framework.md` — 技术工具层规则（轨道B）
16. `skills/qing-stock-monitor-update/references/llm-hallucination-prevention.md` — **LLM 幻觉防范**：cron 任务生成股价数据时的验证与约束（含批量更新 cron prompt 模板）
17. `skills/qing-stock-monitor-update/references/cron-script-sync.md` — **Cron 脚本双向同步**：`~/.hermes/scripts/` 与项目目录 `scripts/` 的同步策略、软链接方案、废弃脚本处理
18. `skills/qing-learning/references/claim-schema-validation.md` — **Claim Schema 验证**：生成 claims 时的字段要求和枚举值规范（跨 skill 共享）
19. `skills/qing-stock-monitor-update/references/yaml-patterns-20260604.md` — **新增 YAML 配置模式（已代码实现）**：dedupe_by_type 差异化去重（风控15min/减仓30min/板块轮动30min + 价格突破阈值）、t_zone 做T区间拆分、sector_group 清理三同步
20. `skills/qing-stock-monitor-update/references/dedupe-by-type-implementation.md` — **dedupe_by_type 代码实现细节**：映射规则、价格突破逻辑、向后兼容策略、7个单元测试覆盖。已代码实现，配置生效中。
22. `skills/qing-stock-monitor-update/references/direction-performance-scan.md` — **全方向性能扫描**：模式 C——当用户要求"梳理所有方向哪些在调整"时，全方向 × 全标的 × 全行情的批量扫描方法论。含腾讯 API 批量获取、theme 分组统计、缺口检测流程。
23. `src/qing_investment/agent/tools/stock_sector_mapper.py` — **个股板块三层定位**：当 UP 未提及某标的时，通过新浪 API 获取实时板块排名，量化判断个股地位（日内龙头/中军/趋势/跟风）。含本地缓存管理（`config/stock_monitor/stock_sector_mapping.json`，TTL=24h）。定时重建脚本 `scripts/build_sector_mapping.py`，cron `*/30 6-8 * * 1-5`（盘前 6:00-8:30 每半小时，共 6 次）——增量模式：缓存新鲜则秒级跳过，过期自动全量重建（~6 分钟）。`--force` 强制全量，`--retries 3` 失败自动重试（指数退避）。HTTP 层已内置 3 次重试（5s/10s/20s），timeout 30s。当缓存过期且所有 cron 次都失败时，`get_stock_sectors()` 降级为快速反查模式（只查 20 个最热门板块）。
24. `skills/qing-stock-monitor-update/references/config-health-check.md` — **配置健康检查**：watchlist/strategy_pack/positions 完整性检查清单（code 格式、entry 去重、sector 覆盖、防失真、非主板标记）。每次 config review 或大更新后执行。
25. `scripts/validate_config.py` — **配置一致性校验脚本**：独立运行 `python scripts/validate_config.py` 自动检查 code 格式、entry 去重、sector_groups 覆盖、today_snapshot 位置、claims 一致性、持仓区间完整性。退出码 0=干净，1=警告，2=错误。推荐每次 config 更新后运行。详见 `references/validate-config-script.md`。
27. `skills/qing-stock-monitor-update/references/scan-all-stocks-json-summary.md` — **scan_all_stocks JSON 输出**：`--json-summary` 标志的使用说明、输出格式、集成方式。
28. `references/trader-mindset-design-philosophy.md` — **设计哲学纠正（2026-06-08）**：用户明确纠正 v1.0 方向——系统不应走向更多量化规则，而应让 LLM 以交易者思维（赔率思维+机会发现）做出判断。所有后续修改必须遵循此哲学。
29. `references/architecture-review-framework.md` — **配置架构系统性Review框架**：四步法（现状→缺陷→方案→优先级），区别于 config-health-check（配置完整性检查）。当用户要求对 config+cron 做全链路架构 review 时使用。
30. `references/prompt-layer-transformation-playbook.md` — **Prompt 层改造实战手册**：当系统被诊断为"太保守、只减仓不提醒买入"时，如何仅通过重写 system prompt 实现交易者人格嵌入、赔率框架激活、反保守自检。含 5 个 prompt 文件改造清单、nodes.py 注入逻辑、JSON 字段扩展指南。
31. `references/daily-state-hot-score-implementation.md` — **Phase 3-4 架构实现参考**：daily_state 状态机、hot_score 热度分、claims_to_entry 桥接、3节点 cron prompt（**09:26/14:00/15:20**，注意 09:26 是集合竞价后，不可改为 09:30）、add_zone 触发逻辑的完整实现细节与维护指南。
32. `references/config-field-audit-checklist.md` — **Config 字段补全核对清单**：当用户要求"核对改动是否与架构文档一致"时使用。覆盖 Prompt/代码/Config 三层，含自动化核对脚本、常见遗漏模式、修复优先级。
33. `references/no-agent-cron-timeout-patterns.md` — **no-agent Cron 超时防御模式**
34. `references/batch-kline-screening-workflow.md` — **批量K线筛选+介入点生成工作流**：拉60日K线→UP标准筛选→Qing-Agent分析→生成entry_points→更新watchlist：增量+高频 cron、`save_cache` 防测试破坏、HTTP 重试+退避、`python -u` 非缓冲输出。适用于所有 `no_agent: true` 的长运行 cron 脚本。
34. `references/config-cron-alignment-debugging.md` — **Config-Cron 对齐诊断决策树**：cron 空输出三步诊断法、API 故障 vs schedule 不匹配区分、微信限流偏移修复。
35. `references/batch-kline-qing-agent-fallback.md` — **Qing-Agent K线拉取不可靠 → 本地批量兜底**：Qing-Agent /chat 端点的自动K线拉取成功率低（18只仅1只成功），应改为本地批量拉取后再结构化注入。含 `scripts/batch_kline_analysis.py` 使用说明和内联代码示例。
36. `references/market-index-config.md` — **市场指数配置与数据注入**：当前拉取的五大指数（上证/深证/创业板/科创50/全A）、全A指数来源说明（同花顺无API→中证全指替代）、新增指数的两步修改法（stock_monitor.py + stock_data.py）、验证命令。
37. `references/qing-agent-endpoints.md` — **Qing-Agent 双入口差异**：`/analyze/trigger` vs `/chat` 的架构差异、数据流对比、选择决策树、实战陷阱。盘后分析用 `/chat`。

## 工作流程

### Step 0: 前置检查

1. **`git pull`**：确保本地文件是最新版本，避免基于旧版本修改后产生冲突。
2. **Cron 脚本同步检查**：若用户同时修改了 cron 监控脚本（如 `hermes_stock_monitor_agent.py`、`hermes_stock_monitor_daily_review.py`），必须确保 `~/.hermes/scripts/` 与项目目录 `~/learning-investment-strategies/scripts/` 保持一致。推荐方案：前者使用 **Wrapper 委托模式**（真实文件，内容委托到项目版本），详见 `references/cron-script-sync.md`。用户硬性要求："每次改动都需要保证两边一致"。
3. **检查数据是否已同步**：若 watchlist 的 `today_snapshot`、`technical_narrative`、`sector_narrative` 已包含复盘文档中的数据，不要重复写入。向用户报告当前同步状态，询问是否需要基于**今早动态**追加更新。
4. **区分两种更新模式**：
   - **模式 A（基础）**：更新已有票的 narrative + today_snapshot
   - **模式 B（极易遗漏）**：扫描复盘文档中的"关注地位方向""核心思路""方向提示"段落，提取 UP 新提到的标的，新增到 watchlist 并在 strategy_pack 中补充 entry_points
   - **模式 C（方向体检）**：用户要求"看看过去提到的方向哪些在调整"或"全面梳理UP方向"时，执行全方向 × 全标的 × 全行情扫描（见 `references/direction-performance-scan.md`）
   - **必须先执行模式 A，再执行模式 B，两步都完成才算完整**

### Step 1: 获取真实数据

运行数据获取脚本：

```bash
cd ~/learning-investment-strategies
python3 skills/qing-stock-monitor-update/scripts/fetch_stock_data.py \
  --config-dir config/stock_monitor \
  --output /tmp/stock_data_$(date +%Y%m%d_%H%M).json
```

**读取输出数据**：`stocks` 字段是列表（list），不是字典。必须先转换为 `code -> info` 映射：

```python
import json
with open('/tmp/stock_data_YYYYMMDD_HHMM.json') as f:
    data = json.load(f)
stocks_list = data.get('stocks', [])
stock_dict = {s['code']: s for s in stocks_list if 'code' in s}
# 市场指数：data['market']['indexes']
```

数据源优先级：
1. 运行环境原生金融数据能力
2. 东方财富实时行情（stock_monitor.py 已有）
3. glmv-stock-analyst/fetch_all.py（K线、基本面、主力资金、分时图）
4. **腾讯财经 API（curl，无需 Python 包，备用首选）**
5. 新浪财经/其他公开接口（降级）

降级规则：数据源不可用时标记 `degraded: true`，不阻断更新。详见 `references/data-source-fallback-chain.md`。

**全数据源降级时的兜底策略**（本会话中出现过）：
- 如果所有外部 API（Tencent API / East Money / akshare）都超时或返回空：
  1. 使用 `watchlist.yaml` → `today_snapshot` → `stocks_with_data` 中的最新本地行情数据
  2. 使用 `strategy_pack.yaml` → `today_snapshot` 中的指数数据
  3. 在回复中标注"数据源降级，基于本地快照数据（来自最近一次同步）"
  4. 不编造价格。如果本地数据也缺失该标的，如实告知用户"无法获取实时价格"
- 注意：本地快照是上一交易时段的数据，非实时。用于策略方向的判断足够，但精确买入/卖出点位需等数据源恢复后确认。

**备用：直接 curl 腾讯财经 API（当脚本超时或不可用时）**

`fetch_stock_data.py` 可能因网络或依赖问题超时。此时用腾讯 API 直接获取指定标的的收盘行情：

```bash
curl -s "http://qt.gtimg.cn/q=sz000969,sz000066,sh603920"
```

解析：字段3=code，字段4=最新价，字段5=昨收。Python 示例：

```python
import urllib.request
url = f"http://qt.gtimg.cn/q={','.join(codes)}"
data = urllib.request.urlopen(url).read().decode("gb2312", errors="ignore")
for line in data.strip().split(';'):
    if not line.strip(): continue
    parts = line.split('="')[1].rstrip('"\n;').split('~')
    code = parts[2]; latest = float(parts[3]); prev_close = float(parts[4])
    pct = round((latest - prev_close) / prev_close * 100, 2)
```

注意：GB2312 编码，name 可能乱码。只适合快速获取收盘价，无 K 线/基本面。

**⚠️ 腾讯 API 代码格式陷阱**：API 返回的 key 是不带前缀的纯数字（如 `002055`），而非请求时用的 `sz002055`。匹配时必须使用数字 code 作 key，不能用带 sh/sz 前缀的字符串：

```python
# ❌ 错误 — 前缀不匹配
quotes['sz002055']  # KeyError

# ✅ 正确 — 用 parts[2]（纯数字）作 key
api_key = parts[2]  # '002055'
quotes[api_key] = {...}
```

**更新前检查 entry_suggestions**：
若 `config/stock_monitor/entry_suggestions/` 目录下有待确认文件（由 `scripts/sync_claims_to_config.py` 生成），先读取并展示给用户确认。确认后写入 strategy_pack.yaml，删除建议文件。

### Step 2: 检查 UP 最新观点（模式 A + 模式 B）

**读取最近 3 天的内容**（必须执行）：
- `knowledge/claims/claim-YYYYMMDD-*.yaml`
- `knowledge/wiki/每日复盘/YYYY-MM-DD.md`
- `sources/raw/财经/`（最近 3 天）

**可选：调用 Qing-Agent 辅助分析（推荐，当服务在线时）**

如果 Qing-Agent 服务在线（`curl -s http://127.0.0.1:8000/health` 返回 `{"status":"ok"}`），可调其 `/chat` 端点获取 UP 风格的通盘判断：

```bash
curl -s -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "请分析今天收盘后的市场状态，包括指数、板块、主线方向、风险提示，以及持仓的操作建议。持仓：安泰科技300股成本28.67，中国长城400股成本18.11", "session_id": "stock-monitor"}'
```

Qing-Agent 返回的是**定性判断**（方向/态度/策略基调），不是具体价格数据。与本地数据配合使用：
- **Qing-Agent →** "当前阶段：主升末期，微盘股破位，不能左侧抄底"
- **本地数据 →** "上证支撑4033，持仓标的止损位24.5"
- **具体操作以本地数据为准，方向判断参考 Qing-Agent**

**何时调用 Qing-Agent**：
- UP 刚发了视频/复盘专栏，但还没转化为 claims → Qing-Agent 可直接提取 UP 风格判断
- 需要 UP 口吻的完整市场分析来填充 today_snapshot/up_bias
- 多个来源说法不一，需要综合判断

**何时不调用**：
- 只需更新单个标的叙事，不涉及方向判断
- Qing-Agent 服务未启动

**可选：调用 Qing-Agent 辅助分析（推荐）**
如果 Qing-Agent 服务在线（`curl -s http://127.0.0.1:8000/health`），可调其 `/chat` 端点获取 UP 风格的通盘判断：

```bash
curl -s -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "请分析今天收盘后的市场状态，包括指数、板块、主线方向、风险提示", "session_id": "stock-monitor"}'
```

Qing-Agent 返回的是**定性判断**（方向/态度/策略基调），不是具体价格数据。与本地数据配合使用：
- Qing-Agent → "当前阶段：主升末期，微盘股破位，不能左侧抄底"
- 本地数据 → "上证支撑4033，持仓标的止损位24.5"
- 具体操作建议以本地数据为准，方向判断参考 Qing-Agent

**模式 A：更新已有标的 up_mention_status**
- `last_mentioned_date`
- `mention_context`
- `explicit_operation`（如有明确买/卖/持有/规避）
- `sentiment`（积极观察/中性提及/明确规避/未提及）

**模式 B：提取 UP "关注方向"（极易遗漏，必须执行）**
- 扫描复盘文档中的"关注地位方向""核心思路""方向提示""强势股"等段落
- 提取 UP 明确提示要关注的标的（即使当前不在 watchlist 中）
- 检查这些标的是否已在 watchlist 中：
  - **若不存在**：新增 theme 或追加到对应 theme，写入完整字段（含 narrative）
  - **若已存在**：更新 narrative，并在 `watch_reason` 中追加 UP 最新提示
- 无论是否新增，都必须在 strategy_pack.yaml 的 `entry_points` 中补充操作策略
- **示例命令**：`grep -n "关注地位方向\\|核心思路\\|鼎龙股份\\|裕太微" sources/raw/财经/复盘*.md`

**模式 B 变体：Claims → watchlist 缺口检测（新增）**
当 claims 中明确提到某个方向（如"燃气轮机：机构看好，回调上车，中线格局"），但 watchlist 中没有对应的独立 theme 时：
1. 不要忽略。这是 UP 在传递方向信号，只是还没转化为 watchlist 标的
2. 在分析回复中**明确标注该缺口**："UP 在 claim-XXXX-YY 中提到某方向，但 watchlist 缺失此 theme"
3. 如果用户要求补充，按模式 B 流程新增 theme + 补充标的
4. 如果 claim 中只有方向判断没有具体标的，如实告知："UP 给了方向判断但未点名具体标的，需要联网搜索或等后续内容"

### Step 2.5: 同步更新 strategy_pack.yaml（必须与 watchlist 同步，不可遗漏）

**不可遗漏**：只更新 watchlist 而不更新 strategy_pack 会导致观察池无法指导实际交易。用户明确反馈："不只是更新watchlist 你每次更新的时候都要把操作策略，介入股价都加上，不然什么时候能买入呢？观察有啥有用呢"

**更新前必须执行 claims 一致性校验**（详见 `references/claims-consistency-check.md`）：
1. 扫描最近 3 天的 claims，查找与目标标的相关的博主观点
2. 若 claim 中博主明确说"不追高""韭菜行为""只观察"，对应标的必须配置为 `entry_zone: 只观察不介入`，`position_ratio: 0`
3. 在 `note` 中标注 claim 来源（如"来源：claim-20260602-002.yaml"）
4. 常见矛盾：给"已提前提示，现在追是韭菜"的方向配介入区间 → 必须修正为只观察
5. **若用户问"扩大范围"或"还有什么可买"，使用 `scripts/scan_all_stocks.py` 扫描全项目标的，而非仅看已有 entry_points**

**更新前必须执行技术分析扫描**（详见 `references/technical-analysis-scan.md` 和 `references/entry-points-generation.md`）：
1. 运行 `scripts/scan_all_stocks.py` 获取所有标的的实时行情 + 历史K线 + 技术评分
2. 对重点标的（P1/P2、博主新提及、用户询问的）逐一分析：
   - 均线系统：多头/空头/缠绕
   - 回撤幅度：从近期高点回撤 %（判断调整是否充分）
   - 量价关系：放量/缩量/正常
   - K线形态：长下影/反包/大阳线/大阴线/十字星
   - 支撑压力：近期20日高低点
3. 基于技术分析生成介入区间（4种方法）：
   - **均线法**：趋势票回踩 MA5/MA10（如 [MA5×0.97, MA5×1.00]）
   - **低点法**：震荡票接近近期低点（如 [近期低点×0.98, 近期低点×1.02]）
   - **回撤法**：高位票等充分调整（如 [近期高点×0.85, 近期高点×0.90]）
   - **分时法**：日内回踩低点（如 [今日最低×0.99, 今日最低×1.03]）
4. 技术评分与博主观点交叉验证：
   - 技术评分高 + 博主看好 → 正常配置
   - 技术评分高 + 博主不介入 → ❌ 配置为"只观察不介入"
   - 技术评分低 + 博主看好 → ⏳ 配置区间但标注"等更充分调整"
5. 将技术分析结果写入 `entry_points` 的 `note` 字段，便于后续复盘

**更新内容**：
- `quant_entry_strategy.entry_points`：为每个重点标的补充**具体介入区间、仓位、触发条件、失效条件**
- `quant_entry_strategy.position_advice`：更新空仓/满仓的操作建议
- `market_framework`：更新周期阶段、核心问题
- `index_rules`：更新指数关键位

**entry_zone 填写规范**：
  - **必须提供具体价格数字**，不能写"近期平台附近""等分歧后缩量回踩"等模糊描述
  - 若数据源可用：基于当日收盘价，结合技术分析（均线/低点/回撤/分时）计算具体区间
  - **若数据源降级无法获取实时价格**：
    - **诚实说明**："数据源降级，无法获取实时价格。需手动填写"
    - **提供计算规则**："基于当日收盘价，回踩 5-7% 介入"
    - **绝不编造虚假价格**（用户会验证，编造价格会导致信任崩塌）
    - **备用方案**：使用腾讯财经 API（curl）获取价格，详见 `references/data-source-fallback-chain.md`
  - 对于已大涨的票（如单日 +18%）：介入区间需等更充分调整（10-15%）
  - **主板-only约束**：用户只能交易主板票（sh6xxxxx / sz0xxxxx）。若标的非主板（科创板688/创业板300），需在 note 中标注"不可交易（非主板）"，并优先推荐主板替代标的

**position_ratio 填写规范**：
- 必须提供具体仓位（如"1成""0.5成"）
- 高弹性/高风险票降低仓位（如裕太微 0.5 成）
- 空仓总仓位控制在 6 成以内（因新增多个方向）
- 技术评分高 + 博主看好 + 主板 → 1.5-2成
- 技术评分中等 + 博主未提及 + 主板 → 0.5-1成

**触发条件与失效条件规范**：
- 触发条件必须具体可执行："回踩470-480区间，分时不再创新低，放量收回均线"
- 失效条件必须量化："跌破453且30分钟不能收回"
- 不能只写"等企稳""趋势走坏"等模糊描述

**用户交易约束（主板-only）**：
- 用户只能交易主板票（sh6xxxxx / sz0xxxxx），无科创板（688）或创业板（300）权限
- 配置 entry_points 时必须过滤主板-only，非主板标的需明确标注"不可交易（非主板）"
- 为用户推荐标的时，优先主板；若只有非主板可选，需说明并询问是否接受

**无持仓票不配置 stop_loss**：
- 用户明确："没有持仓的不用止损，主要是介入区间和操作策略"
- `stop_loss` 字段只用于已有持仓的票
- 观察池新票只配置 `entry_zone` + `invalidation`（失效条件）

### Step 2.5f: entry_points 状态生命周期管理

架构文档 §4.5.2 为 entry_points 引入了 `status` / `opportunity_pattern` / `odds_analysis` / `claim_basis` 字段。每次更新 strategy_pack 时必须逐条检查：

**status 状态机**：
- `active` → 当前价仍在介入区间附近，等待触发
- `triggered` → 价格已进入介入区间，需推送提醒
- `expired` → 价格已远离区间（>10%）或 claim 已过期，不再有效
- `executed` → 用户已执行操作，转为持仓或归档

**状态转换规则**：
- active → triggered：现价进入 entry_zone 区间，在 note 中记录触发日期
- active → expired：现价偏离 entry_zone > 10% 且无新 claims 支撑，或引用 claim 被 superseded
- triggered → executed：用户确认已买入，记录执行价和日期
- triggered → active：触发超过 5 天未执行，价格仍在区间 → 保持 active；价格已远离 → expired
- executed → 从 entry_points 移除，归档到 positions 的 entry_decision

**赔率分析（odds_analysis）填写规范**：
- `upside_pct`：基于 claim 目标位 vs 当前价的上行空间（如 +15%）
- `downside_pct`：基于技术支撑位 vs 当前价的下行风险（如 -5%）
- `odds_ratio`：upside/downside，如 "3:1"
- `estimated_probability_up`：主观概率估计（如 45%）
- `expected_value`：赔率 × 概率 = 期望收益（如 3×0.45 - 1×0.55 = 0.8）
- **赔率 < 2:1 不配置 entry_point**（不符合不对称机会原则）
- 由 LLM 或人工在更新时填充，非写死

**claim_basis 校验**：
- 每条 entry_point 应标注来源 claim ID（如 `claim-20260604-003`）
- 若引用 claim 被 superseded → 更新 claim_basis 到新 claim
- 若引用 claim 的 statement 与 entry 逻辑矛盾 → 修正或删除 entry_point

### Step 3: 更新 watchlist.yaml

**追加原则**：
- 新 theme → 追加到 `themes` 列表末尾
- 新 stock → 在对应 theme 的 `stocks` 列表内追加
- 旧 theme/stock 保留，除非用户明确要求删除
- **必须扫描复盘文档中的"关注地位方向""核心思路"段落，提取 UP 新提到的标的**
- code: "600246.SH"
  name: "万通发展"
  role: "pcie_switch_core"
  segment: "PCIe Switch"
  priority: "P1-核心"
  watch_reason: "..."
  sync_with_index: "..."
  confirm_with: ["ST得润", "寒武纪"]
  buy_setup:
    - "条件1"
    - "条件2"
  invalidation_setup:
    - "失效1"
    - "失效2"
  # 新增描述型字段
  up_mention_status:
    last_mentioned_date: "2026-05-28"
    mention_context: "博主在复盘视频中提到..."
    explicit_operation: null
    sentiment: "积极观察"
  technical_narrative:
    trend: "5日线上方运行"
    volume_character: "涨停放量"
    key_levels: ["支撑：15.0", "压力：17.5"]
    pattern: "突破平台后首板"
    note: "封单坚决"
  sector_narrative:
    relative_strength: "CPU链最强"
    money_flow: "主力连续2日净流入"
    leader_follower: "板块龙头"
    catalyst: "字节自研CPU"
    risk: "组内分化"
```

### Step 4: 更新 strategy_pack.yaml

**更新内容**：
- `today_snapshot`：市场环境、UP 基调、整体操作建议
- `market_framework.current_stage`：周期阶段（如情绪拐点/主升/调整）
- `market_framework.core_question`：当前核心问题
- `index_rules`：指数关键位（如 4055 支撑）
- `quant_entry_strategy`：基于收盘数据的量化介入点
- `sector_groups`：板块分组（如有新增板块）
- `agent_analysis_schedule`：大模型分析时间点（如需调整）

**`index_rules` 格式兼容性（必读）**：
- 代码对通用格式（`trigger_condition: close_below`）支持不完整，存在漏报风险。
- **必须同时写 legacy 格式兜底**：`- trend_defense: 4070` 作为 `trigger_condition: close_below` 的兼容备选。
- 实际验证方法：更新后运行 `python -m qing_investment.stock_monitor --ignore-trading-time`，检查 `alert_decision_log` 是否生成对应记录；若未生成，说明通用格式未被支持，需补 legacy 格式。

**`sector_rotation_rules` 关键字段**：
- 格式：**list of dicts**，每个 rule 有独立 `id`
- `offensive_group_ids` / `defensive_group_ids` / `avoid_group_ids`：引用 `sector_groups` 中定义的 `id`，不是字符串列表
- `min_spread_pct`：进攻/防御组均涨幅差阈值（默认 1.0，复盘后可视情况上调）
- `min_red_ratio_spread`：红盘率差阈值
- `require_offensive_positive: true`（可选）：防止"跌得少"被误判为"进攻回流"
- 详见 `references/sector-rotation-rules-format.md`

**`sector_groups` 同步纪律**：
- 新增持仓标的必须加入对应 sector_group，否则不会被纳入板块轮动计算。
- 已清仓标的必须从 sector_group 中移除，否则会拖累组平均涨幅，产生错误的板块轮动信号。
- **清理 sector_group 时必须执行三同步**：①从 `sector_groups.members` 移除 → ②从 `offensive_group_ids` 移除（若组变空）→ ③更新 `notification_policy.only_notify_when` 中的对应提醒条件。
- **ST/高风险标的处理**：不要单独拆到独立的 `st_watch` `avoid` 组。用户偏好是 ST/高风险标的保留在原来的 thematic group 中（如 ST得润留在 cpu_self_development），保持 group 结构简单。不创建单独的 ST 观察组。
- **旧方向降级为 monitor_only（不删除）**：当 UP 切换关注方向（如 MLCC→燃气轮机），不要删除旧的 sector_groups。改为 `style: monitor_only` + 添加 `note` 说明原因。在 `sector_rotation_rules` 中新增 `monitor_only_group_ids` 列表，将降级组从 `offensive_group_ids` 移入。这样旧主题仍参与板块强弱监测但不触发买入信号。示例：`style: monitor_only` + `note: UP已转向其他方向，降级为只监控不介入` + sector_rotation_rules 新增 `monitor_only_group_ids` 列表。

### Step 5: 更新 positions.yaml

**⚠️ Step 5.0：防失真检查（必须最先执行）**

**反面案例（2026-06-05）**：安泰科技成本28.667，reduce_zone 仍为 25.5-26.5，但现价已跌至 20.98。风控线距现价 +20% 以上，完全失效——跌破 24.0 时未触发任何提醒因为风险线早已被跌破。**根因：上次更新时没有根据最新价格重新校验价格区间**。

**自动化防护（2026-06-06 已集成到 stock_monitor.py）**：`validate_position_price_zones()` 函数在每次 cron tick 拉取行情后自动检查。检测规则：
- `reduce_zone` 下限距现价 > 12% → 向上失真（提醒下调）
- `risk_zone` 下限 > 现价（已被跌破）→ 向下失真（风险线已失效）
- `reduce_zone` / `risk_zone` 均缺失 → 高危漏报

失真警告会写入 `state.json` 的 `stale_zone_warnings` 字段，并在每日复盘上下文中展示。**即使有自动化检查，手动更新时仍需执行以下流程**（自动化检查是兜底，不是替代）。

**强制流程**：

1. **先获取实时数据**（Step 1），再加载 positions.yaml。
2. **逐只检查每个持仓的价格区间**：
   - 计算 `reduce_zone` / `risk_zone` / `t_zone` 与当前价格的距离
   - 若 `risk_zone` 下限 > 现价（已被跌破）→ **必须下调**
   - 若 `reduce_zone` 下限与现价差距 > 10%（如 25.5 vs 20.98，差距 +21%）→ **必须下调**
   - 若 `t_zone` 完全脱离现价区间 → **必须调整**
3. **重新计算合理区间**（基于当前价格）：
   - `reduce_zone`：锚定前期成本密集区或近期反弹高点，距现价 +5~12%
   - `risk_zone`：锚定近期低点（如当日最低、20日最低），距现价 -3~5%
   - `t_zone`：锚定现价 ±2%，用于日内做T
4. **更新 `today_plan`**：基于**当前价格**重新评估操作策略，不能照抄昨天的 plan。
5. **更新 `latest_monitor_reference`**：写入当前实时价、涨跌幅、同板块验证结果。

**更新内容**：
- `latest_quote_snapshot`：最新行情快照
- `latest_up_bias`：UP 最新判断基调
- `today_key_signals`：今日关键信号
- 每个持仓的 `latest_monitor_reference`：最新价、涨跌幅 + 同板块验证
- 每个持仓的 `pnl`：浮动盈亏
- 每个持仓的 `reduce_zone` / `risk_zone` / `t_zone`：基于当前价格重新校验 → 失真则更新
- 每个持仓的 `today_plan`：基于**当前价格+最新 claims**重新编写（不保留旧计划）

**持仓变动处理**：
- **持仓-YAML缺口检测（必须优先执行）**：用户告知持仓后，先对比 `positions.yaml`。若用户说了某只票但 YAML 中没有 → 这是缺口，必须新建。常见场景：用户手动建仓后还没更新配置，或上次清仓后重新开仓。**反面案例**：用户说"大同证券天赐材料200股"，positions.yaml 中大同账号 `positions: []`（已全部清仓），Agent 只更新了华宝的万泽股份而遗漏了天赐材料。
- **新建持仓**：添加完整字段（code, name, shares, cost, reduce_zone, risk_zone, account, open_date, note, today_plan）。同时更新 `strategy_summary` 和 `portfolio_stats`（total_positions +1, direction_concentration 追加）
- **减仓**：更新 shares 和 cost（用户会提供新的 cost），在 note 中标注"减仓后X股（原Y股）"
- **清仓**：从 `positions` 列表移除，添加到 `closed_positions`，记录卖出价和盈亏。同时更新 `strategy_summary` 和 `portfolio_stats`
- **账户重命名**：若用户要求更改账户名称，同步更新所有 `account` 字段和 `strategy_summary` 中的描述

**用户减仓响应流程（新增）**：
当用户告知"已减仓X股"时：
1. **立即更新 positions.yaml**：
   - 更新 `shares`：原股数 - 减仓股数
   - 更新 `cost`：用户提供的新的成本价（若用户未提供，保持原 cost）
   - 在 `note` 中追加："6月X日减仓X股，剩余Y股，新成本Z.XX"
   - 更新 `today_plan`：基于新持仓重新评估明日策略
2. **重新评估提醒需求**：
   - 获取当前实时行情
   - 基于新持仓计算新的 reduce_zone / risk_zone（如需调整）
   - 判断是否需要后续减仓提醒：
     - 若剩余股数仍较多（>50%原持仓）且价格仍在风险区间 → 保留提醒
     - 若剩余股数很少（<30%原持仓）或价格已脱离风险区间 → 当天不再提醒
3. **向用户确认**：
   - 汇报更新后的持仓（剩余股数、新成本、当前盈亏）
   - 说明后续提醒逻辑（是否还会继续提醒、什么条件下提醒）
   - 询问是否需要调整 reduce_zone / risk_zone

**用户未告知减仓时的默认逻辑**：
- 用户未主动告知减仓 → 保持原有提醒逻辑不变
- 正常触发 reduce_zone / risk_zone 提醒
- 不猜测用户是否已操作

**示例对话**：
```
用户：安泰科技减仓200股
AI：收到。更新安泰科技持仓：700股→500股，成本24.702保持不变。
     当前价22.12，新浮亏约-11.1%。
     reduce_zone 22.00-23.00 是否需要上调？
     后续若价格仍在22-23区间，会继续提醒做T机会。
```

**价格区间字段规范（必读）**：
- `risk_zone`：风控区间，格式 `"44.5-45.5"`。代码优先读取此字段，触发条件为 `latest <= risk_zone[1]`（即区间上限）。
- `risk_line`：单点风控线（如 `44.5`）。代码兼容作为 `risk_zone` 的 fallback，解析为 `(44.5, 44.5)`，触发条件为 `latest <= 44.5`。
- `reduce_zone`：减仓观察区间，格式 `"41.15-42.5"`。当 `latest` 落入此区间时触发减仓观察提醒。
- **关键陷阱**：若只配 `risk_line: 44.5` 而期望区间触发（如 44.5-45.5），必须用 `risk_zone: "44.5-45.5"`。
- **`positions.example.yaml` 必须使用 `risk_zone` 而非 `risk_line`**：示例文件作为模板应使用推荐字段名，避免复制后形成旧习惯。
- **高危漏报**：若持仓未配置 `reduce_zone` 或 `risk_zone`/`risk_line`，`evaluate_position_alerts()` 将完全跳过该持仓，导致跌停/大跌无任何提醒。更新时必须逐条确认每个持仓都配置了价格区间字段。

**add_zone 维护规范（架构文档 §4.5.3）**：
- `add_zone` 与 `reduce_zone` 对称，方向相反——价格跌到 add_zone 触发"加仓提醒"
- 计算依据：技术支撑位（MA20/MA60/前低）上方 1-3%
- 与 reduce_zone 的空间关系：add_zone < 现价 < reduce_zone
- `add_trigger`：触发条件，如"回踩30.5-31.0企稳，分时不创新低"
- `add_position_ratio`：加仓仓位，如"0.5成"
- `add_invalidation`：加仓失效条件，如"跌破30且30分钟不能收回"
- 每次更新持仓时，基于当前价重新校验 add_zone 是否仍然有效

**trade_log 维护规范**：
- 由 cron 或手动在检测到持仓操作后自动追加
- 格式：`{date, action, price, shares, reason}`
- 操作类型：买入/加仓/减仓/清仓/做T
- 15:20 cron 复盘时自动校验 trade_log 与 shares 一致性
- 手动更新持仓后也需追加 trade_log 记录

**portfolio_stats 维护规范**：
- `total_positions`：当前持仓数量
- `total_exposure_pct`：总仓位占资金比例
- `weighted_avg_odds`：按仓位加权的平均赔率
- `direction_concentration`：各方向仓位集中度
- 每次持仓变动（建仓/加减仓/清仓）后需重算
- 15:20 cron 复盘时自动重算

**已清仓标的处理**：
- 已清仓标的必须移入 `closed_positions`，同时从 `positions` 列表中删除。
- 若已清仓标的仍留在 `positions` 中，会继续触发减仓/风控提醒，产生配置滞后误报。

**today_plan 格式**：
```yaml
today_plan:
  - "【复盘定调】标的定性描述"
  - "【明日策略】持有/做T/减仓/清仓"
  - "【做T区间】低吸：X.XX-X.XX；高抛：X.XX-X.XX"
  - "【风控线】X.XX-X.XX，跌破且30分钟不能收回触发"
  - "【强度确认】板块同步条件"
  - "【禁忌】不追涨停/一致高开"
```

**无 UP 观点时的处理**：
- 基于 `technical_narrative` + `framework/technical-analysis-framework.md` 推断
- 必须写入 `inference_note`：
  ```yaml
  inference_note:
    basis: "UP未明确提及，基于技术框架推断"
    confidence: "中"
    key_assumption: "假设大盘不跌破4055"
    invalidation: "若放量跌破15.8，推断失效"
    suggested_action: "等回踩15.8-16.0区间企稳后轻仓试探"
  ```

### Step 6: 验证

```bash
cd ~/learning-investment-strategies
python3 -m qing_investment.stock_monitor --status
python3 -m qing_investment.stock_monitor --analysis-context
python3 scripts/validate_config.py
```

确认：
- YAML 解析无错误
- `validate_config.py` 退出码为 0（无错误）或仅预期内的 sector 覆盖警告
- 输出包含新增的描述型字段
- 大模型分析上下文格式正确
- **code 格式标准化**：检查 watchlist 中所有 code 是否为 `XXXXXX.SZ`/`XXXXXX.SH` 格式（不是 `shXXXXXX`/`szXXXXXX`）
- **entry_points 去重**：按 `code + name` 检查是否重复
- **today_snapshot 唯一**：确认 today_snapshot 仅在 strategy_pack.yaml 中存在，watchlist.yaml 中不存在
- **sector_groups 覆盖**：确认新增的主题对应的 sector_group 已同步创建

### Step 7: Git 提交

```bash
cd ~/learning-investment-strategies
git add config/stock_monitor/watchlist.yaml config/stock_monitor/strategy_pack.yaml
git commit -m "monitor: update watchlist/strategy for $(date +%Y-%m-%d)"
# positions.yaml 已 gitignored，不提交
```

## 用户交互模式：方案确认后批量执行

用户偏好先读完分析结论→确认→再执行。当给出 config 审计或修改方案时，先展示摘要（P0/P1/P2 分级），等用户说"按照你的说法改"后再批量执行。不要在未确认时直接改。

## 关键纪律

-2. **Cron 时间必须与文档一致**：`config-cron-architecture-review.md` 明确指定 3 节点为 09:26（集合竞价后）/ 14:00 / 15:20。**不可将 09:26 改为 09:30**——09:26 是竞价结束、结果可用的精确时刻，09:30 已错过最佳定调窗口。修改 cron 时间前必须核对文档，不可凭直觉"取整"。
-2.5. **设计文档意图必须完整理解——"差异化"≠"减少"**：当设计文档说"v1.0精简为3个节点，但修正为不减少节点数，每个节点有独立的差异化prompt"时，正确理解是：**保持原有的9个时间节点不变，只改变每个节点的prompt内容使其各有侧重**。绝不能把"差异化prompt"理解为"减少节点数"。若对文档意图有任何不确定，必须引用原文段落向用户确认后再执行。反面案例：将"9节点各配独立prompt"误执行为"精简为3节点"，导致6个cron job被误删，需全部恢复。
-1. **设计哲学（2026-06-08 用户纠正）**：本系统的目标不是做量化规则引擎，而是让 LLM 像 UP 一样以交易者思维做出判断。不能为了让系统"更稳定"而走向更多硬编码的量化规则——那会杀死 AI 判断的核心价值。每次修改 cron prompt 或 agent 逻辑时，必须问："这是在增强 LLM 的交易者思考能力，还是在用规则替代它？" 详见 `references/trader-mindset-design-philosophy.md`。
0. **配置 Review 必须覆盖全链路（2026-06-06 用户纠正）**：当用户要求 review 观察池/持仓池/策略配置时，**不能只看 YAML 文件**。必须同时 review：
   - `config/stock_monitor/*.yaml`（watchlist, strategy_pack, positions）
   - `skills/qing-stock-monitor-update/SKILL.md`（更新流程与纪律）
   - `src/qing_investment/stock_monitor.py`（代码消费逻辑）
   - `scripts/scan_all_stocks.py` / `scripts/validate_config.py`（工具链）
   - 相关的 reference 文件（qualitative-fields-spec, entry-points-generation 等）
   **反面案例（2026-06-06）**：Agent 仅读取 YAML 文件做 review，用户纠正："你看过qing stock monitor update skill吗？这里面涉及的脚本和提示词需要一起review的，重新review整个观察池和持仓池架构"。全链路 review 发现 9 个缺陷（5 config + 4 架构），仅看 YAML 只能发现其中 5 个。
1. **Cron 脚本同步纪律**：修改 cron 监控脚本时，`~/.hermes/scripts/` 必须使用 **Wrapper 委托模式**（创建真实文件，内容委托到项目版本），或 `prompt` 字段替代 `script` 字段。~~软链接~~已被 Hermes cron 拒绝（解析 canonical path 后判定为外部路径）。~~硬拷贝~~需手动同步，容易漂移。**Wrapper 模式**同时满足：单一来源（改项目版本即生效）、通过 cron 安全检查、零维护。用户硬性要求："每次改动都需要保证两边一致"。详见 `references/cron-script-sync.md`。
2. **`uv run` 超时陷阱**：cron 环境下 `uv run` 启动慢（检查/创建虚拟环境），可能超过 60s 超时导致任务失败。解决方案：脚本内部优先使用 `.venv/bin/python` 直接运行，fallback 到 `uv run`。项目目录下所有 `hermes_stock_monitor_*.py` 已统一实现该逻辑。
3. **观察池追加，不替换**：新 theme/stock 追加到末尾，旧的不删。
3. **数据源降级**：不可用时不编造数据，标记 degraded。
4. **验证后提交**：每次更新后运行 `--status` 和 `--analysis-context` 确认。
6. **区分轨道**：技术推断只引用 `framework/technical-analysis-framework.md`（轨道B），不混淆市场认知 claims（轨道A）。
7. **持仓更新必须完整**：不能只改股数而忽略 `today_snapshot`、`strategy_summary` 和 `today_plan` 的同步更新。
8. **必须同步更新 strategy_pack**：只更新 watchlist 不更新 strategy_pack 是严重遗漏。entry_points 必须包含具体介入区间、仓位、触发条件。
9. **绝不编造价格**：数据源降级时诚实说明，提供计算规则，不编造虚假价格。
10. **区分两种更新模式**：模式 A（已有票更新）+ 模式 B（UP 新方向提取），两步都完成才算完整。
11. **claims 一致性校验**：更新 strategy_pack 前必须扫描 claims，确认策略不与博主最新纪律矛盾。若 claim 中博主明确说"不追高"/"韭菜行为"，对应标的必须配置为"只观察不介入"。**若用户问"扩大范围"或"还有什么可买"，使用 `scripts/scan_all_stocks.py` 扫描全项目标的**。
12. **sector_rotation_rules 格式**：必须使用 list of dicts，引用 sector_groups 的 id。详见 `references/sector-rotation-rules-format.md`。
13. **主板-only 约束**：用户只能交易主板票（sh6xxxxx / sz0xxxxx），无科创板/创业板权限。**观察池（watchlist）应覆盖全 A 股市场**：UP 提及的非主板标的（688/300/301）也要加入 watchlist，标记 `tradable: false` + `note: "不可交易（科创板/创业板），仅观察学习UP思路"`。只有 `entry_points` 需要过滤主板-only，非主板标的不配介入区间。
   - **非主板标的加入同一 theme，不单独隔离**：如果某方向的核心标的是科创板（如华丰科技688629），应将其与主板同类标的（如航天电器002025）放入同一个 theme（如 `domestic_compute`），标记 `tradable: false` 即可。**不要为不可交易标的单独创建"仅观察"theme**——这会导致板块分析时遗漏该方向的产业链全貌。
   - **反面案例（2026-06-05）**：华丰科技（688629 昇腾核心）若被隔离到单独的"科创板观察"theme，将无法在 `domestic_compute` 的板块轮动计算中被纳入，导致昇腾方向的产业链分析不完整。
14. **技术分析辅助决策**：使用 `scripts/scan_all_stocks.py` 获取实时行情+历史K线+技术分析，辅助判断买入时机。技术分析维度包括：均线系统、支撑压力、回撤幅度、量价关系、K线形态、综合评分。详见 `references/technical-analysis-scan.md`。
14. **技术分析必须执行**：更新 strategy_pack 前必须运行 `scripts/scan_all_stocks.py`，基于均线/回撤/量价/K线形态/支撑压力生成介入区间，不能拍脑袋定价。详见 `references/technical-analysis-scan.md` 和 `references/entry-points-generation.md`。
15. **介入区间必须有数据支撑**：不能写"近期平台附近""等分歧后缩量回踩"等模糊描述，必须提供具体价格数字和计算依据。
16. **触发/失效条件必须具体可执行**：不能写"等企稳""趋势走坏"，必须量化（如"跌破453且30分钟不能收回"）。
17. **用户反馈优先**：复盘报告中的 YAML 建议只是"建议"，用户明确同意后才执行。用户质疑的需讨论实现方案后再执行。详见 `references/daily-review-cases.md` 案例六。
18. **去重机制含同日去重（2026-06-06 增强）**：减仓观察/风控观察类告警在同一天内对同一标的只会触发一次（价格变化 < 2% 时压制），避免"安泰科技一天触发3次减仓观察"的问题。实现：`filter_new_alerts()` 检查 `state.json` 的 `daily_emitted` 字段，`record_emitted_alerts()` 同步写入。若价格变化 > 2% 则突破去重重新提醒。详见 `references/daily-review-cases.md` 案例七。
19. **Claim Schema 字段枚举值陷阱**：`timeframe` 字段枚举值为 `short-term` / `medium-term` / `long-term`（带连字符），不是 `short_term`（下划线）。写错会导致验证失败。
20. **`execute_code` YAML 竞态覆盖陷阱（高危）**：对同一 YAML 文件（watchlist/strategy_pack/positions）的多次修改**必须合并到单个 `execute_code` 调用中完成**。原因：每个 `execute_code` 独立加载文件快照，若调用 A 保存后调用 B 也加载+保存，B 的快照不包含 A 的修改，导致 A 的变更被静默覆盖。**反面案例（2026-06-05）**：分两次 execute_code 分别添加 4 只新标的和更新 narrative → 第二次调用加载的旧快照不包含新增标的，保存后新增标的全部丢失。**正确做法**：一次 execute_code 完成全部 load → modify → save 流程，最后验证文件内容。
21. **代码格式标准化**：`stock_monitor.py` 的 `stock_code_to_secid()` 只接受 `XXXXXX.SZ` / `XXXXXX.SH` 格式（正则 `(\d{6})\.(SZ|SH)`）。**任何时候添加新标的到 watchlist/strategy_pack，code 必须使用此标准格式**。非标准格式如 `sh688381`、`sz002897` 会导致行情拉取静默失败（`stock_code_to_secid` 返回 `None`，该标的被跳过）。**反面案例（2026-06-06）**：watchlist 中 6 个标的用了 `sh######` 格式，其中 3 个在定期行情拉取中被跳过。修复方法：`sh688381 → 688381.SH`，`sz002897 → 002897.SZ`。
22. **entry_points 重复**：同一标的在 `entry_points` 中出现多次，每次更新时容易因追加操作产生重复。重复条目浪费 prompt token 且暗示标的被强调。**每次更新 strategy_pack 后，必须检查 entry_points 去重**：按 `code + name` 组合检测重复，保留最详细的条目。**反面案例（2026-06-06）**：航天电器（002025.SZ）在 entry_points 中出现 3 次，3 条内容几乎相同。
23. **today_snapshot 双写**：`watchlist.yaml` 和 `strategy_pack.yaml` 曾同时包含 `today_snapshot`，内容互不一致（一个说"调整第17天接近尾声"，另一个说"放弃执念"）。**已规定**：`today_snapshot` 只放在 `strategy_pack.yaml` 中，`watchlist.yaml` 不应包含此字段。添加新数据到 watchlist 时不要创建 today_snapshot 块。
24. **hot_score 消费规则**：热度分由 cron 每日 09:00 自动计算（`scripts/calc_hot_scores.py`），不需要手动触发。每次手动更新 watchlist 后，检查 `config/stock_monitor/watchlist_hot_scores.json`：Top 10-15 作为"今日重点关注"写入 strategy_pack 的 today_snapshot；热度分骤变（>3分变化）的标的需优先检查 claims 更新；热度分持续 <3 超过 30 天 → 建议用户将 lifecycle 降级为 archived。
25. **entry_suggestions 检查**：每次手动更新前，检查 `config/stock_monitor/entry_suggestions/` 是否有由 `sync_claims_to_config.py` 生成的待确认文件。如有，优先处理——UP 的操作建议不应积压。确认后写入 strategy_pack，删除建议文件。
26. **add_zone 配置会被条件驱动轮询消费**：`scripts/qing_stock_monitor_poll.py`（cron 每5分钟 no-agent 轮询）会拉行情并检查持仓的 add_zone——配置了 add_zone 的持仓，价格进入区间时会自动推送"加仓观察"提醒。因此 add_zone 必须保持与当前价格的有效距离（太低不会被触发，太高会频繁误报）。每次手动更新持仓后需重新校验 add_zone。
27. **Cron prompt 不直达 qing-agent（架构陷阱）**：9个看盘 cron 通过 HTTP 调用本地 qing-agent，qing-agent 使用自己的 LangGraph system prompt（`prompts/system/market_analyst.txt` 等）。修改 cron job 的 `prompt` 字段对 qing-agent 无效——只影响 fallback 文本路径。**修改 LLM 分析行为 → 改 `market_analyst.txt`；修改 cron 调用参数 → 改 `strategy_pack.yaml` 的 `agent_analysis_schedule`。** 反面案例：Agent 修改 9 个 cron prompt 引用 `cron_*.txt`，但 qing-agent 完全不读 cron prompt。详见 `references/cron-pipeline-architecture.md`（含 Cron 空输出诊断决策树 + 三重对齐检查表）。
    **⚠️ 时间同步子陷阱**：`agent_analysis_schedule` 的 `time` 字段（HH:MM）必须与 cron job 的 `schedule` 分钟数完全一致。差一分钟 → `find_agent_analysis_trigger()` 返回 None → 脚本空输出 → cron 静默跳过。反面案例（2026-06-09）：strategy_pack 尾盘条件单 `time: '14:50'` 但 cron `55 14 * * 1-5`；10:00 cron 存在但 strategy_pack 完全缺失 10:00 条目；10:30 的 ID 从 `morning_confirm` 错写（源码为 `opportunity_scan`）。**三个 cron 同日空输出，根因相同**。修复后验证方法：手动运行 `scripts/hermes_stock_monitor_agent.py` 检查 stdout 是否非空。
    **⚠️ `--daily-review-context` 例外**：15:20（收盘复盘）使用独立路径 `stock_monitor.py --daily-review-context`，**不经过** `find_agent_analysis_trigger()`，不检查 `agent_analysis_schedule`。其空输出原因通常是 DeepSeek API 流式断连（agent.log 出现 "Stream stale for 180s"），而非 schedule 不匹配。两者症状相同（微信没收到），根因完全不同。
    **⚠️ 批量诊断工具**：发现 cron 空输出时，使用三步诊断法：①检查输出文件 >0字节否？②agent.log 搜索 "script produced no output" ③三方对齐表（cron schedule vs strategy_pack.time vs DEFAULT.time）。详见 references/config-cron-alignment-debugging.md。
28. **no-agent cron 超时陷阱（~120s）**：Hermes 对 no-agent cron 有隐式超时（约 120 秒）。超过此时间的脚本会被 kill 并报告 error，即使脚本已部分成功（如 build_sector_mapping.py 已保存缓存但被超时 kill）。防御模式：增量+高频 cron、`save_cache` 参数防止测试破坏生产缓存、HTTP 层重试+退避、`python -u` 非缓冲输出。详见 `references/no-agent-cron-timeout-patterns.md`。
29. **`--max-sectors`/限制参数必须防御缓存破坏**：任何带 `--max-*`/`--limit`/`--dry-run` 的构建类脚本，必须确保这些标志不会触发生产缓存写入。反面案例：`--force --max-sectors 5` 将 4331 条全量缓存覆盖为 242 条。修复模式：底层函数增加 `save_cache: bool = True` 参数，调用端 `save_cache=args.max_sectors is None`。详见 `references/no-agent-cron-timeout-patterns.md` 模式 B。
30. **Qing-Agent /chat 端点K线自动拉取不可靠（2026-06-09）**：Qing-Agent v4 理论支持含代码的消息自动拉取 90 日 K 线，但实测 18 只标的仅 1 只成功（其余静默降级）。**不要依赖此能力**。正确做法：先用腾讯 API 批量拉取（`scripts/batch_kline_analysis.py` 或 execute_code 内联），按回撤分四档（🔥>30%/🟡20-30%/🟠10-20%/🔴<10%），作为结构化文本注入 Qing-Agent message。详见 `references/batch-kline-qing-agent-fallback.md`。
31. **strategy_pack 过期诊断**：配置文件的 updated_at、current_stage、up_quote 日期、关键点位、盘中方向关键词必须与 UP 最新观点一致。过期待征：updated_at > 3天前、关键点位与 UP 矛盾、盘中方向词已从 UP 关注中消失。修复：grep 过期关键词→对比 today_snapshot.up_bias→系统重写 framework/schedule/focus/index_rules/policy。
32. **10jqka 同花顺全A(883657)无公开API（2026-06-09）**：同花顺全A是同花顺客户端私有指数，腾讯/东方财富/同花顺 HTTP API 均返回 404。替代方案：中证全指(000985)，腾讯 API `sh000985` 原生支持，走势高度一致。已注入 stock_monitor.py `MARKET_INDEXES` 和 stock_data.py `fetch_index_quotes`。详见 `references/market-index-config.md`。
33. **微信 iLink 限流导致 cron 推送静默丢失（2026-06-09）**：cron 分析正常执行（status: ok），但 delivery 因 iLink rate limited 静默失败。现象：jobs list 中 `last_delivery_error: "Weixin send failed: iLink sendmessage rate limited"`。不影响分析生成，输出仍可在 `~/.hermes/cron/output/<job_id>/` 读取。当前无已知修复方案（平台限制），但可通过偏移 cron 分钟数减少碰撞：`*/5` → `1-56/5`（:01, :06, :11...），`*/10` → `1-51/10`。B站监控（`*/10`）也是整10分碰撞源。
34. **DeepSeek API 流式断连（2026-06-09 首次观测）**：deepseek-v4-pro API 返回 HTTP 200 但 0 bytes 0 chunks，持续 3×180s 超时后耗尽重试。这不是 key 限流（同一 key 的其他请求正常），是服务端部分推理节点挂死。症状：agent.log 出现 `Stream stale for 180s — no chunks received` + `RemoteProtocolError: peer closed connection without sending complete message body`。区分方法：API 故障 → 有 AI call 但失败；schedule 不匹配 → 根本没有 AI call（`script produced no output`）。修复：等 API 恢复。详见 `references/config-cron-alignment-debugging.md` Step 4。
35. **Qing-Agent 双入口差异（/analyze/trigger vs /chat）**：两个入口架构完全不同。`/analyze/trigger` 走完整 LangGraph 管线，要求调用方提供全部实时数据，market_analyst 节点无数据时硬拒绝。`/chat` 自己拉数据（Qdrant+Neo4j+行情），拉不到就降级，不拒绝分析。盘后配置审查、知识库分析等不需要实时行情的任务，必须用 `/chat` 而非 `/analyze/trigger`。详见 `references/qing-agent-endpoints.md`。

36. **`read_file` 输出污染陷阱（2026-06-09 首次发现）**：`read_file` 工具的默认输出格式包含行号前缀（`     N|`）。若将此输出通过 `write_file` 写回文件，行号前缀会被写入内容导致文件损坏（双列格式）。**安全做法**：在 `execute_code` 中始终用 Python `Path(path).read_text()` 读取原始内容作为修改源，不要依赖 `read_file` 的输出作为回写数据。**修复已损坏文件**：`git checkout -- path` 恢复，或从 git history 提取正确版本。

## 从复盘文档批量更新 narrative 的规范流程

当用户要求"把复盘文档的市场数据、板块涨跌、个股表现提取到 watchlist 对应票的 technical_narrative 和 sector_narrative 中"时，按以下流程执行：

### 前置检查
1. **先 `git pull`**：确保本地 watchlist.yaml 是最新版本，避免基于旧版本修改后产生冲突。
2. **定位复盘文档**：在 `docs/` 或 `sources/raw/财经/` 中找最新复盘文件（命名格式：`收盘监控复盘_YYYY-MM-DD.md` 或 `复盘：YY-MM-DD：...`）。
3. **提取关键数据**：
   - 指数收盘：上证、深证、创业板、科创50的收盘价和涨跌幅
   - 板块表现：各主题（CPU自研链、MLCC、半导体、防御等）的涨跌 summary
   - 个股数据：复盘文档"附：今日关键数据速查"表中的收盘价、涨跌幅、持仓盈亏

### 更新流程
1. **读取 watchlist.yaml 完整内容**（不带 offset/limit），确认目标票在哪些 theme 中出现。
2. **提取 UP "关注方向"（模式 B，极易遗漏）**：
   - 扫描复盘文档中的"关注地位方向""核心思路""方向提示""强势股"等段落
   - 提取 UP 明确提示要关注的标的（即使当前不在 watchlist 中）
   - 用 `grep` 或 Python 检查这些标的是否已在 watchlist 中
   - **若不存在**：新增 theme 或追加到对应 theme，写入完整字段（含 narrative）
   - **若已存在**：更新 narrative，并在 `watch_reason` 中追加 UP 最新提示
   - **示例命令**：`grep -n "关注地位方向\|核心思路\|鼎龙股份\|裕太微" sources/raw/财经/复盘*.md`
3. **更新已有票的 narrative（模式 A）**：
   - 同一票多 theme 处理：若某票出现在多个 theme 中，**每个出现位置都要更新**
   - 无 narrative 的票插入：在 `invalidation_setup` 之后插入新块，注意保留换行
4. **字段内容规范**：
   - `technical_narrative.trend`：必须包含日期和涨跌幅（如"6月1日-2.10%跌破成本"）
   - `technical_narrative.note`：必须包含收盘价、成本线（持仓票）、板块 context
   - `sector_narrative.relative_strength`：必须包含该票在板块内的相对位置（如"CPU链内偏弱""MLCC组最强"）
   - `sector_narrative.risk`：必须包含当日观察到的具体风险（如"组内分化严重，ST得润+5%但万通-2.1%"）
5. **today_snapshot 同步更新（注意：写入 strategy_pack.yaml，不是 watchlist.yaml）**：
   - ⚠️ `today_snapshot` 只存在于 `strategy_pack.yaml`，不要在 watchlist 中创建此字段
   - `date`：更新为当前日期
   - `market_stage`：用复盘文档中的精确指数数据重写
   - `stocks_with_data`：更新为复盘文档中的收盘价和涨跌幅

### 常见格式陷阱
- **换行缺失**：正则替换或字符串拼接时，`invalidation_setup` 最后一行与 `technical_narrative:` 之间缺少 `\n`，导致 YAML 解析为 `None`。修复：插入前检查 `invalidation_setup` 块末尾是否有换行，没有则补一个。批量插入时尤其注意：Python 正则替换的替换字符串必须以 `\n    technical_narrative:` 开头，而非直接拼接在前一行末尾。
- **多位置重复票**：如 `000636.SZ` 既是万通发展又是风华高科（不同 theme），更新时必须通过 `role` 字段区分（`pcie_switch_core` vs `mlcc_mainboard_core`），不能仅按 code 匹配。
- **同一 code 不同 name 的票被误匹配**：仅按 `code` 批量替换时，可能将万通发展的 narrative 错误写到风华高科上。修复：匹配时必须同时检查 `code` + `name` + `role`，用三者组合精确定位。
- **YAML 验证**：每次更新后用 `yaml.safe_load()` 验证文件可解析，确认所有目标票的 narrative 字段不为 `None`。

### 推荐方式：Python 批量更新（优于 Patch）

对于批量更新 narrative（涉及多票、多 theme、同一票多位置），**强烈推荐使用 Python `yaml.safe_load` + `yaml.dump` 而非 patch 工具**。

**原因**：
- Patch 工具对 YAML 缩进敏感，歧义匹配风险高
- 同一票出现在多个 theme 中时，patch 只能替换第一处匹配
- 插入新 narrative 块时，换行缺失会导致 YAML 解析失败

**Python 批量更新模板**：

```python
import yaml
import json

# 1. 加载数据
with open('/tmp/stock_data_YYYYMMDD_HHMM.json') as f:
    stock_data = json.load(f)
stock_dict = {s['code']: s for s in stock_data['stocks']}

# 2. 加载 watchlist
with open('config/stock_monitor/watchlist.yaml') as f:
    watchlist = yaml.safe_load(f)

# 3. 准备复盘数据映射（从复盘文档提取）
review_data = {
    '000636.SZ': {
        'name': '风华高科',  # 用于校验，防止 code-name 错位
        'pct': 8.83,
        'note': '6月2日+8.83%...',
        'sector': 'MLCC组最强...',
        'risk': '普涨共振...',
    },
    # ... 其他票
}

# 4. 遍历更新（自动处理同一票多 theme）
for theme in watchlist.get('themes', []):
    for stock in theme.get('stocks', []):
        code = stock.get('code')
        if code in review_data:
            d = review_data[code]
            # 必须校验 name 匹配，防止错位
            if stock.get('name') == d['name']:
                stock['technical_narrative'] = {
                    'trend': f"6月2日{d['pct']:+.2f}%...",
                    'volume_character': '...',
                    'key_levels': ['支撑：...', '压力：...'],
                    'pattern': '...',
                    'note': d['note']
                }
                stock['sector_narrative'] = {
                    'relative_strength': d['sector'],
                    'money_flow': '...',
                    'leader_follower': '...',
                    'catalyst': '...',
                    'risk': d['risk']
                }

# 5. 同步更新 today_snapshot（写入 strategy_pack.yaml）
with open('config/stock_monitor/strategy_pack.yaml') as f:
    strategy_pack = yaml.safe_load(f)
strategy_pack['today_snapshot'] = {
    'date': '2026-06-02',
    'source': '收盘监控复盘_2026-06-02',
    'market_stage': '...',
    'stocks_with_data': [...],
}

# 6. 保存（保留原有格式和注释会被清除，这是 trade-off）
with open('config/stock_monitor/watchlist.yaml', 'w') as f:
    yaml.dump(watchlist, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

# 7. 验证
yaml.safe_load(open('config/stock_monitor/watchlist.yaml'))
```

**关键校验点**：
- `code + name` 双重匹配，防止同一 code 不同 name 的票被误更新
- 遍历后打印更新计数，确认与预期票数一致
- 同一票在多个 theme 中会自动全部更新（因为遍历的是 theme → stocks 嵌套结构）

**Trade-off**：`yaml.dump` 会清除 YAML 中的注释和自定义格式。如果文件中有重要注释，先用 `git diff` 确认变更范围是否合理。

### 数据已同步的识别与处理
- **症状**：执行更新前发现 watchlist 的 `today_snapshot`、`technical_narrative`、`sector_narrative` 已包含复盘文档中的数据。
- **根因**：用户可能已手动更新，或前一次会话已执行过同步。
- **处理原则**：
  1. 不要重复写入相同数据。
  2. 通过 `yaml.safe_load()` 读取并比对关键字段（`trend`、`note`、`relative_strength`、`market_summary`）确认是否已同步。
  3. 若已同步，向用户报告当前状态（各票 narrative 摘要、today_snapshot 数据点），并询问是否需要基于**今早动态**追加更新（如新增 sector_group、调整 up_mention_status）。
  4. 若部分同步（如 today_snapshot 已更新但某票的 sector_narrative 缺失），仅补全缺失部分。
## 验证清单

- [ ] `git pull` 完成，无冲突
- [ ] **code 格式已标准化**：所有 code 为 `XXXXXX.SZ`/`XXXXXX.SH` 格式
- [ ] **entry_points 已去重**：按 `code + name` 检查无重复
- [ ] **today_snapshot 唯一**：仅在 strategy_pack.yaml 中存在
- [ ] **sector_groups 已同步**：新增主题有对应 sector_group（或已有等价组）
- [ ] **UP "关注方向"已提取**：复盘文档中"关注地位方向""核心思路"等段落的标的已检查并处理
- [ ] 所有复盘文档中提到的票都已更新 narrative
- [ ] 同一票在多个 theme 中的每个位置都已更新
- [ ] 同一 code 不同 name 的票已按 `code+name+role` 区分，无错位
- [ ] `yaml.safe_load()` 验证通过，无解析错误
- [ ] `today_snapshot` 中的市场数据与复盘文档一致
- [ ] `git diff --stat` 确认变更范围合理
- [ ] **数据重复检查**：确认不是对已同步数据的重复写入
- [ ] **用户验证**：提示用户通过 SSH 检查文件，提供具体路径和变更摘要

## 用户交互规范

执行本流程时遵守以下用户偏好：
- **简洁优先**：用户偏好简短回复，不喜欢过度解释。给出变更摘要即可，无需逐步说明每个操作。
- **修改后必须立即汇报验证结果**：完成任何修改链（尤其是多步骤 config/code 修改）后，最后一个动作必须是显式回复用户，说明验证结果和当前状态。**不要静默停顿**——用户会追问\"验证完了吗？你没有回复我消息了\"。反面案例（2026-06-07）：Agent 批量修复 P0-P2 后执行验证但最终不回复，用户追问。
- **"停"信号**：用户说"停"/"stop"/"不要改"/"don't change"时，立即停止当前操作，不完成剩余步骤。
- **先文档后脚本**：当用户同时要求"补充到文档"和"改脚本"时，优先完成文档更新，脚本修复延后。
- **减少逻辑**：用户明确拒绝区分逻辑时（如"不用区分置顶评论和普通评论，只看用户名"），立即按简化方案执行。
- **数据已同步时**：若发现 watchlist 已包含复盘文档数据，不要重复写入。向用户报告当前同步状态，并询问是否需要基于**今早动态**追加更新。
- **账户命名灵活性**：用户可能使用任意账户名称（如"大同账号""华宝账号"而非"账号1""账号2"）。更新 `positions.yaml` 时以用户提供的名称为准，不强制使用固定命名。若用户要求重命名账户，同步更新 `positions.yaml` 中所有引用该账户名的地方（包括 `account` 字段和 `strategy_summary` 中的描述）。
- **LLM 幻觉识别**：当用户指出 cron 任务报告中的数据错误（如"万通发展没有涨停"），按 `references/llm-hallucination-prevention.md` 中的流程处理：验证 state.json/实时行情 → 标记幻觉 → 更新 prompt 约束。
- **持仓更新完整流程**：用户要求"更新持仓"时，执行完整 pipeline：获取实时行情 → 计算 PnL → 交叉引用 claims → 验证 watchlist.yaml → 更新 `positions.yaml` 的 `today_snapshot` + 持仓记录 + `strategy_summary`。不能只改持仓股数而忽略市场上下文和可操作建议。
- **提交前 git status**：执行 `git status --short` 和 `git diff --stat` 确认变更范围，再 `git add -A && git commit && git push`。
- **主板-only 约束提醒**：当用户询问"还有什么推荐"时，主动过滤主板票；若推荐列表中无主板可选，明确说明并询问是否接受非主板标的。
- **脚本路径校验陷阱**：Hermes cron 的 `script` 字段会解析 symlink 的 canonical path。若 `~/.hermes/scripts/` 中的文件是 symlink 且指向项目 repo 外部路径，cron 会报错 `Blocked: script path resolves outside the scripts directory`。修复：删除 symlink，改用 `cp` 硬拷贝，或使用 `prompt` 字段替代 `script` 字段。详见 `references/cron-script-sync.md`。

## 禁止事项

- 不编造价格、财务、新闻或博主观点。
- 不把推断伪装成 UP 原话。
- 不删除旧 theme，除非用户明确说移除。
- 不跳过验证直接提交。
- 不将单日语境直接提升为长期 framework。
- **绝不 `git add -f` force-add gitignored 文件**：`positions.yaml` 等私有文件在 `.gitignore` 中是有意为之。`-f` 会绕过保护将敏感持仓数据推送到公开仓库。反面案例：2026-06-04 会话中 `git add -f config/stock_monitor/positions.yaml` 导致私有持仓数据暴露，需 `git reset --hard` + `git push --force` 清理历史。规则：修改 gitignored 文件后，确认变更留在本地即可，绝不强制提交。
