# 盲判 vs UP 差距分析框架（2026-08-13 首测）

用户会周期性要求「对比 UP 早盘/复盘 与 影子盲判，找推理差异、可学习点、缺的数据源」。
这是 recurring 任务类型，输出应结构化（结论前置 + 分点 + 区分事实/推断）。

## 固定分析结构（照此输出）

1. **核心结论**（3-5 条，点出「同向不同因」「缺了哪层推理」）
2. **方向/维度对比表**（盲判 vs UP vs 差异根因）
3. **推理思路差异**（逐条列出结构性差距，每条给「UP 怎么推 / 盲判缺什么」）
4. **可学习点**（按优先级，可落地到盲判系统的改进）
5. **欠缺数据源**（分 🔴致命 / 🟠重要 / 🟡次要，标注「缺因」：凭证缺 / 目录缺 / 时序早）
6. **顺带发现的 bug**（若有）

## 已确认的盲判系统结构性短板（首测结论，可复用）

### 7 处推理思路差异（盲判缺、UP 有）

1. **外盘映射层**（最关键）：UP 起点=「隔夜外盘→A股结构性映射 vs 系统性转向，只反映开盘定价」。
   盲判无此层 → 只能追昨日 A 股动量，方向「同向不同因」。
2. **以点带面层级**：UP 定位「存储=点(导火索)、光模块/CPO=面」，判断「点稳则面可控」。
   盲判方向池是并列的，无「导火索→扩散面」因果层级。
3. **可证伪精确量能阈值**：UP 用「半日(11:30)成交 1.45 万亿」当天可验证；
   盲判阈值模糊且口径错（把成交量当成交额，见下 bug）。
4. **情绪二维结构（宽度×高度）**：UP「宽度极好(跌停0)×高度受限(无主线)→轮动型健康而非主升型健康」
   +「首板×15%晋级率→今日二板家数」推演。盲判只有 sentiment_cycle 单维 + 炸板率。
5. **大金融托底判断**：UP 专设「缺大金融托底指数难突破，横盘用时间换空间」。
   盲判方向池有 broker_finance 但框架没引导判断「金融是否托底」。
6. **资金腾挪因果链**：UP「缩量→资金抬不动两条高成交线→退向低价低成交方向(地产)→持续性取决于量能」。
   盲判只有「量能不足难主升」粗结论，无「量能→资金行为→板块选择」链。
7. **price in 时间分段**：UP 用 Coherent 盘后超预期反跌提炼「业绩兑现期 price in 比业绩本身重要」。
   盲判无「业绩兑现期 vs 预期交易期」概念。

### 欠缺数据源（含缺因）

| 数据源 | 缺因 | 影响 |
|--------|------|------|
| 隔夜外盘 overnight_us | 时序：手动跑太早(02:34)早于 08:20 外盘 cron → `meta.overnight_date=None` | 🔴 UP 整篇起点 |
| 情绪 kpl_emotion（涨停/跌停/炸板/首板/晋级/连板梯队） | ~~无 KPL 凭证~~ **已配置（2026-08-13 用户提供 kpl_user_id/token/device_id）** | 🔴 只剩炸板率 → 已修复 |
| 新闻标题 kpl_news_titles | 同上已配置，但 KPL 资讯当日只有 3 篇（覆盖有限） | 🟠 丢催化(腾讯资本开支/规划/IPO/管制) |
| 龙虎榜 kpl_lhb | 已配置，但 GetDay 不返回席位明细（entry_count=0） | 🟠 丢机构游资动向 |
| 涨停池 limit_pool | `infra/data/limit_pool` 无当日数据（东财源，非 KPL） | 🟠 丢连板高度 |
| 盘中变化 intraday_changes | `infra/data/intraday_changes` 无当日数据 | 🟡 丢盘中轮动节奏 |

**注意**：skill 主文曾写「shadow 15:40 早于 KPL 15:45」的时序说——这已不准确，
实际根因是**云端无 KPL 凭证、`infra/data/kpl` 目录根本不存在**（非时序）。
2026-08-13 起 KPL 凭证已配好（见下「KPL 凭证配置」），情绪/新闻/龙虎榜三块已能拉到。

### 量能口径 bug：真相与修复（2026-08-13 定案，纠正早期错误结论）

