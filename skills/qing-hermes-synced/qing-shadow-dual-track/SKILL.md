---
name: qing-shadow-dual-track
description: |
  M2 影子双轨（影子 AI / shadow）评测系统运维：定位每日盲判/归因产物、
  手动补跑、排查断档根因。触发词：影子 AI、影子双轨、shadow、某天的影子复盘。
---

# qing-shadow-dual-track

M2 影子双轨 = 每日盲判 → 收盘归因 → 提案回写，与 UP 复盘对照验证 AI 判断质量。
代码在 `src/investment_engine/shadow/`（daily/predict/attribute/graduation/status/factcheck/maturity）。

## LLM 通道（2026-08-25 起：sensenova deepseek-v4-flash）

盲判/归因统一走 `src/investment_engine/blindtest/replay.py` 的 `call_deepseek`。
2026-08-25 DeepSeek 官方自费 API 余额耗尽（402 Insufficient Balance，8/25 复盘盲判直接 error），
切换至 sensenova 通道（`https://token.sensenova.cn/v1`，与 Hermes 主模型同 key）：

- 常量全部环境变量可覆盖：`SHADOW_LLM_MODEL`（默认 `deepseek-v4-flash`）、`SHADOW_LLM_BASE_URL`
  （默认 sensenova）、`SHADOW_LLM_MAX_TOKENS`（默认 16384，thinking off 用）、
  `SHADOW_LLM_THINKING_MAX_TOKENS`（默认 32768，thinking on 用）、`SHADOW_LLM_THINKING=on` 恢复推理、
  `SHADOW_LLM_TIMEOUT`（默认 600s，单次 LLM 调用超时）。
- 三层超时覆盖（thinking on 时单轮盲判 ~4 分钟，均留足余量）：
  LLM 调用 600s（replay.py）→ cron 脚本 3600s（Hermes `_DEFAULT_SCRIPT_TIMEOUT`）→
  wrapper `subprocess.call` 无超时（cron 层兜底）。用户 8/25 明确提醒「记得把超时时间放长」。
- key 优先 `SENSENOVA_API_KEY`，回退 `DEEPSEEK_API_KEY`；`.env` 已含 SENSENOVA_API_KEY，无需改 wrapper。
- **推理模型两个坑（实测，8/25）**：
  1. deepseek-v4-flash 默认输出上限 8192 会被 reasoning 吃满——盲判长 prompt（~72K tokens）
     下 content 返回空字符串（`输出非 JSON: ''` 且 completion_tokens=8192/16384 满载）。
     修复：thinking off 时 `max_tokens=16384`；thinking on 时 `max_tokens=32768`
     （`_MAX_OUTPUT_TOKENS_THINKING`，reasoning 动辄数千 tokens）。
  2. sensenova 端点有 rpm/quota 限流（429 rpm exhausted / quota exceeded），瞬时峰值会 429，
     重试逻辑（2^attempt 退避）可自愈；批量补跑时注意间隔。
- **thinking on vs off（8/25 实测）**：用户 8/25 晚切换 thinking on（`SHADOW_LLM_THINKING=on`
  写入 `.env`）。thinking on 延迟 208s（首调）+30s（重试） vs thinking off 15s，但质量质变：
  方向识别从「通信设备/半导体 维持」→「创新药/人工智能 新增」（更贴近当日医药/AI应用/机器人实际上涨），
  推理深度显著提升（「缩量宽度修复而非强度修复」「按反抽消耗调整时间」「昨日判断被涨停扩宽暂时止住」）。
  结论：thinking on 是 UP 方法论的正确打开方式，慢但值得。
- 诊断入口：`log/llm_calls.jsonl`（每条调用 ts/tag/model/latency/error/completion_tokens）。
  看到 `completion_tokens` 满载 + `reply_chars: 0` → 推理吃满输出预算，不是 prompt 问题。

## 产物位置（"某天影子复盘在哪"先查这里）

| 产物 | 路径 | 说明 |
|------|------|------|
| 每日盲判（复盘） | `evals/shadow/predictions/YYYY-MM-DD.json` | market_stage/scenarios/directions/watch_next/used_patterns |
| 早盘盲判（盘前预测） | `evals/shadow/predictions/YYYY-MM-DD-pre.json` | 预测当日，用 T-1 收盘 + 隔夜外盘，`meta.prev_day` 标数据日 |
| 收盘归因 | `evals/shadow/attributions/YYYY-MM-DD.json` | 三方对照（UP复盘 vs AI盲判 vs 市场），trigger 多为 `up-comparison-manual` |
| 完整性报告 | `logs/shadow-status.md` | 记录天数、stage_hit、归因有无、提案统计 |
| 提案 | `framework/proposals/` | open/applied/rejected |

