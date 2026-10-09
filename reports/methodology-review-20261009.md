# 方法论复盘报告 2026-10-09（窗口：2026-09-26 ~ 2026-10-09，14 天，青枫浦上Q）

> 上期：methodology-review-20260919（窗口 08-30~09-18）。本窗口含国庆长假（10-03~10-06 无内容）。
> 执行动作：Step 5.5 批量提取（修复后重跑）+ Step 6 状态回填 61 条 + 新 B 类提案 1 份。

## 核心结论（5 条）

1. **本期最重要的框架增量：「暴跌互爆归因与救市需求判断」（融资融券三分法），已生成 B 类提案
   `framework/proposals/20261009-pattern-nomination-crash-loop-attribution.yaml`，用户当日人审拍板
   「证据已足」直接入库 reasoning-patterns.yaml v3.1（第 18 个框架），配套文档
   `framework/crash-loop-attribution.md`，数据通道 `marketdata.get_margin_balance()` 已落地**。
   10-09 UP 用融资余额走向完成了一次完整的下跌归因：融资余额仍在增加（10-08 融资净买入 +41.39 亿）
   =散户还在加仓→排除融资盘互爆；外围平稳→排除外围传导；龙虎榜机构抱团撤退+机构重仓股领跌
   →定性为纯内部机构互爆（险资/社保/公募/私募/FOF/量化卡风控线、赎回线相互踩踏）；进而推出
   「跌出来的风险只能由 GJD 级买入打破」（claim-20261009-002-e/f/g）。该逻辑与 7 月杠杆恐慌剧本
   （两融 3.1 万亿新高→杠杆平仓螺旋）、7-19~21 国家队托底判定形成跨 regime 证据链，
   现有 17 个框架无一覆盖（最接近的 fund_flow_segmentation 讲的是普涨日资金结构，且仍为空壳），
   属框架演进信号，走提案制而非直接入库。

2. **Step 5.5 批量提取修复并跑通：修复 llm_client hermes_global 通道 temperature=0.3 与 k3
   不兼容问题（k3 仅允许 temperature=1），重跑后 20 个候选文件合并 10 个新 examples，
   0 落 others**——现有框架对本窗口内容覆盖力良好。但 4 个空壳框架（volume_surge_fade /
   volume_source_qualify / fund_flow_segmentation / board_break_nature）自 09-01 标记以来
   两轮提取仍为 0 examples，缺口原因同前：需要分时量能/资金流/断板盘口类 raw，
   普通复盘专栏喂不出来，维持标记。

3. **窗口主线叙事为「节前磨底→节后暴跌→机构互爆定性」三段演化**。9-27~9-30 节前缩量磨底
   （缩量两面看、修复确认三条件、节后布局三信号）→ 10-08 节后首日科技暴跌（源杰科技黑天鹅
   触发、情形 A/B 应对框架）→ 10-09 归因定型为机构互爆并提出 GJD 救市需求。UP 应对纪律
   同步演进：10-08 给出「2.2 万亿前科技不开新仓、站稳 2 万亿滚动做 T」的明确数字阈值纪律。

4. **矛盾 8 对，0 true-conflict、0 agent-up-conflict，无需用户裁决**。最重两对：
   ①10-09 机构互爆归因 contradicts 9-28「节前风险敞口收缩」归因——随下跌演化归因修正，
   属 correction/cycle-shift（9-28 归因只解释了节前段）；②10-08「科技现阶段没有趋势了」
   contradicts 10-01「科技进入主题投资→产业验证验证窗口」——对科技定性进一步转谨慎，
   属 cycle-shift，科技方向 claims 不标过期。另注意 10-08 中文在线补仓（operation）与
   9-08 减仓计划方向反转，属 UP 个人账户操作层面变化。

5. **A 类操作纪律候选 1 组达标**：claim-20261008-002-b「量能阈值仓位门控」（2.2 万亿/2 万亿
   双阈值），满足门槛第 1 条（明确规则+具体数字）且已在 Step 5.5 中作为
   volume_threshold_position_gating 归入 position_by_cycle 框架（examples 7→8）。
   建议经 Review→Write 管道写入 `framework/trading-rules.md`（该文件自 08-22 起未更新，
   上期累计候选也未写入，缺口持续扩大）。

## 数据统计

- 窗口内 claims：**276 条**（20 个文件）
- 按日分布：10-08(69) / 09-29(47) / 09-27(44) / 09-28(42) / 10-09(26) / 09-30(18) /
  10-07(13) / 10-01(12) / 10-02(5)
- claim_type：sector-theme 85 / methodology 65 / market-cycle 59 / operation 29 /
  macro 16 / technical-signal 10 / risk 5 / stock-view 3 / technical-knowledge 2 / catalyst 2