早期结论「`get_index_daily` 漏查 amount」是**错的**。实测：`index_klines` 表虽有 `amount`
字段，但**腾讯指数接口不提供成交额，amount 恒为 0.0**——加查 amount 是无效修复。

**真相**：腾讯指数 K 线只有成交量(volume，单位手)，没有成交额。UP 全程用的「两市成交额」
（如「21524 亿」）来自 **KPL 情绪快照的 `daban.q_zrtj`**（单位万元，`q_zrtj=215242310` 万
= 21524.2 亿，精确对上 UP 口径）。沪市是 `daban.s_zrtj`。

**已落地修复**（`src/investment_engine/blindtest/dataset.py`）：
1. `_load_emotion` 把 KPL 拼音字段语义化为中文键名，含 `两市成交额_亿`（`q_zrtj/10000`）、
   `沪市成交额_亿`（`s_zrtj/10000`）、`昨日涨停`(lZhangTing)/`今日涨停`(tZhangTing)/`封板率_pct`/
   `跌停`/`上涨家数`/`下跌家数`/`炸板家数`/`昨日涨停今收益_pct`/`昨日连板今收益_pct`。
2. `_compact_bars` 键名 `vol万手` → `成交量万手`（防 LLM 把成交量误读成成交额）。

**2026-08-14 二次纠正：`q_zrtj` 是「昨日」成交额，`qscln` 才是「当日」**（上面「真相」说的
q_zrtj=两市成交额是首测结论，不完整）：
- `daban.q_zrtj` 的 `zr`（拼音「昨日」）= **昨日**成交额（08-13 收盘后拉到 21524 亿 = 08-12 的）。
- `daban.qscln` 才是**当日**成交额（08-13 = 25509.2 亿 ≈ UP 说的「2.5万亿」）。
- 已修复：`两市成交额_亿` 改用 `qscln`，新增 `昨日两市成交额_亿` = `q_zrtj` 供环比放量判断。
- 校验口诀：用 UP 复盘原文对齐——UP 说「今日 2.5万亿」应匹配 qscln，「昨日 21524亿」应匹配 q_zrtj。

KPL 字段语义对照（`docs/design/kpl-api-inventory.md`）：`tZhangTing`=今日涨停、`lZhangTing`=昨涨停、
`tFengBan`=封板率、`tDieTing`=跌停、`SZJS/XDJS`=上涨/下跌家数、`PPJS`=炸板、`ZRZTJ/ZRLBJ`=昨涨停/连板今收益。

## 外盘数据源路由（2026-08-13 定案）

东财 `push2`/`push2his` 对云服务器(腾讯云)IP 段做反爬，TCP 层直接断连；Sakuracat(mihomo 127.0.0.1:7890)
代理出口 IP 也是腾讯云 → 走代理无效。**美股行情改用腾讯 `qt.gtimg.cn`**（`q=usNVDA,usAAPL,...`，GBK 编码），
13 只映射股全覆盖。字段：`[3]现价 [4]昨收 [32]涨跌幅%`。代码见 `src/investment_engine/overnight_us.py`。

## 盲判数据包实际构成（build_daily_pack）

包含：`index`(5指数60根K线，键 `d/c/pct/vol万手`)、`stocks`(code/name/direction/close/pct/turnover/pos20)、
`directions`(方向池，键是 `id` 不是 `direction_id`)、`chains`、`glossary`、`patterns`、`core_patterns`。
缺失时进 `pack["missing"]` 列表（`kpl_emotion`/`kpl_news_titles`/`kpl_lhb`/`limit_pool`/`intraday_changes`）。

⚠️ 调试坑：`_compact_bars` 输出的指数 K 线键名是**缩写** `d`/`c`/`pct`/`成交量万手`，
不是 `date`/`close`——打印时用错键名会看到全 None，误判「数据缺失」。

## KPL 凭证配置（2026-08-13 起）

`KplClient.from_env()`（`src/investment_engine/kpl/client.py`）读 `.env` 里的
`kpl_user_id`/`kpl_token`/`kpl_device_id`（大小写均可）。`.env` 用 `KEY=value` 格式，追加：

```
kpl_user_id=<用户ID>
kpl_token=<token>
kpl_device_id=<device_id>
```

拉取入口 `scripts/kpl_daily_fetch.py`（cron 17:45）：`--date` 指定日，`--force` 覆盖，
`--skip-emotion/--skip-news/--skip-lhb` 跳块。落盘 `infra/data/kpl/{emotion,news,lhb}/<day>.json`。
跑前必须 `set -a && source .env && set +a`。

