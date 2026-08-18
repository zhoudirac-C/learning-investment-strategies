---
date: 2026-08-17
type: fix-merged
status: implemented
implemented_at: 2026-08-18
source: evals/shadow/predictions/2026-08-17-pre.json + evals/shadow/predictions/2026-08-17.json + evals/shadow/attributions/2026-08-17.json + sources/original/bilibili/2026-08-17-2214-专栏（UP复盘）
merges:
  - framework/proposals/2026-08-17-pattern-scenario-hard-condition.md
  - framework/proposals/2026-08-17-pattern-patch-note.md
  - framework/proposals/2026-08-17-data-channel-note.md
  - framework/proposals/2026-08-17-data-channel-weekend-catalyst.md
  - framework/proposals/2026-08-17-capability-boundary-note.md
---

# 8-17 盲判 vs UP 复盘：合并修复文档（早盘审计 + 晚间对照）

## 背景

2026-08-17 两轮盲判与 UP 两侧输出对照：

| 轮次 | 盲判结论 | UP 对应输出 | 结果 |
|---|---|---|---|
| 盘前盲判（-pre.json） | 震荡/缩量企稳 | UP 早盘 09:04 | 方向命中（5G/存储），过程层四类缺口（见归因 json） |
| 晚间盲判（2026-08-17.json） | 主升/放量攻击 | UP 22:14 复盘专栏 | 定性错误：UP 判「反弹修复段第一根普涨中阳，非趋势加速」 |

本文档把早盘过程审计的 5 份提案与晚间复盘对照的新发现合并为一份修复清单，原提案保留作溯源，处置以本文为准。

## 一、晚间对照的核心分歧

同一根中阳，两种读法：

- **盲判**：成交额 23874 亿环比放大 + 涨停 106 家 + 封板率 89.8% → 「放量攻击、主升」；但 operation 又写「反弹超预期、获利了结降仓位」——结论与操作建议自相矛盾。
- **UP**：性质是**换手（消费→科技调仓）而非增量资金**，带逼空性质；位置上是**反弹修复段第一根普涨中阳**，右侧确认标准应放在「补缺回踩之后能否量价配合」，而非当天。

关键细节：盲判自己抓到了「盘中预估 43772 亿 vs 实际 23875 亿」的冲量滑落形态，却仍输出「放量攻击」——证据与结论脱节，属推理纪律问题而非数据缺。

## 二、修复项清单

### A. 推理规则 / 模式修补

- **A1 情景硬阈值只挂结构信号**（并入自 `pattern-scenario-hard-condition`，保持其窗口验证轨道）
  量能只写方向性要求；点位阈值仅保留结构位；每个情景须声明单一承重墙变量（key）。
- **A2 冲量滑落形态识别规则**（并入自 `pattern-patch-note`）
  盘中预估量能与实际量能出现大幅落差、尾盘缩量的，不得判「放量攻击」；需结合分时量能确认。
- **A3 量能源头判断（换手 vs 增量）**（晚间新增）
  判放量性质时必须回答「量从哪来」：存量调仓（板块间换手）与增量入场的持续性含义不同。
  UP 原话：「涨幅是结果，换手的方向才是这根中阳真正的信息量」。
- **A4 位置决定意义**（晚间新增）
  中阳/大阳定性前先定位置（反弹修复段 vs 趋势加速段）；修复段的右侧确认点放在补缺回踩之后，不以当日量价齐升直接判主升。
- **A5 量能分档采用相对口径 + UP 刻度参照**（晚间新增）
  盲判自拍的绝对阈值（24000/22000 亿）与 UP 框架（2.5 万亿放量确认位、3 万亿以上警惕过热）错位；统一改为「守住前日量级 / 温和放大 / 越过确认位」的相对表述，绝对刻度以方法论框架内的分档为准。
- **A6 两路资金分层**（晚间新增）
  机构口径与游资口径分开看：普涨下机构净卖出多于净买入、买入集中在 CPO/先进封装，可解释「高低切明显但高位无亏钱效应」。情绪指标不得合并笼统使用。
- **A7 断板性质区分**（晚间新增）
  主动换龙（资金内生性轮动）不杀情绪；停牌/监管等外力断板才会打断梯队。情绪票的关键变量在断板性质而非业绩。