## 归因补跑（2026-08-27 实测）

- **结构性缺口（2026-08-27 已修，勿再当缺口报）**：`daily.py` 现已覆盖三条自动 trigger——
  `stage_miss`（晚盘）、`stage_miss_premarket`（早盘，TDD 补入，commit bfa4fe0）、
  `direction_miss`（到期超额≤0）。早盘修复前漏掉的 8-20/8-24 已手动补跑（commit 2bf7ceb）。
  手动补跑仅用于历史缺口日，入口（脚本放 /tmp、repo 根目录执行）：
  ```python
  from investment_engine.shadow.attribute import run_attribution
  from investment_engine.blindtest.truth import load_truth
  rec = run_attribution(day, trigger="stage_miss_premarket", pred=<该日 -pre json 记录>,
      score_info={"truth": load_truth().get(day), "track": "premarket",
                  "predicted_stage": pred["result"]["market_stage"]})
  ```
  补跑后调 `investment_engine.shadow.status.write_status()` 刷新完整性报告。
- **必须先加载 .env**：手动 shell 跑 run_attribution 时 `call_deepseek` 读 SENSENOVA_API_KEY，
  需 `set -a; source .env; set +a` 再跑（cron 自动注入，手动终端不注入，否则报
  "缺少 SENSENOVA_API_KEY"）。LLM 调用约 15s/日。
- **断档先核对再补**：归因只对「判错日」生成，不是每天都有。核对顺序：
  ① 预测文件 `stage_hit` + `load_truth()` 真值 → ② scored 日 `due_scores.direction_details`
  平均超额 ≤0（direction_miss）→ ③ 与 attributions/ 目录比对。历史 triggers 有
  stage_miss / direction_miss / process_audit / up-comparison-manual 多种，勿按 trigger 名
  反推是否该有归因。
- **已落地**（2026-08-27，commit bfa4fe0）：daily.py 早盘 `-pre` 判错也触发归因
  （trigger=`stage_miss_premarket`）。此前早盘 stage_miss 从不归因（8-20/8-24 漏，
  已手动补，commit 2bf7ceb）。`test_daily.py` 10 用例含早/晚盘归因触发回归。
- **direction 评分 samples=0 坑**：LLM 输出的 direction_id 若为中文名（银行/煤炭/医药/
  通信设备），既不在 TDX concept 板块映射（sector_members.json ~270 个概念板块）也不在
  direction_pool 英文 id 集合 → `_direction_members` 返回 [] → direction_scores 跳过 →
  该日方向超额失明（`_direction_missed` 永远 False，不触发归因）。识别标志：
  `due_scores.directions.samples=0` 且 `direction_details=[]`（实测 8-19/8-20）。
  根因与治本方案（数据源实测 + `_direction_members` 新浪行业回退设计，用户已认可）：
  见 `references/scoring-rescore-ops.md` §六；手动重评配方见 §二。治方向 = prompt 约束 LLM 输出 direction_id 到映射集合（未实施，提案级）。
  **应急重评法**（8-19/8-20 实测）见 `references/scoring-rescore-ops.md`——成分取盲判自选
  stocks、口径与 direction_scores 一致，回填时附 `_rescore_note` 标注局限（n=1~2 偏乐观）。
- **K 线停更排查**：`stocks_kline` 里 TDX 批量成分股（~4600 只）靠 `fetch_tdx_sector_klines.py`
  增量续跑，会断更（实测 8-13 后全停）——评分前置先查
  `SELECT MAX(trade_date) FROM stocks_kline WHERE code=?`。该脚本 `--only` 参数有 bug
  （静默退出零输出）；手动补用 `TdxMarket().get_kline(code, category='daily', count=90)`
  + `save_klines(code, kl, db_path=...)`，7 只 ~10s。
- 提交纪律：只 add 归因文件 + 生成的提案 + shadow-status.md，勿混入工作区其他改动
  （预测/配置等并行修改不属本次补跑）。