## FORBIDDEN_RE 打码坑（盲测 prompt 泄漏拦截）

`assert_no_leakage` 的 `FORBIDDEN_RE = UP|青枫浦|博主` 会拦截 prompt 里的来源指称。
`build_daily_pack` 已对 directions 的 name、glossary 打码，但**早盘盲判额外注入的
`overnight_us` 数据没打码**，会触发 `LeakageError: prompt 含来源指称 'UP'`。

来源在两处：`us_map.yaml` 的 **theme.name**（如「存储（UP 用 SK海力士ADR映射…）」）和
**stocks[].earnings_note**（如「美东8/12盘后财报（2026-08-11 UP早盘记录）」）。

**修复**（`src/investment_engine/shadow/premarket.py` `_pack_to_premarket_prompt`）：
注入 overnight_us 时对 theme.name 和 earnings_note 都做 `FORBIDDEN_RE.sub("██", ...)` 打码。
以后往盲测 prompt 新增数据块，务必先跑一遍 `assert_no_leakage`，若报来源指称，检查新块每个
字符串字段是否含「UP/青枫浦/博主」。

## 早盘盲判的幂等跳过（正常行为，非 bug）

`run_predict_premarket` 里若 `{day}-pre.json` 已存在且 `status` 非 `error`/`None` → 返回
`{"status":"skipped"}`。这是防重复调 DeepSeek 的幂等保护。若某天早盘被手动跑过（尤其凌晨跑、
缺隔夜外盘），cron 到点会 skipped——需手动 `rm` 掉旧文件重跑才能带上完整数据。

## 盲判数据缺失三连根因（2026-08-14 排查定案，可复用）

用户要求「对比盲判 vs UP、找可优化点」时，**先跑 `build_daily_pack(day)` 看数据包实际缺什么，
别只看盲判 JSON 表象**。三连根因都能让盲判 `directions` 全空 / 量能口径错乱：

1. **`is_cache_ready` 误拦收盘后补拉**（最隐蔽）：`pre_fetch_klines.py` 早盘 08:30 `mark_cache_ready`
   后，收盘后 15:35 补拉被 `is_cache_ready(day)` 幂等检查跳过 → stock_pool 个股 K 线停在 T-1 →
   `build_daily_pack` 里 `bars[-1]["date"] != day` 过滤掉全部 stock_pool → `stocks=0` → `directions=0`。
   修复：`pre_fetch_klines.py` 收盘后窗口(post_close_window)跳过 ready 检查，强制补拉覆盖收盘价。

2. **KPL 情绪数据无 cron 自动拉取**：`kpl_daily_fetch.py` 从未挂 cron（`infra/data/kpl/emotion/`
   只有手动拉的那一份）→ 情绪/成交额缺失 → LLM 只能读「成交量万手」→ 误读成成交额。
   修复：挂 cron（17:45 工作日）+ wrapper `~/.hermes/scripts/qing_kpl_daily_fetch.py`（读 .env 注入 kpl 凭证，显式 CST 当天）。

3. **`q_zrtj` 是昨日、`qscln` 才是当日**（字段映射错误）：见上「量能口径 bug」二次纠正。

**诊断口诀**：`build_daily_pack` 返回的 `missing` 列出缺的数据块；`stocks=0 且 directions=0`
基本是 K 线停在 T-1（根因 1）；`emotion=None` 是 KPL 没拉（根因 2）。补拉顺序：先 KPL
（`kpl_daily_fetch.py --date <day> --force`），再 K 线（`FORCE_KLINE_FETCH=1 pre_fetch_klines.py`），
最后 `rm` 旧盲判 JSON 重跑 `shadow_daily.py --date <day>`。

## 盲判 vs UP 多天连续对比（用户强调「分析不能只看一天」）

盲判每天独立「震荡」二分、无状态记忆；UP 是连续叙事（「7/31 预判反弹 6-8 天 → 8/13 第 9 天超预期
→ 获利了结」）。对比时至少串 3 天盲判，重点看三处断裂：
1. **量能口径是否多天一致**（实测四天四种口径：209.7亿 / 18493.9万手 / 21524亿 / 21550万手 =
   数据缺失铁证，别只看单日）。