- **A8 晋级率折算**（晚间新增）
  首板家数 × 约 15% 晋级率折算次日二板健康区间，纳入连板梯队跟踪变量。

### B. Prompt 纪律约束

- **B1 证据-结论一致性硬约束**（晚间新增，与 A2 互补）
  盘中预估与实际量能偏差超过阈值（建议 ±30%）时，禁止输出「放量攻击」类结论；
  更一般地：stage_reason 中引用的每条证据不得与 market_stage/nature 结论冲突，冲突时必须改写结论。
- **B2 规则执行自检**（并入自归因「规则未遵守」项）
  prompt v5 规则 7（rebound_day ≥ 理论窗口 → position 优先判「反弹超预期」）在 8-17 盘前未被执行（8-14 执行正确，属执行回归）。
  处置：输出前自检 cycle_state 与 operation.position 的一致性；operation 与 market_stage 结论不得互相矛盾（本轮「主升+获利了结」即违反）。

### C. 数据通道

- **C1 板块资金流 + 分时量能**（并入自 `data-channel-note`）
  接入主力净流入/板块资金流与分时成交数据，用于验证量能真实性与资金持续性。
- **C2 周末/节假日催化通道**（并入自 `data-channel-weekend-catalyst`，细节以原文为准）
  `build_daily_pack` 扫描 `prev_trading_day..target_day` 区间新闻；fetch 侧确认 KPL 周末可得性；防泄漏边界不变（UP 言论类内容不得入盲判包）。
- **C3 机构席位 / 龙虎榜净买卖数据**（晚间新增）
  UP 精确到「兴森科技机构净买入 2.6 亿居两市首位、净买卖超千万个股 26 只（买 11 / 卖 15）」，是 A6 两路资金分层判断的直接证据。需调研东财/同花顺龙虎榜接口可得性。
- **C4 板块间资金迁移（换手方向）**（晚间新增）
  行业/概念级净流入流出对照（如消费净流出 vs 科技净流入），是 A3 量能源头判断的前提；与 C1 同族，可合并调研。
- **C5 连板梯队明细 + 断板原因**（晚间新增）
  limit_pool 已具备涨停/跌停/连板梯队（见 A1 提案「配套数据通道」），但盲判实际只用了涨停家数、封板率两个汇总值；需确认梯队明细（首板数、高度板名单、断板原因标注）是否进了盘前/盘后数据包，没进则补。
- **C6 个股公告 / 调研纪要 / 卖方研报时效通道**（晚间新增）
  UP 个股论证全部基于公告、投资者关系记录、券商研报（太辰光 CPO 试制、德福科技载体铜箔验证、欧陆通谷歌项目）；盲判方向理由仍停在「昨日涨幅 + 隔夜美股映射」。评估接入公告/研报摘要源的可行性与防泄漏边界。
- **C7 另类事件数据**（晚间新增，仅备案）
  莱茵河水位→科思创不可抗力→维生素涨价（圣达生物）一类跨市场事件链，现有通道接不住；本期只备案，不开通道。
- **C8 非公开信息边界标注**（并入自 `capability-boundary-note`）
  依赖非公开信息（如板块资金流）的结论须显式标注；数据缺失时降低置信度并提示信息差风险。C1/C3/C4 未落地前，相关判断一律按此降级处理。

## 三、溯源映射

| 修复项 | 来源 |
|---|---|
| A1 | 早盘提案 pattern-scenario-hard-condition（保持窗口验证） |
| A2 | 早盘提案 pattern-patch-note |
| A3–A8 | 晚间盲判 vs UP 复盘对照（本文新增） |
| B1 | 晚间新增；B2 早盘归因「规则未遵守」项 |
| C1 | 早盘提案 data-channel-note |
| C2 | 早盘提案 data-channel-weekend-catalyst |
| C3–C7 | 晚间新增 |
| C8 | 早盘提案 capability-boundary-note |

## 四、处置优先级建议