盲判 JSON 结构（v5，2026-08-14 起）：`market_stage` + `nature` + `stage_reason`、`scenarios[]`（name/condition/conclusion/key）、
`watch_next[]`、`invalidation[]`、`directions[]`（direction_id/reason/posture/trend/stocks）、
`operation{position/action/basis}`（状态→动作推导，见 position_by_cycle）、
`cycle_state{rebound_day/bottom_level/bottom_date/theoretical_window/note}`（反弹天数连续追踪）、`used_patterns[]`。
契约版本在 `blindtest/replay.py` 的 `PROMPT_VERSION`（现 `v10.1`），`parse_result` 是唯一的字段规范化入口。
v10（2026-08-21）：规则25 宏观三条件校验（global_macro 含美债收益率时 stage_reason 必须做「美联储/油价80/10Y 4.70%」三条件检验并给宏观 vs AI证伪定性，机械校验 `_MACRO_CHECK_HINTS`）+ 规则23b 催化兑现覆盖（隔夜映射股大幅回落优先于前日催化，reason 须同时引用两者）。来源：8/21 盲判 vs UP 早盘对比——UP 用三条件把下跌定性为宏观扰动而非 AI 证伪、用莫德纳隔夜 -23.6% 反向印证医药分歧，盲判均缺。
v10.1（2026-08-21 晚）：规则26 指数点位幻觉校验（输出千位级点位须落在 pack 指数当日收盘 ±10% 内，量能语境豁免）+ factcheck 反向提取（「X涨停」的 X 不在涨停池即报错，连接/量能语境词过滤防误报）。来源：8/21 复盘盲判实测两缺陷——invalidation 幻觉点位 4588.7、「江海股份涨停」漏检。
数据包含 `structure` 块（上证多级别顶底结构）。

**顶底结构识别 + cycle_state 关键坑**（2026-08-14 实测，完整细节见 `references/structure-detection-cycle-state.md`）：
- `src/investment_engine/structure.py` 是通用顶底结构识别模块（MACD 背离 + 金叉/死叉 + 级别→天数映射），
  输入 K 线就能算、不绑定指数，可复用于 ETF/个股。级别→天数：30min底=3天/60min底=2天/90min底=6-8天/120min底=12天/90min顶=8天。
- **`index_klines` 表的 dif/dea 是增量更新时算的、历史 close 覆盖后不重算，已漂移**（实测自算 49.8 vs 表 39.7）——
  结构识别必须自算 MACD（`structure.py::compute_macd`），不能信表里 dif。
- MACD EMA26 需 ≥26 根历史，查询必须拉 ≥100 根，否则有效数据不足、背离识别全空（90min 只查 25 根 → dif 全 None）。
- 盘中分时量能数据源已解决：TDX 指数分钟线 amount 累加 = 两市成交额（误差 0.007%），见 `tdx-data-source-troubleshoot`。
- **cycle_state 冷启动已解**：`detect_structure` 的 `recent_bottom/recent_top` 追踪最近结构形成日，
  即使当前已不在背离状态也能定位反弹起点，不依赖 prior_day 接力。
- **多指数是关键（2026-08-14 晚修正）**：UP「6-8天反弹」是科技类指数（科创/创业板）90min 底部结构，
  上证只有 60min 单级别 2天、V形反转无底背离。structure 块改多指数（上证+科创50+创业板指），
  科创50 需脚本加 sh000688 + TDX `resolve_symbol` 修 000688 为沪市指数。
- **cycle_state 用代码算，别让 LLM 数**：LLM 从 structure 找 recent_bottom 数交易日有随机性（这次识别
  下次不识别），改 `dataset.py::_compute_cycle_state` 确定性算（优先科创50 90min），LLM 只引用。

v3 相对 v2 新增三件套（对齐 UP 方法论，补「只会阶段二分」「只看单日」两个盲区）：
- `nature`（性质定性）：`放量攻击|缩量企稳|主动降速|内生瓦解|外力扰动|方向转折` 六选一，定性量价性质、区别于阶段二分。
  08-13 实测：盲判输出 `主动降速`，精确对齐 UP「放量阴线=主动降速非方向转折」。
- `directions[].trend`（方向连续性）：`加强|退潮|新增|维持` 四选一，标注方向相对昨日的连续性。
- `prior_day` 注入（连续状态）：`shadow/predict.py` 的 `_load_prior_summary(day)` 读前一交易日复盘盲判摘要
  （market_stage/nature/stage_reason/watch_next/directions），注入 `pack["prior_day"]`；`premarket.py` 同样注入。
  SYSTEM_PROMPT 要求对照昨日 watch_next 兑现/证伪。效果：08-13 stage_hit 从 False（判「调整」）→ True（判「震荡」+「主动降速」）。