2. **directions 是否每天换一批且无连续性**（UP 会跟踪方向加强/退潮，盲判方向池并列无因果）。
3. **有无「天数/周期/兑现时点」维度**（UP 有「第 9 天」「晚两天」，盲判只有静态二选一 scenario）。

## 08-14 二次对比：外盘映射打通后的新缺口 + 改造三类法

首测（08-13）的 7 处差距，08-14 复查时部分已收敛：
- ✅ 外盘映射层已打通且准确：08-14-pre 正确读出 Coherent -7.99%→光模块承压、美光+4.23%→存储、
  英伟达/博通微涨→算力平稳，「方向同向不同因」在方向层已收敛。
- ✅ 量能口径已修复（qscln 当日 25509 亿 vs q_zrtj 昨日 21524 亿，字段映射对）。

暴露一个更深的新缺口——**量能「形态」判断（放量 vs 缩量）**，这是首测「量能口径 bug」没覆盖的下一层：
- 盲判 stage_reason 写「成交额 25509 亿较前日放量 18.5% → 放量阴线=主动换手」；
- UP 原文「预估成交额从开盘近 3 万亿滑落到 2.5 万亿，看似放量实则全天逐渐缩量」。
- 同一组数据，盲判判「放量换手（健康）」，UP 判「缩量衰竭（承接不足）」，**论据反了、结论碰巧都落在「震荡」**。
- 根因：盲判只有收盘成交额单点（qscln/q_zrtj 环比），没有「盘中分时量能曲线」（开盘预估→逐级变化）。

同理的情绪/方向缺口：盲判用「涨停总数+封板率」单维，UP 用「首板38/二板12/晋级率16%/跌停个位数」四维
并推演「首板×15%晋级率→今日二板健康值5-6家、观察点是首板能否回补60家」；方向无「国产链>海外链」排序
与「定价权在海外」标签；无大金融「托而不举」判断；无操作纪律层（买阴不买阳/做T压成本/周末敞口收缩）。

### 改造三类法（把差距转成改动力，recurring 套路）

差距按「成本/数据依赖」分三类，优先级 P0→P2：

| 类 | 定义 | 例子 |
|----|------|------|
| A 改 prompt/pattern 就能教 | 思路缺失非数据缺失，零新数据 | 操作纪律层、方向强弱排序、大金融托而不举 |
| B 必须补数据源 | 代码/脚本已存在但没数据 | 连板梯队（limit_pool）、盘中分时量能 |
| C 纯 bug | 口径/单位/字段错 | watch_next 单位错、scenarios 阈值错、erban 丢弃 |

**关键工程事实（08-14 核实，部分已落地；做改造前必看）**：
1. `scripts/limit_pool_fetch.py`（涨停池/连板梯队，东财 push2ex，云环境可用、无需凭证、不反爬，
   含 zt_count/max_lbc/ladder/first_board_width/promotion_rate/fanbao）**已挂 cron `37 15 * * 1-5`**
   （wrapper `~/.hermes/scripts/qing_limit_pool_fetch.py`，job「涨停池拉取」）；
   `scripts/intraday_changes_fetch.py` **仍未挂 cron**（`infra/data/intraday_changes` 目录不存在）。
2. KPL `lianban`(PHBList) 字段结构 `[代码,名称,涨幅,连板数,"N连板",板块,"板块;天数"]`，连板股断板后标签变
   「昨N连板」、连板数归 0（兑现日特征，原样透传勿归一）；`erban`(ErBanList) 是「当日二板池」同构，盘中为空、尾盘才出。
   KPL lianban 只有「昨日连板股今日表现」（3 条），无法替代 limit_pool 完整梯队（首板宽度需 limit_pool）。
3. `dataset.py _load_emotion` 已补 `erban` 字段 + 连板梯队语义化（中文键 `连板梯队`/`二板池`，字段
   code/name/pct/连板数/标签/板块）。
4. 盘中分时量能**完全缺失**：腾讯指数日K只有成交量（手，无成交额），KPL 收盘后一次性拉取。
   是「放量 vs 缩量」判断的根因，需新数据源调研（候选：东财盘中成交额[反爬]、分钟K累加、新浪/同花顺）。
5. `dataset.py _CORE_PATTERN_IDS = ("sentiment_cycle","mainline_identification","position_by_cycle")` 注入 3 个核心模式全文（`position_by_cycle` 于 08-14 晚挂入）；
   新增 pattern 需加进这里，而非散落在 prompt。

