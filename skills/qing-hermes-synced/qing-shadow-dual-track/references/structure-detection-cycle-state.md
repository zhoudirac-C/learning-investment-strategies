# 顶底结构识别 + cycle_state 连续周期追踪（2026-08-14）

## 背景与目标

用户要「完整版」：通用顶底结构识别（MACD 背离），不止底部还有顶部，输入 K 线
就能算（通用到 ETF / 个股 / 指数），用于盲判 `cycle_state`（反弹第几天）连续追踪。
核心诉求：**第二天引用 prior_day 时知道「反弹到第几天 + 该注意什么」**，而不是
每天从零判断「震荡/调整」。

## UP 推导「底部反弹几天」的完整逻辑（挖自 claims + framework）

**核心公式：底部结构级别 → 理论反弹天数**（级别越大窗口越长）：

| 底部结构级别 | 理论反弹天数 | 来源 |
|-------------|------------|------|
| 30min 底 | 3 天 | claim-20260310-001-a |
| 60min 底 | 2 天（单级别；上级别有顶部压制时缩短） | claim-20260317-001-a |
| 60/90min 底（共振） | 6-8 天 | claim-20260731-020 |
| 120min 底 | 12 天 | claim-20260709-004-a |

顶部：90min 顶 = 8 天调整、120min 双顶 = 4-6 天（framework 对照表）。

**三个修正因子**：①上级别压制打折；②底部钝化消失→无法推算、改用趋势突破兜底
（突破关键点位才确认）；③每天根据实际走势动态修正剩余窗口。

**本轮反弹完整闭环**：07-31 科创 60/90min 底部结构形成 →「理论 6-8 天，今天第 1 天」
→ 08-13 第 9 天超预期 → 获利了结。这就是 cycle_state 要追踪的连续状态。

## structure.py 模块（src/investment_engine/structure.py）

- `compute_macd(closes) -> (dif, dea, macd_hist)`：EMA12/26/9，口径对齐
  `scripts/update_index_klines_intraday.py::_ema`（前 period-1 根 None，第 period 根 SMA 种子）。
- `detect_structure(klines, window=5, timeframe) -> {bottom, top}`：找局部极值点 →
  背离判定 → 金叉/死叉结构形成 → 级别→天数映射。
- `LEVEL_DAYS`：级别→理论天数映射表（上表）。

**MACD 背离判定**：底背离 = 价格创阶段新低 + DIF 未同步新低（抬高）；顶背离 =
价格创阶段新高 + DIF 未同步新高（降低）。结构形成 = 背离后 DIF 金叉（底）/死叉（顶）DEA。

## 关键坑（未来复用必读）

1. **EMA26 需 ≥26 根历史**才有效，前 25 根 dif=None。查询必须拉 ≥100 根历史，
   否则有效数据不足、背离识别全空（90min 只查 25 根 → dif 全 None → 0 结果）。
2. **index_klines 表的 dif 已漂移，必须自算 MACD**：表里 dif 是增量更新时算的，
   历史 close 被覆盖后不重算（实测自算 49.8 vs 表 39.7）。不能信任表里的 dif/dea。
3. **盘中分时量能数据源已解决（TDX 指数分钟线，2026-08-14 验证）**：本地 index_klines 表里
   分钟级 amount 不可靠（深市 sz399001 全 0、30min 缺开盘/收盘两根），但 **TDX `get_index_bars`
   指数分钟线 amount 可靠**：上证+深证 60min 全天 amount 累加 = 两市全天成交额，误差 0.007%
   （21430 亿 vs KPL 21428 亿）。这是「放量 vs 缩量」盘中量能曲线的数据源。服务器支持差异
   （杭州/浙江/上海电信能拉，腾讯云1/广东电信空）+ `get_kline` 需 `retry_empty=True`，见
   `tdx-data-source-troubleshoot` skill。
4. **极值点识别要跳过 dif=None 的位置**（前 25 根 MACD 未算出），否则 _assess 比较 None 报 TypeError。

## cycle_state 集成（契约 v5）

- `dataset.py::_load_structure(day)`：读上证 sh000001 五个级别（daily/120/90/60/30min），
  各调 detect_structure，只保留有结构（bottom/top 非 None）的级别，注入 pack["structure"]。
  注意分钟级 bar_time 带时间（'…15:00'）、daily 不带，查询上限分别用 day 与 day+' 23:59:59'。
- `replay.py`/`premarket.py`：契约 v5，JSON 加 `cycle_state`（rebound_day/bottom_level/
  bottom_date/theoretical_window/note）+ `operation`（position/action/basis）。