⚠️ `prior_day` 会传染历史盲判的**错误口径**：若前一日盲判是在数据修复前生成的（如「成交额18493.9万手」误读），
它会原样带进后一日的 prior_day 摘要。随历史盲判逐步重跑自愈，但做连续对比时要注意这个污染源。

## 双盲判节奏（2026-08-13 起）

| 时点 | 任务 | 入口 | 数据 | stage_hit 回填 |
|------|------|------|------|---------------|
| 9:28 早盘 | 盘前预测当日 | `scripts/shadow_premarket.py` | T-1 收盘 + 隔夜外盘 | T 日复盘盲判时回填 |
| 22:00 复盘 | 判当日 | `scripts/shadow_daily.py` | T 日收盘 | 当日回填 |

两条 cron（Hermes，`deliver: feishu`）：`28 9 * * 1-5` 早盘、`0 22 * * 1-5` 复盘。
早盘盲判代码在 `src/investment_engine/shadow/premarket.py`（`run_predict_premarket`），
隔夜外盘落盘 `infra/data/overnight_us/{day}.json`（`scripts/overnight_us_fetch.py`，cron 08:20）。

## 手动补跑

```bash
cd ~/learning-investment-strategies
set -a && source .env && set +a   # shadow_daily.py 不 source .env，缺 key 会报 predict_error（2026-08-25 起 key 优先 SENSENOVA_API_KEY）
.venv/bin/python scripts/shadow_daily.py --date 2026-08-12       # 补复盘盲判（判当日）
.venv/bin/python scripts/shadow_premarket.py --date 2026-08-12   # 补早盘盲判（预测当日）
```

`--date` 参数可补历史；复盘脚本会先补当日指数 daily 收盘价（`update_one(code,"daily")`，东财→腾讯兜底）再跑。

### ⚠️ 补跑前先补 K 线数据（2026-08-13 实测，最易踩）

盲判 `build_daily_pack` 读 **`stocks_kline` 表**（个股日K）＋ **`index_klines` 表**（指数，统一后），
但目标日收盘数据**可能缺失**——早盘 6-8 点预拉取只拉到「前一交易日」（当时当日未收盘），
而收盘后没有补数据 cron。后果：`has_fresh_data(day)` 因最新交易日 != day 返回 False，
盲判直接 `no_data` 静默跳过（不报错，只输出一行）。

补跑前先检查 + 补拉，顺序不能乱：

```bash
# 1. 检查目标日数据量（盲判依赖 stocks_kline，不是 index_klines）
python3 -c "import sqlite3; c=sqlite3.connect('infra/data/kline_cache.db'); \
  print('个股:', c.execute(\"SELECT COUNT(*) FROM stocks_kline WHERE trade_date='2026-08-12' AND code NOT LIKE 'IDX%'\").fetchone()[0]); \
  print('指数:', c.execute(\"SELECT COUNT(*) FROM stocks_kline WHERE trade_date='2026-08-12' AND code LIKE 'IDX%'\").fetchone()[0])"

# 2. 缺失则补拉：先指数后个股（FORCE_KLINE_FETCH=1 绕过窗口+ready 检查，手动补跑必加）
.venv/bin/python scripts/fetch_index_klines.py                       # 5 个指数 → IDX 别名入 stocks_kline
FORCE_KLINE_FETCH=1 .venv/bin/python scripts/pre_fetch_klines.py    # 个股（stock_pool+watchlist+positions）

# 3. 再跑盲判（见上）
```

**时间隔离要点**（用户反复强调「别弄错时间数据」）：在交易日未开盘时段（凌晨 0-9 点）补拉，
腾讯 API 最新日K 就是「前一交易日收盘」，恰好正确；若开盘后补拉会混入当日盘中数据，需谨慎核对
`fetch_index_klines.py` 打印的最后日期是否 == 目标日。

**两表区别**（易混淆，2026-08-13 起有架构变更）：

| 表 | 内容 | code 格式 | 写方 | 读方 |
|----|------|-----------|------|------|
| `stocks_kline` | 个股日K（+旧 IDX 别名指数） | `000636.SZ` / `IDX000300` | pre_fetch（个股）、fetch_index_klines（指数别名） | 盲判个股、回测个股 |
| `index_klines` | 指数多级别K线 | `sh000001` 等 | update_index_klines_intraday（盘中 */30 cron） | 监控 MACD、**盲判指数（统一后）** |

