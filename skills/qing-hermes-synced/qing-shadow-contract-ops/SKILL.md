---
name: qing-shadow-contract-ops
description: |
  影子盲判契约演进的操作手册（qing-shadow-dual-track 的只读限制下使用的执行层补充 skill）。
  覆盖：把新 reasoning pattern 挂进盲判（_CORE_PATTERN_IDS + prompt + parse_result + 版本号）、
  新增输出字段、验证（泄漏/解析/注入）、重跑早盘/复盘盲判。
  触发词：挂进盲判、挂 pattern、新增 pattern 进盲判、盲判契约、新增字段、operation 字段、
  position_by_cycle、PROMPT_VERSION、改盲判提示词、重跑盲判。
---

# qing-shadow-contract-ops

`qing-shadow-dual-track` 是只读伞技能（定位产物/补跑/断档排查），盲判契约与 pattern 挂载的
改动步骤沉淀在此。别去 patch 只读的 qing-shadow-dual-track——改法照本 skill 走。

## 背景：pattern 先建后挂，两步走

`position_by_cycle`（周期位置→操作映射）2026-08-14 的落地过程是标准范式：

1. **先建 pattern**：写进 `framework/reasoning-patterns.yaml`（含 steps/falsification/source_claims），
   独立 commit，但**暂不挂 `_CORE_PATTERN_IDS`**——commit message 写「不挂 _CORE_PATTERN_IDS，先审颗粒度」。
2. **用户确认后再挂**：用户一句「挂进盲判」= 确认注入，此时才改下面四步。

这样把「建 pattern」与「强制注入」解耦，颗粒度/字段先审后动。

## 挂新 pattern 进盲判（四步，改 4 个文件）

| 步 | 文件 | 改动 |
|----|------|------|
| 1 | `src/investment_engine/blindtest/dataset.py` | `_CORE_PATTERN_IDS` 追加 `pattern_id`（强制注入全文） |
| 2 | `blindtest/replay.py` + `shadow/premarket.py` 的 SYSTEM_PROMPT | 规则2 把新 pattern 加入「必须逐条对照」清单；JSON 契约新增输出字段；末尾加推导规则（如规则7） |
| 3 | `blindtest/replay.py` `parse_result` | 新字段规范化——这是唯一规范化入口，premarket 复用同一函数 |
| 4 | `blindtest/replay.py` `PROMPT_VERSION` | +1（v3→v4） |

### 关键约束（踩坑点）

- `_load_core_patterns` 只取 `steps[].name/action` + `falsification`，**不取 source_raw**。
  新 pattern 的 name/steps/falsification 必须来源中立（禁 UP/青枫浦/博主），否则 `assert_no_leakage`
  报 `prompt 含来源指称`。来源证据写 `source_claims`（claim ID），不泄漏也不进 prompt。
- 新增输出字段**必须三处同步**：两处 SYSTEM_PROMPT 契约 + parse_result。漏一处 → 字段被 parse 丢弃
  或 LLM 不输出；只改 replay 不改 premarket → 早盘盲判拿不到新字段。
- **别把具体动作写死进 prompt**（用户 2026-08-14 明确纠正）。正确做法：写「状态→动作」映射 pattern +
  推导规则（先定位状态→按映射匹配动作→元规则校验），让 AI 自判状态再推动作。禁止脱离状态写
  「逢低关注/降低仓位」这类无状态依赖套话。

## 验证（改完必跑，一条命令）

```bash
cd ~/learning-investment-strategies && PYTHONPATH=src .venv/bin/python -c "
import json
from investment_engine.blindtest.dataset import _load_core_patterns, _CORE_PATTERN_IDS
from investment_engine.blindtest.replay import parse_result, PROMPT_VERSION
print('v', PROMPT_VERSION, '| core', _CORE_PATTERN_IDS)
s = json.dumps(_load_core_patterns(), ensure_ascii=False)
print('leak', [k for k in ('UP','青枫浦','博主') if k in s])   # 必须空
print('parse_op', parse_result(json.dumps({'market_stage':'震荡','operation':{'position':'反弹中段','action':'持股做T','basis':'缩量回调'}}))['operation'])
"
```

三项全绿（版本号对 / 注入成功 / 无泄漏 / parse 正常）再重跑。

## 重跑盲判（含幂等跳过坑）

```bash
cd ~/learning-investment-strategies
rm -f evals/shadow/predictions/{day}-pre.json        # ⚠️ 必须先 rm：run_predict_premarket 对已存在且 status 非 error 的记录返回 skipped，不覆盖旧结果
set -a && source .env && set +a                      # 需 DEEPSEEK_API_KEY（脚本不 source .env）
.venv/bin/python scripts/shadow_premarket.py --date {day}   # 早盘（预测当日）
.venv/bin/python scripts/shadow_daily.py --date {day}       # 复盘（判当日）
```