1. **B1 + B2（prompt 纪律）**：无数据依赖，可立即改，直接堵本轮两处自相矛盾。
2. **A2/A3/A4（形态与位置定性规则）**：无数据依赖，方法论补丁，随 B 组一起落。
3. **A1**：维持既有窗口验证轨道（≥4 周跨 regime 命中后转正）。
4. **C5**：先确认现有 limit_pool 梯队明细是否已入包——大概率只是接线问题，成本最低。
5. **C1/C3/C4**：数据接口调研后分批接；未落地前按 C8 降级。
6. **C2**：按原提案三步走。
7. **C6/C7**：本期备案。

## 五、落地执行方案（2026-08-17 接口调研已实测）

调研结论先行：**C5/C6 的前提已过时**——梯队明细和公告/研报都已在本地落盘，缺的不是通道而是接线；C1/C3/C4 所需接口 akshare 已装且实测可用（部分接口被东财拒连，有替代）。以下按执行顺序分四批。

### 接口调研结论（2026-08-17 实测，akshare 1.18.64 已装）

| 需求 | 接口 | 实测状态 |
|---|---|---|
| 行业资金流（C1/C4） | `ak.stock_fund_flow_industry(symbol="即时"/"3日排行"/"5日排行"/"10日排行")` | ✅ 90 行业，字段含流入/流出/净额/领涨股 |
| 概念资金流（C1/C4） | `ak.stock_fund_flow_concept(symbol="即时"/...)` | ✅ 387 概念，同构字段 |
| ~~`stock_sector_fund_flow_rank`~~ / ~~`stock_main_fund_flow`~~ | 备选 | ❌ 本机被东财拒连（RemoteDisconnected），用上行两个替代 |
| 机构席位汇总（C3） | `ak.stock_lhb_jgmmtj_em(start_date, end_date)` | ✅ 买方/卖方机构数、机构净买额、占成交比 |
| 逐股席位明细（C3） | 现有 `src/investment_engine/eastmoney_lhb.py`（datacenter 日榜+逐股前 5 席位） | ✅ 已在跑，含「机构专用」席位 |
| 昨日涨停今日表现（C5 断板） | `ak.stock_zt_pool_previous_em(date)` | ✅ 直接给昨板今日涨跌幅，断板/亏钱效应免join |
| 强势股池（C5 辅助） | `ak.stock_zt_pool_strong_em(date)` | ✅ |
| 涨停/炸板池 | 现有 push2ex（`src/investment_engine/limit_pool.py:26`） | ✅ 已在跑，比 akshare 同族接口更稳，不换 |
| 分钟分时（C1） | TDX pytdx（`qing_investment.tdx_market`，现成封装）；东财 trends2（`agent/tools/stock_data.py:396`） | ✅ 两条腿现成；`ak.index_zh_a_hist_min_em` ❌ 被拒连 |
| 公告（C6） | `ak.stock_notice_report`（`research_feed.py:118` 已在用） | ✅ 已在跑，**周末也拉** |
| 研报（C6） | 东财 reportapi（`research_feed.py:24` 已在用） | ✅ 已在跑，含周末 |
| KPL 周末资讯（C2） | `kpl/news.py` | 未验证，需周末实测一次 |

断板原因无现成 API，**可推导**：昨日连板名单（limit_pool `zt_items` lbc≥2 或 `stock_zt_pool_previous_em`）∩ 今日涨停池差集 = 断板名单；当日无成交/停牌 → 外力断板；有成交未封 → 主动断板（换龙候选）；KPL 新闻全文 grep「股票名+监管/停牌/核查」佐证。

### 批次 P0：prompt 纪律（B1/B2 + A2/A3/A4/A5，无数据依赖，1 天内可落）

落点：`src/investment_engine/shadow/premarket.py`（规则列表 :43-60）与 `daily.py`（盘后同构），prompt_version v5→v6。

- B1：新增硬约束——盘中预估 vs 实际量能偏差 >±30% 禁判「放量攻击」；`stage_reason` 引用证据不得与 `market_stage/nature` 冲突。
- B2：输出自检——`operation.position` 与 `market_stage` 不得矛盾；规则 7（rebound_day ≥ 窗口 → 「反弹超预期」优先）列自检项，堵 8-17 执行回归。
- A2：`intraday_amount` 块「形态」字段（`dataset.py:445-450` 已算好冲量滑落/逐级放大/平量）为冲量滑落时禁判放量攻击。
- A3/A4/A5：量能源头（换手 vs 增量）、位置决定意义（修复段右侧确认在补缺回踩后）、量能相对口径（守住前日量级/温和放大/越过确认位，删自拍绝对阈值）写成 prompt 规则；同步补 `framework/reasoning-patterns.yaml` 与 `up-glossary.md`。