⚠️ **2026-08-13 架构变更**：盲判/评分/真值标签的指数**统一改读 `index_klines` 表**（不再读
`stocks_kline` 的 IDX 别名）。新增 `history.get_index_daily()` + `INDEX_ALIAS_TO_CODE` 映射
（IDX000300→sh000300 等）。原因是：写 IDX 别名的 `fetch_index_klines.py` 从未挂 cron（数据会断），
而 index_klines 有盘中 cron 在持续更新。但 index_klines 的 daily 级别**曾有一个收盘价覆盖 bug**，
必须先修（见下节 + `references/index-klines-daily-override-bug.md`）。

### ⚠️ 早盘盲判注入外盘要防「来源指称」泄漏（2026-08-13 实测）

早盘盲判 `premarket._pack_to_premarket_prompt` 注入隔夜外盘时，`us_map.yaml` 的 **theme name**（如
「存储（UP 用 SK海力士ADR映射…）」）和 **earnings_note**（如「…（2026-08-11 UP早盘记录）」）里含
「UP」字样，会触发 `assert_no_leakage` 报 `prompt 含来源指称 'UP'`（error 落盘、次日重跑）。

修法：注入时对 theme name 和 earnings_note 都做 `FORBIDDEN_RE.sub("██", ...)` 打码
（和 directions 的 name 打码一致）。`FORBIDDEN_RE = re.compile(r"UP|青枫浦|博主")`，从
`blindtest.dataset` 导入。排查时逐个数据块 `FORBIDDEN_RE.search(json.dumps(块))` 定位，别只看 pack 顶层。

### 方向池迁移方向（2026-08-13 起）

本地方向池 `direction_pool.yaml`(45方向) + `stock_pool.yaml`(212只) 是「人工圈定的静态池」，
盲判方向识别被它锁死，看不到市场实时新题材。KPL 板块榜只有 Top4 太稀疏，正确答案是 **TDX 概念板块成分股**：

- TDX `block_gn.dat` 有 269 个概念板块 / 41054 条成分股映射，完整覆盖算力租赁/存储芯片/PCB/CPO/光通信等 UP 方向
- 但 pytdx `get_and_parse_block_info` 有下载 bug（板块名被污染成乱码），已修：用 `TdxMarket.get_block_members()`
- 已落盘 `config/stock_monitor/sector_members.json`（`scripts/fetch_tdx_sector_members.py`）
- 板块实时涨幅 = 成分股 `get_quotes` 批量拉 pct_change 取均值（不依赖本地 kline_cache，本地覆盖率仅 9-27%）

详见 `tdx-data-source-troubleshoot` 的 `references/tdx-block-members-parse-bug.md`。

**2026-08-13 已完成三处接入 TDX 板块（替代 direction_pool/stock_pool）**：
- `dataset.py`：`directions` 用 TDX 板块（`_sector_directions` 反推「当日有行情的板块」，滤
  ST/次新/含H股等 7 个噪音板块）；`stocks` 加 `sectors` 多板块归属字段，`direction` 取首个非噪音板块
- `score.py`：`_direction_members` 优先查 `sector_members.json` 找成分股，回退 stock_pool
- `sector_data.py`：新增 `fetch_tdx_boards` provider（成分股实时行情聚合板块涨幅），接入
  东财→新浪→tdx→同花顺 fallback 链

⚠️ **TDX 板块成分股 K 线覆盖是评分瓶颈**：本地 kline_cache 只覆盖 222/5364 只（4%），
`direction_scores` 算 5 日超额需要成分股 K 线落库。补拉脚本 `scripts/fetch_tdx_sector_klines.py`。
⚠️ **TDX 高频请求有间歇性失败**：同一只股票首次 `get_kline` 返回空、重试即成功
（实测 000006/000008 重试后 [90,0,90]）。无重试时失败率 36%，加 3 次重试（指数退避）后降到 2%。
只剩确定性失败（停牌/退市，如 000004）。任何批量拉 TDX K 线的脚本**必须带单只重试**。

## 断档排查（2026-08-13 实测）

用户问"找到影子 AI 跑的某天复盘"时，若 `predictions/` 目录无该日文件 = **当天没跑**。

**历史根因**：shadow_daily **曾长期未挂 cron**——8/7-8/11 产物是手动补跑的。**2026-08-13 起已挂**：
`28 9 * * 1-5` 早盘盲判 + `0 22 * * 1-5` 复盘盲判（Hermes cron，job 名「影子双轨-早盘盲判」/
「影子双轨-复盘盲判」）。排查顺序：

```bash
cronjob list | grep -i shadow          # Hermes 任务（应先看这里）
crontab -l | grep -i shadow            # 系统 crontab（本机 Mac 才有）
git log --all --oneline | grep -i shadow  # 最后落盘时间（判断断档起点）
```