重跑前确认三样齐备（缺则静默 no_data 或漏数据）：①T-1 个股/指数 K 线（`build_daily_pack` 依赖，见
qing-shadow-dual-track 的补 K 线顺序）②早盘需 `infra/data/overnight_us/{day}.json` ③复盘需 `predictions/{prev}.json`
（`_load_prior_summary` 注入连续状态）。

## 当前契约状态（v5，2026-08-14 起）

- `_CORE_PATTERN_IDS = ("sentiment_cycle", "mainline_identification", "position_by_cycle")`（3 个核心模式全文）
- 输出字段：`market_stage` + `nature` + `operation{position,action,basis}` + **`cycle_state{rebound_day,bottom_level,bottom_date,theoretical_window,note}`**（反弹天数连续追踪）
- 数据包新增两块：`structure`（多指数顶底结构）+ `intraday_amount`（盘中量能形态）

## cycle_state：反弹天数连续追踪（v5 核心，2026-08-14 跑通）

`cycle_state` 让盲判「第二天引用前一天就知道反弹到第几天」，不每天孤立判断。字段：
`rebound_day`（从底部结构形成日算的交易日数，整数/null）+ `bottom_level/bottom_date/theoretical_window`（底部结构级别/形成日/理论窗口）+ `note`。

**⚠️ 关键根因（踩了一整晚才定位）**：UP 的「6-8天反弹」是**科技类指数（科创/创业板）的 90min 底部结构**，不是上证大盘的。上证同期只有 60min 单级别（理论 2 天，V 形反转无底背离）。本地无 sh000688 分钟数据 → 用**创业板指 sz399006** 近似（同为科技成长）。之前 cycle_state 一直 `rebound_day=null` 就是「用上证做结构识别」——上证 60min 理论才 2 天，LLM 看到「2天反弹」判成已结束。改用创业板指 90min 后跑通：`rebound_day=10 / bottom_level=90min / theoretical_window=6-8天`。

- `_load_structure` 多指数循环：`_STRUCTURE_INDEXES = (("sh000001","上证指数"), ("sz399006","创业板指"))`，输出 `{指数名: {级别: 结构}}`。
- `recent_bottom/recent_top`（`detect_structure` 返回）：追踪「最近一次结构形成」（背离+金叉/死叉确认），即使当前已不在背离状态也能定位反弹起点（解决冷启动）。**必须过滤时间范围**（只保留最近 60 天内）——否则 daily 的 3 月前历史底部结构会干扰 LLM 判断「当前反弹周期」。
- 级别→理论天数映射（UP 方法论，来源 claims）：30min底=3天 / 60min底=2天 / **60+90min共振=6-8天** / 120min底=12天 / 120min双顶=4-6天 / 90min顶=8天。
- **MACD 必须自算**（`structure.py::compute_macd`）：`index_klines` 表里 dif/dea 是增量更新时算的、历史 close 覆盖后不重算，已漂移（实测自算 49.8 vs 表 39.7）。MACD EMA26 需 ≥26 根历史，读 K 线要拉 ≥100 根。

## intraday_amount：盘中量能形态（B2 落地）

`_load_intraday_amount(day)` 用 TDX 拉上证+深证 60min amount，构建「开盘预估全天 → 尾盘实际」：
预估全天 = 累计 × (240/已交易分钟)，60min 4 根时点 10:30/11:30/14:00/15:00。形态定性：开盘预估 > 尾盘实际×1.2 = 冲量滑落（全天缩量）。数据源细节见 `tdx-data-source-troubleshoot`（上证+深证 60min 累加 = 两市成交额，误差 0.007%）。

配套 SYSTEM_PROMPT 规则 9：量能定性**必须用盘中形态、禁止收盘环比**。效果：stage_reason 从「放量18.5%」（收盘环比，错）纠正为「冲量滑落全天缩量」（盘中形态，对，对齐 UP「看似放量实则全天缩量」）。

## prompt 迭代坑（改 SYSTEM_PROMPT 必看）

- **LLM 不听话 → 用「禁止写 X 结论」强措辞，别用「建议用 Y」**。规则 9 从「必须用盘中形态」迭代到「禁止写『成交额X亿较前日Y亿放量/缩量Z%』这类纯环比结论」才生效——因为 emotion 块里 `两市成交额_亿` 与 `昨日两市成交额_亿` 两个现成数字，LLM 会习惯性算环比，只有「禁止」才拦住。
- **三引号字符串 patch 加全角括号会 SyntaxError**：多条规则共用一个 `"""..."""` 字符串时，只有最后一条结尾有 `"""`。patch 时若在中间规则结尾误加 `"""`，字符串提前关闭、后续行变代码（中文全角括号报 invalid character）。改完必跑 import 验证。
- 新增字段**三处同步**（replay SYSTEM_PROMPT + premarket SYSTEM_PROMPT + parse_result），漏一处字段被 parse 丢弃或 LLM 不输出。