### 盲判系统三层（改动手册）

| 层 | 文件 | 关键位置 |
|----|------|---------|
| prompt（教思路） | `blindtest/replay.py` SYSTEM_PROMPT L46-63 | 复盘盲判判据 |
| prompt（教思路） | `shadow/premarket.py` PREMARKET_SYSTEM_PROMPT L24-41 | 早盘盲判判据 |
| 数据包 | `blindtest/dataset.py` build_daily_pack / _load_emotion / _load_limit_pool / _load_intraday_changes | 数据组装 |
| 模式库 | `framework/reasoning-patterns.yaml` | 推理框架（_CORE_PATTERN_IDS 引用） |

## 操作建议 × 周期位置映射（2026-08-14 用户纠正「不要盲目写死提示词」后沉淀）

UP 的操作建议是「状态 → 动作」的函数，**不是常量**。把具体动作（买阴不买阳/做T压成本）写死进 SYSTEM_PROMPT，
会在错误状态输出反向操作——反弹末期也喊「买阴不买阳」，而 UP 说的是「获利了结、不要急着表态」。

| 周期位置 | 环境判据（UP 信号） | 操作建议 | 证据 claim |
|---------|-------------------|---------|-----------|
| 反弹初期(第1-2天) | 双创底部钝化、做空尾声 | 加仓至七成、半仓盘中打满 | `07-31-018`、`03-17-001-a` |
| 反弹中段(趋势未变) | 缩量回调、分歧但趋势完好 | 持股 + 买阴不买阳 + 灵活做T | `08-14-039`、`05-28-002-c` |
| 反弹超预期(第9天+) | 放量兑现、涨停家数萎缩 | 获利了结、降仓位、不急表态 | `08-13-023`、`08-13-046` |
| 高位/兑现阶段 | CPO高位兑现、龙头滞涨 | 降低仓位、不追高、保利润 | `04-26-001`、`06-10-038-a` |
| 趋势下跌 | 破位、恐慌杀跌 | 纪律优先，买阴只是小仓位博弈 | `06-11-001-m`、`06-08-001-i` |
| 磨底期 | 低容错、量化横跳 | 不追高、找低位拿住、**不瞎操作** | `06-04-004-i` |
| 震荡调整 | 操作难度大、无主线 | 降低预期、控制操作频率 | `07-06-008`、`07-08-005-k` |

三条元规则（贯穿所有状态的上层纪律）：
1. **仓位纪律高于判断**（`06-11-001-m`）：「判断可以错，纪律不能破」——动作优先级由「状态」决定，不是看多看空。
2. **确定性决定动作力度**（`08-09-030`、`08-13-046`）：买阴不买阳的前提是「方向确定性高」，确定性决定敢不敢在阴线上接，不等于任何位置都能买。
3. **兑现日/磨底期的动作是「不做」**（`08-13-046`、`06-04-004-i`）：特定状态最优动作是克制，不是任何操作模板。

**落地结论（已实施，2026-08-14 晚，用户授权）**：盲判已有 `market_stage`(主升/震荡/调整/恐慌) + `nature`(六选一) 两个状态字段。
正确改法不是把「买阴不买阳」写进 conclusion，而是让 AI 基于自己判定的状态推导动作——映射关系做成 pattern 判断步骤
（`position_by_cycle`：先定位周期位置→再匹配动作），不是硬编码。

**已落地**（提交 `85bdfa7`）：
1. `position_by_cycle` 挂入 `_CORE_PATTERN_IDS`（`dataset.py`）→ 每次盲判强制注入全文（4 步 + 4 证伪），不再只是 patterns 索引；
2. 输出契约 `v3 → v4`，新增 `operation{position/action/basis}`（`replay.py`/`premarket.py` 的 SYSTEM_PROMPT + `parse_result` 规范化）；
3. prompt 规则 7：operation 必须用 position_by_cycle 推导（先定位周期位置 → 按映射匹配动作 → 三条元规则校验），
   禁止脱离状态写「逢低关注/降低仓位」这类无状态依赖的套话；
4. 早盘盲判重跑验证（`2026-08-14-pre`，v4）：`operation.position=震荡调整 → action=降低预期、控制操作频率`，
   `used_patterns` 含 `position_by_cycle`，动作正确由状态推导而非硬编码。