**断档链路自查**（数据 → 盲判三层，哪层缺补哪层）：
1. 个股日K `stocks_kline`（pre_fetch cron：早盘 6-8 点 + 收盘后 15:35）
2. 指数 daily `index_klines`（盘中 */30 9-15 更新，收盘后那一次覆盖成收盘价）
3. shadow 盲判 cron（早盘 9:28 / 复盘 22:00）

## 对照要点（避免误判归因）

- **判断"数据缺失"前，先 `cronjob list` 核对现有定时任务**——用户反复纠正：数据拉取任务往往
  已在 cron 里（指数日K `update_index_klines_intraday` */30 9-15、个股日K pre_fetch 6-8 点），
  问题是**没对齐消费方口径**（盲判读的表 ≠ cron 写的表），不是"没有任务"。别拍脑袋下"全缺"结论。
- attribution 是**人工归因**（非自动），trigger 字段标记触发方式
- 盲判数据包 **2026-08-13 起已含 KPL 情绪/新闻/龙虎榜**（凭证已配置，`.env` 的
  `kpl_user_id/kpl_token/kpl_device_id`；`_load_emotion` 已把拼音字段语义化）。仍缺 limit_pool/盘中变化（东财源，非 KPL）——详见
  `references/blind-vs-up-gap-analysis.md`。

  ⚠️ **KPL 成交额字段语义（易踩，2026-08-13 实测）**：`q_zrtj`/`q_zrcs` 是**昨日**成交额（zr=昨日，单位万元），
  `qscln` 才是**当日**成交额。`dataset.py` `_load_emotion` 早先误用 `q_zrtj` 当「两市成交额_亿」，导致盲判拿到
  T-1 成交额（08-13 拉到 21524.2 亿=08-12 的值）。已修：`两市成交额_亿` 用 `qscln`（fallback `q_zrtj`），
  新增 `昨日两市成交额_亿` 用 `q_zrtj` 供环比放量判断。其余：`s_zrtj`=沪市昨日、`szln`=深市当日。
- 方向 5 日结算未到期（`status: pending_maturity`）前，归因只评推理质量不评对错
- 设计文档：`docs/superpowers/specs/2026-08-08-m2-shadow-dual-track-design.md`、
  `docs/superpowers/specs/2026-08-10-shadow-pack-contract-v2.md`

## 盲判 vs UP 差距分析（用户会周期性要求）

「对比 UP 与盲判、找推理差异/可学习点/缺的数据源」是 recurring 任务。固定分析结构、
7 处推理差异、欠缺数据源清单、量能口径 bug、外盘数据源路由，全部沉淀在
`references/blind-vs-up-gap-analysis.md`。做这类对比前先读它。

08-14 二次对比新增（已并入同 reference）：外盘映射层与量能口径已修复收敛，新核心缺口是
「量能形态判断」——盲判用收盘成交额环比判「放量」，UP 用盘中分时曲线（开盘3万亿→尾盘2.5万亿）
判「全天缩量」，论据反了、结论碰巧都落在「震荡」。并沉淀了「改造三类法」（改 prompt 教 / 补数据源 / 修 bug）。

08-21 三次对比新增结论（盲判早盘 vs UP 08:49 专栏全文）：
- **差距定性**：阶段/情绪/量能三维已收敛（盲判与 UP 算出同一个二板健康区间数），剩余差距是
  「UP 平均比盲判多推两层因果 + 多一层次日演绎」——不是「看得见什么」而是「看见之后推几层」。
- **根因四分类**（改造时按类选路径）：①数据源缺失（公告/回购级催化、研报价值量测算、地缘新闻线——需新通道，prompt 层不可解）；②推理模式未入库（宏观三条件校验、宽度≠强度两步走、时点定价——走提案制/prompt 规则）；③规则优先级瑕疵（催化溯源被隔夜回落覆盖→规则23b）；④契约表达位不足（operation 无周末/时点粒度——v10 未改，候选 v10+）。
- **方向外推的结构性盲区**：盲判 directions 从昨日资金流外推，抓不到当日新主线诞生
  （8/21 实测：盲判推医药/通信，实际切到有色资源）。规则21（防御禁顺延）只覆盖一半，
  「主线切换预判」仍是 open gap。