### 批次 P1：接线修复（C5/C6/C2 前段 + 顺手修断链，1-2 天）

- **C6**：`build_daily_pack`（`blindtest/dataset.py:545`）加 `research` 块：读 `infra/data/research/{notices,reports}/{day}.json`，标题+个股摘要封顶入包，过 `assert_no_leakage`。**成本最低，先做。**
- **C5**：梯队明细（ladder/compare/promotion_rate/regulatory_distance/zt_items/zb_items）**已在包内**（`dataset.py:293-309`）——真正缺口是 prompt 未强制引用 + 无断板原因。处置：prompt 加「连板梯队分析必须引用 ladder 与 promotion_rate」；`limit_pool_fetch.py` 增断板推导（上节方案）；评估 `_LP_ITEM_CAP=20`（`dataset.py:34`）是否上调。
- **C2 前段**：pack 加 `catalysts_since_prev_day`，扫描 prev_trading_day..target_day 的 notices/reports/KPL news（周末已由 research_feed 覆盖）；KPL 周末可拉性留一行验证脚本下周末实测。
- **顺手修断链**：`infra/data/intraday_changes/` 目录不存在，数据包 `missing` 恒含 intraday_changes——补齐拉取链路或从块清单摘除。
- **C8**：prompt 加「`missing` 块对应判断须降级置信度并标注信息差」规则（`attribute.py:19` KNOWN_DATA_GAPS 已登记缺口）。

### 批次 P2：新数据通道（C1/C3/C4，2-3 天）

照「模块在 src/investment_engine/ + 薄入口 scripts/ + infra/data/ 落盘」既有范式：

- **C1/C4**：新建 `src/investment_engine/fund_flow.py` + `scripts/fund_flow_fetch.py`（cron 15:40 前后，与 limit_pool 同窗口）：`stock_fund_flow_industry` + `stock_fund_flow_concept`，即时/3日/5日/10日四窗口 → `infra/data/fund_flow/{day}.json`。多窗口即回答「换手方向+持续性」。
- **C3**：`eastmoney_lhb_fetch.py` 扩展加 `stock_lhb_jgmmtj_em` → 落盘文件加 `jgmmtj` 节（机构汇总口径，与既有逐股席位互补）。
- **分时量能落盘**：cron 15:35 用 TDX 60min 算当日四点曲线存 `infra/data/intraday_amount/{day}.json`；`dataset.py:412 _load_intraday_amount` 改优先读盘（当前打包时实时拉，历史回放拿不到）。
- `dataset.py` 接入新块 + `missing` 登记；**pyproject.toml 补 akshare 依赖声明**（已装未声明）。
- 注意 `src/qing_investment/agent/AGENTS.md` §6：若同步给监控侧加板块资金流，须插 `sector_data.py` 的 `_PROVIDER_CHAIN`，数据不可用时报错而非编造。

### 批次 P3：方法论沉淀与验证（随窗口走）

- A1 维持原窗口验证轨道；A6/A7/A8（两路资金分层/断板性质/晋级率折算）落 `reasoning-patterns.yaml`，其中晋级率折算的 `promotion_rate` 字段已在包内，仅需 prompt 引用。
- C7 另类事件链维持备案。
- v6 prompt 上线后跑 shadow 双轨，归因侧看「规则未遵守」类缺陷是否清零。

## 六、实施记录（2026-08-18 全部落地）

### P0 prompt v6（B1/B2 + A2/A3/A4/A5 + C5 引用 + C8 降级）

- `src/investment_engine/blindtest/replay.py`：`PROMPT_VERSION` v5→v6，`SYSTEM_PROMPT`（盘后，predict/replay 共用）追加规则 10-16。
- `src/investment_engine/shadow/premarket.py`：盘前 prompt 追加同编号规则 10-16（盘前语境适配）；`missing` 块纳入盘前 prompt 正文（规则 11(c)/C8 依赖）。

### P1 接线（C5/C6/C2/C8）