- `predict.py::_load_prior_summary`：prior_day 摘要加 cycle_state + operation 接力。

## 冷启动解法：recent_bottom/recent_top（选项2 已落地，2026-08-14）

问题：`structure` 块只保留「当前还在背离/刚形成」的结构，历史底部结构（如 07-31）在
反弹后段已经不在里面；而 prior_day 是旧契约（无 cycle_state）时无法接力。结果：
首次 v5 跑 cycle_state 的 rebound_day=null（盲判冷启动，看不到 07-31 底部结构）。

**已落地（选项2）**：`detect_structure` 增加 `recent_bottom` / `recent_top` 字段，遍历所有
背离对找「背离+随后金叉/死叉确认」的最近一次，即使当前已不在背离状态也能定位历史结构形成日。
验证：60min recent_bottom=07-31 10:30，精确对齐 UP「科创60/90分钟底部结构今天形成」。
`_load_structure` 已把 recent_bottom/recent_top 注入 structure 块（dataset.py）。

**遗留调优（不阻塞）**：
- 90min 极值点漏谷（window=4 在稀疏分钟线上漏 08-03 的谷）→ 90min recent_bottom=None；
  60min 定位正确。根因是「窗口内最小/最大」算法不够鲁棒，后续用分形/更宽确认窗口优化。
- recent 时间范围未限制：daily recent_bottom 报到 03-12（5 个月前），`_find_recent_formed`
  需加「最近 N 个交易日」限制。
- 多级别共振未做：60min recent_bottom 理论天数 (2,2) 是单级别口径，UP 的「6-8 天」是 60+90 共振结果。

## 验证锚点（算法与 UP 判断吻合）

- 回溯 07-31：上证 90min 识别底背离（价格 3803 新低但 DIF 从 -27.5 抬到 -18.1），
  理论天数 (6,8) = UP「科创 60/90 分钟底部结构，反弹 6-8 天」。
- 当前 08-14：识别 30min 顶部结构形成 + 60min 顶背离 + 90/120min 无结构 = UP
  「无 60 分钟以上顶部结构」。

## 关键修正（2026-08-14 晚，覆盖上文的遗留）

1. **多指数结构识别（最关键）**：UP 的「6-8 天」是**科技类指数**（科创/创业板）90min
   底部结构，上证大盘同期只有 60min 单级别（2 天）、是 V 形反转无底背离。`_load_structure`
   改为多指数（上证 sh000001 + 科创50 sh000688 + 创业板指 sz399006，`_STRUCTURE_INDEXES`），
   输出 `{指数名: {级别: 结构}}`。本地无科创分钟数据 → 脚本加 sh000688（`update_index_klines_intraday.py`
   + `pre_fetch_index_klines.py` 的 INDICES），TDX 回填历史。
2. **cycle_state 改代码算（消除 LLM 随机性）**：让 LLM 从 structure 找 recent_bottom 数交易日
   不可靠（这次识别下次不识别）。改为 `dataset.py::_compute_cycle_state` 代码确定性算
   （优先科创50 90min → 创业板指 → 上证），注入 `pack["cycle_state"]`，LLM 只引用+写 note。
3. **operation↔cycle_state 联动**：requirement 7 明确「position 第一决定变量是周期位置
   （结合 rebound_day）」，超窗口判「反弹超预期/高位兑现」而非「震荡调整」。验证：
   operation.position 从「震荡调整」→「反弹超预期」，action→「获利了结、降低仓位」。
4. **TDX 兜底（东财反爬断连）**：`fetch_latest_klines` 东财失败后分钟线降级 TDX
   `get_index_bars`（30/60min 直接拉、120min 由 60min 按时点对齐合成：10:30+11:30→11:30、
   14:00+15:00→15:00），日线保持腾讯兜底。TDX 需修 `resolve_symbol`：000688/000985/000932
   加入沪市指数列表，否则误判为个股走 get_security_bars 返回垃圾数据。
5. **起点锚口径**：recent_bottom.time 是「金叉确认日」，UP 说的「形成日」可能是「底背离谷2」
   或条件句「若今天形成」（claim-20260731-020 是预判）。科创50 90min 底背离 07-21→07-30、
   金叉 08-04，导致 rebound_day 与 UP 差 1-2 天（不影响「超窗口、接近尾声」结论）。

已解决的遗留：90min 漏谷（科创50/创业板 90min 均能识别，window=4 足够）；recent 时间范围
（`_load_structure` 加 60 天 cutoff 过滤）；多级别共振（科创50 90min 直接给 6-8 天，无需合成）。