做改造前必查的工程事实（08-14 部分已落地）：`scripts/limit_pool_fetch.py`（东财 push2ex，云环境可用、无需凭证、
不反爬）**已挂 cron `37 15 * * 1-5`**（wrapper `~/.hermes/scripts/qing_limit_pool_fetch.py`，job「涨停池拉取」），
`intraday_changes_fetch.py` 仍未挂；`dataset.py _load_emotion` 已补 `erban` 字段 + 连板梯队语义化（中文键
`连板梯队`/`二板池`）；SYSTEM_PROMPT 已加单位约定（成交额=亿、成交量=万手，禁「成交额X万手」跨单位表述）；
盘中分时量能仍完全缺失（腾讯日K只有成交量手），是「放量 vs 缩量」根因，需新数据源调研。

三个高频要求务必覆盖（2026-08-14 用户强调）：
- **操作建议是状态依赖的，不能写死进 prompt**（2026-08-14 用户明确纠正「不要盲目写死提示词，固化了提示词」）：
  UP 的「买阴不买阳」「做T压成本」「不要乱操作」是「周期位置 → 动作」的函数，不是常量——反弹初期加仓、
  反弹超预期(第9天)获利了结、趋势下跌买阴只是小仓位博弈、磨底期「不瞎操作」。把具体动作固化进 SYSTEM_PROMPT
  会让盲判在错误状态输出反向操作（反弹末期也喊「买阴不买阳」，而 UP 说「获利了结、不要急着表态」）。
  该沉淀的是「状态→动作」的映射关系（做成 pattern 判断步骤：先定位周期位置→再匹配动作），
  不是硬编码 conclusion。映射表见 reference 末尾「操作建议 × 周期位置映射」。
  ✅ **已落地（2026-08-14 晚，用户授权）**：`position_by_cycle` 挂入 `_CORE_PATTERN_IDS`（强制注入全文 4 步+4 证伪），
  契约 v4 新增 `operation{position/action/basis}` 输出字段 + prompt 规则7「先定位周期位置→按映射匹配动作→三条元规则校验」。
  早盘盲判重跑验证：`operation.position=震荡调整 → action=降低预期、控制操作频率`，动作由状态推导而非硬编码。
- **多天连续对比**：用户明确「分析不是一天的结论是多天连续变化的结果，盲判复盘不能只看一天」。
  对比必须串 ≥3 天盲判，看量能口径是否一致、directions 是否连续、有无「第 N 天/兑现时点」维度。
- **数据缺失诊断**：盲判 directions 全空 / 量能口径错乱时，先跑 `build_daily_pack(day)` 看
  `missing`/`stocks`/`emotion`，三连根因（is_cache_ready 误拦收盘补拉、KPL 无 cron、q_zrtj 字段错）
  见 reference 末尾「盲判数据缺失三连根因」。三连根因 **2026-08-14 均已修复**：
  ① `pre_fetch_klines.py` 收盘后窗口(post_close_window)跳过 `is_cache_ready` 幂等检查（早盘 mark ready 不再拦收盘补拉）；
  ② 挂 KPL cron「KPL每日数据拉取」`45 17 * * 1-5`（wrapper `~/.hermes/scripts/qing_kpl_daily_fetch.py`，`no_agent` 直接跑 `scripts/kpl_daily_fetch.py`，wrapper 内 source .env + 显式 CST 当天）；
  ③ `dataset.py` `_load_emotion` 成交额改用 `qscln`（当日）。

  附：`stocks_kline` 表里 `fetch_tdx_sector_klines.py` 写**裸码**、`pre_fetch_klines.py` 写**带后缀**（`000636.SZ`），
  两套格式并存——`build_daily_pack` 的 `get_klines_range` 用 `code=? OR code LIKE '%.%'` 兼容，但 stock_pool 带后缀与
  4588 条裸码全市场数据不匹配，排查「stocks 数量异常」时先看 code 格式。

## Prompt 规则演进工作流（v9→v10 实测，2026-08-21）

给 `blindtest/replay.py` 加新规则（如 v10 的规则25 宏观三条件、规则23b 催化兑现覆盖）的标准流程：