- `dataset.py` 新增 `_load_research`（公告/研报入包，各封顶 30）、`_load_catalysts`（`target_day` 区间催化扫描，封顶 60，**离目标日最近日期优先填充**，展示恢复时间正序）；`_load_limit_pool` 透传 `broken_boards`；`pack_to_prompt` 全量 dump 新块自动可见。
- 断链修复：`infra/data/intraday_changes/` 补齐（脚本本身正常，根因是本机 cron 未注册，见下「待办」）。
- `attribute.py` `KNOWN_DATA_GAPS` 置空（三通道已落地，历史归因记录引用旧标签属当时事实）。

### P2 新通道（C1/C3/C4 + 分时落盘）

| 通道 | 模块 / 脚本 | 落盘 | 接口 |
|---|---|---|---|
| 板块资金流（C1/C4） | `investment_engine/fund_flow.py` / `scripts/fund_flow_fetch.py` | `infra/data/fund_flow/{yyyymmdd}.json` | akshare `stock_fund_flow_industry/concept` 四窗口（即时/3/5/10日） |
| 分时量能落盘（C1） | `investment_engine/intraday_amount.py` / `scripts/intraday_amount_fetch.py` | `infra/data/intraday_amount/{yyyymmdd}.json` | TDX 60min（dataset 改读盘优先、实时回退+日期守卫） |
| 机构席位（C3） | `eastmoney_lhb.py` 增 `fetch_jgmmtj` | lhb 日文件加 `jgmmtj` 键 | akshare `stock_lhb_jgmmtj_em` |
| 断板推导（C5） | `limit_pool.py` 增 `compute_broken_boards` | limit_pool 日文件加 `broken_boards` 键 | akshare `stock_zt_pool_previous_em` + 炸板池对照 |
| KPL 周末验证 | `scripts/kpl_weekend_check.py` | — | 手动工具，下周末实测 |

- `pyproject.toml` 补声明 `akshare>=1.18`。
- 8-17 真实数据验证：jgmmtj 兴森科技机构净买 2.61 亿居首（与 UP 口径吻合）；断板 6 只分类完整（11 连板 = 晋级 5 + 断板 6）；intraday_amount 复现 43772→23875 冲量滑落。

### P3 方法论沉淀

- `framework/reasoning-patterns.yaml` 11→17 条：`volume_surge_fade`(A2) / `volume_source_qualify`(A3) / `position_context_qualify`(A4) / `fund_flow_segmentation`(A6) / `board_break_nature`(A7) / `promotion_rate_benchmark`(A8)，validation 均为 pending-m1 待窗口验证。
- `framework/up-glossary.md` +5 条（换手/右侧确认/冲量滑落/主动换龙/两路资金；来源日期用中文写法规避盲判包日期断言，语义泄漏未消除，如需更严可在 `_load_glossary` 加日期行过滤）。

### 测试

- 新增/扩展：test_premarket(+5)、test_daily(+2)、test_dataset(+20)、test_limit_pool(+7)、test_eastmoney_lhb(+4)、test_fund_flow(+4)、test_intraday_amount(+6)、test_premarket 数据块(+3)、test_attribute 同步。
- `tests/investment_engine` 全量 323 passed；`test_hermes_agent_data_blocks` 7 passed 无连带破坏。

### 待办（运维侧，代码已就绪）

1. **cron 注册**（本机未配，建议）：
   - `scripts/fund_flow_fetch.py` 工作日 15:40（板块资金流，仅当日快照无回溯）
   - `scripts/intraday_amount_fetch.py` 工作日 15:35（收盘后分时量能落盘）
   - `scripts/intraday_changes_fetch.py` 已建议 15:40 但本机 cron 未注册，需补
   - `scripts/eastmoney_lhb_fetch.py`、`scripts/fetch_research_reports.py`、`scripts/limit_pool_fetch.py` 确认在册
2. **KPL 周末可拉性**：下周末手动跑 `.venv/bin/python scripts/kpl_weekend_check.py`（周中冒烟无法回答，news 接口是单窗口最新页）。
3. **prompt 体积**：盘后包 136.5K→149.5K 字符（约 64K tokens），后续加块需考虑二次压缩。
4. A1 维持原窗口验证轨道；17 条模式库条目随 shadow 双轨跑命中率，pending-m1 转正标准不变。