- confidence：high 179（65%）/ medium 97
- supersedes 59 条 / contradicts 8 条；Step 6 机械回填 superseded 61 条
  （47 个文件，`logs/status_backfill_report.txt`）

## 主题漂移（三阶段）

| 阶段 | 日期 | 性质 | 要点 |
|------|------|------|------|
| 节前缩量磨底 | 09-27~09-30 | no-change + clarification | 缩量两面看（以价格区分卖压衰竭/买盘不足）、修复确认=收盘站回+上涨家数+科技核心共振、节后布局需三信号同时确认；外盘只提供开盘定价线索（permanent） |
| 节后首日暴跌 | 10-07~10-08 | correction | 科技暴跌触发=源杰科技黑天鹅（contradicts 7-14 韩股链条归因口径）；应对=情形 A/B 框架+量能阈值门控；供给约束题材逻辑硬度>轮动题材 |
| 机构互爆定性 | 10-09 | extension（新推理链） | 融资余额三分法归因→机构互爆→GJD 救市需求；「指数定环境、板块定方向、个股定时点」共振三判据 |

核心纪律全程稳定：不见量价确认不追、单一信号不构成转强证据、情形 A/B 预案式应对。

## 矛盾分类汇总

| 发起 claim | 对象 | 分类 | 说明 |
|---|---|---|---|
| claim-20261009-002-f | claim-20260928-002-b | correction/cycle-shift | 下跌归因从「节前风险敞口收缩」修正为「机构互爆」（只解释节前段，非全程错误） |
| claim-20261008-003-f | claim-20261001-001-g | cycle-shift | 科技定性：「产业验证窗口」→「现阶段没有趋势」，转谨慎非证伪 |
| claim-20261008-007-w | claim-20260816-003-010 | risk-repriced | 汇率：央行「不预设目标、防范超调」覆盖 8-16「破 6.7 进升值阶段」预判 |
| claim-20261002-001-e | claim-20260827-062-x | risk-repriced | 联储鸽派盖过鹰派，加息预期退潮（旧 claim 已 superseded） |
| claim-20260928-001-c | claim-20260909-001-a | clarification | 美股外部约束口径细化（油价回落但美债约束未消失） |
| claim-20260929-003-c | claim-20260923-002-b | clarification | 节前「梦想方向布局窗口」与「老方向反弹有限」分层并存，非真矛盾 |
| claim-20261008-005-a | claim-20260714-001-ad | 非矛盾（不同事件归因） | 10-08 暴跌（源杰黑天鹅）与 7-14 暴跌（韩股链条）是两次不同事件 |
| claim-20261008-006-b | claim-20260908-005-5 | cycle-shift（operation） | 中文在线从计划减仓转为补仓，UP 个人账户操作变化，提示关注 |

## Durable Rule 筛选

- **B 类（推理模式）**：本期生成 1 份提名提案（crash_loop_attribution，见核心结论 1）。
  证据窗口 2026-07-02~2026-10-09（约 14 周 ≥4 周门槛✓），出现于两种下跌剧本
  （7月杠杆恐慌/10月机构互爆，均属恐慌调整大类但互爆主体与数据特征不同）；
  完整三分归因+救市判断链 10-09 首次成体系出现，建议维持 pending-review，
  待下一次暴跌场景盲判验证后转正。
- **A 类（操作纪律）**：「量能阈值仓位门控」（2.2 万亿/2 万亿，claim-20261008-002-b）
  达标待写入 trading-rules.md。
- 上期 pending-review 的「涨价幅度=国产化率倒序表」本窗口无新证据，维持 pending-review。

## Step 5.5 批量提取结果

- 首轮因 llm_client hermes_global 通道 temperature=0.3 与 k3（api.kimi.com/coding 仅允许
  temperature=1）不兼容全部 LLM 调用失败；已修复（temperature=1）并重跑。
- 重跑结果：20 候选 → 10 新 examples（position_by_cycle +2、sentiment_cycle +2、
  mainline_identification +1、technical_timing +1、operation_strategy +1、
  sector_rotation +1、ai_industry_chain +1、upstream_cycle…详见 state 文件）、
  0 新框架、0 落 others。
- 空壳框架仍为 4 个（volume_surge_fade / volume_source_qualify / fund_flow_segmentation /
  board_break_nature），缺口=盘口级 raw，维持标记。

## 后续建议

1. ~~crash_loop_attribution 提案人审~~ **已完成（当日拍板入库 v3.1 + 配套文档 + 数据通道）**。
   后续观察点：下一次暴跌场景用该框架盲判验证，回填 validation.historical_hit_rate。
2. 「量能阈值仓位门控」写入 trading-rules.md（Review→Write 管道，需用户确认后执行）。
3. ~~两融数据通道~~ **已完成**：`qing_investment.marketdata.get_margin_balance(days=N)`，
   东财 RPTA_WEB_MARGIN_DAILYTRADE，实测与 UP 截图口径吻合。