1. **TDD**：先在 `tests/investment_engine/test_validate_result.py` 追加 `Test<RuleName>` 类（触发/合规/无数据豁免三用例起步），跑红再实现。
2. **三处同步改**：① SYSTEM_PROMPT 规则正文（编号顺序不能乱——新规则追加在末尾；扩展已有规则用 `23b` 这类子编号插在原规则后）；② 模块级引用词常量（如 `_MACRO_CHECK_HINTS`，**必须放模块级**——patch 锚点若选在函数体内会把常量插进函数导致 IndentationError，选锚点前先确认目标行缩进为0）；③ `validate_result()` 内的机械校验分支。
3. **`PROMPT_VERSION` 递增**（v9→v10），否则产物版本号失真。
4. **真实数据冒烟**：用当天 `infra/data/global_macro/YYYYMMDD.json` 等真实落盘数据直接调 `validate_result()` 验证触发/通过两路（比只跑单测更接近实况）。
5. **全量测试跑不完是常态**：`pytest tests/` 约700用例 >10 分钟，前台必超时——用 `terminal(background=true, notify_on_complete=true)` 落日志到 /tmp 再查。已知预存问题：`tests/chan_engine/test_adapter_chanpy.py` 缺 `Chan` 模块收集报错，与盲判无关，可 `--ignore=tests/chan_engine`。
6. 改完同步本 SKILL.md 的契约版本行 + 提案文件沉淀在 `framework/proposals/`。

⚠️ 全量测试有未定位失败时**不要 commit**，下次会话先查上次日志尾部再继续。

**完整演进手册（含 factcheck 反向提取坑、`_CLAIM_TMPL` 双花括号转义、版本钉死断言同步、预存失败基线清单）已沉淀在 `references/prompt-rule-evolution-recipe.md`——演进前先读它。**

## 推理模式库（pattern）结构与新增流程（2026-08-14）

盲判 `used_patterns[]` 与 prompt 注入的模式正文，来自 `framework/reasoning-patterns.yaml`
（v3.0 来源中立；**框架数不固定，2026-08-15 时 11 个**——10 通用框架聚合自 116 个单 raw 模式
+ `position_by_cycle` 由提案制新增；框架会随提案制演进，`extract_reasoning_patterns.py` 已改
从 yaml 动态读框架列表，不再硬编码）。`pattern_id` 见各节首行。

- **盲判强制注入白名单** `_CORE_PATTERN_IDS = ("sentiment_cycle", "mainline_identification", "position_by_cycle")`（`blindtest/dataset.py`，08-14 position_by_cycle 已挂入）；
  `_load_core_patterns()` 只取这两个 pattern 的 `steps(name/action)` + `falsification`（不取 source_raw 等来源字段，防泄漏）。
  新增 pattern **默认不挂**白名单 = 仅 qing-agent 语义匹配召回；挂进去 = 盲判每篇复盘强制走该推导。
- **schema 校验**（`investment_engine/distill/pattern_schema.py::validate_patterns_file`）：
  必填 `pattern_id/name/description/trigger/data_requirements/steps/falsification/validation`；steps 每项必填 `step/name/question/action`；
  **决策字段（trigger/steps[].action/falsification）禁止 UP/青枫浦/博主**（来源中立，source_raw 不受限）；steps[].data 必须引用 data_requirements 的 name。校验命令：
  ```bash
  cd ~/learning-investment-strategies && PYTHONPATH=src .venv/bin/python -c "import yaml; from investment_engine.distill.pattern_schema import validate_patterns_file; validate_patterns_file(yaml.safe_load(open('framework/reasoning-patterns.yaml', encoding='utf-8')))"
  ```
- **自定义字段安全**：`nodes.py _ensure_patterns_cache()` 只整体 safe_load 存 dict，匹配时按需取 name/description/step_name，
  不遍历未知字段——`source_claims`（claim 溯源）这类自定义字段不会报错。
- **提名→转正**：`framework/proposals/` 是草稿区（.md 提案，`status: proposed` 待窗口验证）；转正走 `scripts/apply_pattern_proposal.py <proposal.yaml>`（人工评审后，--dry-run 预览）。
- **已落地**（2026-08-14）：`position_by_cycle`（周期位置→操作映射框架）入库（commit `a9644f5`）后，当晚已**挂入** `_CORE_PATTERN_IDS`（commit `85bdfa7`），
  把「操作建议 × 周期位置」映射 + 三条元规则（仓位纪律高于判断/确定性决定力度/兑现日磨底期克制）做成 4 步判断（定位周期位置→定性量价性质→按状态映射匹配→元规则校验），claim 溯源用 `source_claims` 字段。同步契约 v4 新增 `operation{position/action/basis}` 输出字段。
- **坑**：核实 claim 溯源时 `mcp__neo4j__search_claims_graph` 搜某些关键词（如「表态」「瞎操作」）会报
  `Object of type Date is not JSON serializable`（Neo4j 某字段 Date 类型序列化失败），改用 `mcp__qdrant__search_claims` 语义搜索绕过。
