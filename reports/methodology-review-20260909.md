# 方法论复盘报告 2026-09-09（窗口：2026-08-26 ~ 2026-09-08，14 天）

## 核心结论（5 条）

1. **17 个顶层框架在窗口内无新增，framework 层未发生结构性更新**。8/26 以来
   `reasoning-patterns.yaml` 的 17 个 pattern_id（upstream_cycle / mainline_identification /
   sector_rotation / macro_transmission / sentiment_cycle / technical_timing / earnings_analysis /
   ai_industry_chain / operation_strategy / position_by_cycle / others / volume_surge_fade /
   volume_source_qualify / position_context_qualify / fund_flow_segmentation / board_break_nature /
   promotion_rate_benchmark）保持稳定，新增内容均通过 `framework/proposals/` 提案制
   走 patch-note 合并进现有框架 examples（8/26 ~ 9/5 共 10 份提案，多为 glossary / pattern patch）。

2. **上期（8/22）提名的 6 条 A 类操作纪律已全部落盘** `framework/trading-rules.md`：
   - 急跌不接飞刀与买阴不买阳纪律（claim-20260809-030、claim-20260820-027）
   - 量能档位与整数量能位纪律（claim-20260818-006、claim-20260812-028）
   - 离场标准后移纪律（claim-20260818-050、claim-20260818-051）
   - 周末持仓成本纪律（claim-20260814-019、claim-20260821-021）
   - 减仓节奏纪律（claim-20260820-028、claim-20260820-030）
   对应 8/22 报告中的 ❌ 未收录项已全部转为 active。A 类候选池当前清零。

3. **窗口内新增 B 类推理模式候选 3 条（均 permanent/high，现有 17 框架装不下，建议走提案制）**：
   - **claim-20260826-016-a 涨价幅度=国产化率倒序表**：用涨价幅度倒序表反推国产化率，
     给"涨价≠国内厂商利润"提供可证伪的量化锚点。与 upstream_cycle / upstream_price_cycle_qualify
     互补但不重合，建议新增 pattern_id: price_increase_domestication_inverse。
   - **claim-20260901-016-a 攻而不克把犹豫筹码变卖盘主动回撤变观望**：区分"被动攻而不克"
     与"主动回撤"两种筹码结构，是 position_context_qualify（位置决定意义）的下游延伸，
     建议作为该框架的 example 合并而非独立框架。
   - **claim-20260908-003-d 先定位调整位置再等量价确认**：强调"先识别调整发生在哪个位置，
     再等待量价确认"，比"预设调整只剩几天"更有意义。与 position_context_qualify 的
     "先定位置再定性"同源，但扩展到调整段（非中阳段），建议作为该框架的 example 合并。

4. **观点漂移弧在窗口内完成一次完整闭环**：科技主线从"硬件端向上游延伸"（8/30 超节点价值扩散）
   →"按位置与催化重新分配资金"（9/8 科技内部重新分配）→"修复强度暂不作过高预设"（9/8 明日基准
   情形先分歧再观察修复）。UP 对科技的定性从"进攻"转向"观察修复"，但操作纪律（买阴不买阳、
   不见量价确认不追）全程稳定，未出现 methodology 级漂移。

5. **矛盾与证伪集中在 macro 与 sector-theme 层，methodology 层 0 矛盾**：
   - 窗口内 29 条 contradicts 发起方中，methodology 类仅 1 条（claim-20260904-025 缩容环境聚焦单一主线
     contradicts 5/18 的"多主线轮动"），属 cycle-shift 而非 logic-broken。
   - 被 supersedes 最集中的老观点是 claim-20260819-007（6 次，8/19 大跌当日的"全球同源抛售第四棒"
     定性），已被后续内生性回调框架（claim-20260830-003-a、claim-20260903-024-a）逐步替代。
   - 无 true-conflict / agent-up-conflict 需用户裁决。

## 数据统计

- 窗口内 claims：**510 条**（8/26 ~ 9/8，12 个交易日 77 文件）
- 按日分布：8/27(69) / 9/1(65) / 8/31(59) / 8/26(51) / 9/3(43) / 9/4(39) / 9/8(38) /
  9/2(36) / 8/30(35) / 9/7(30) / 8/28(24) / 9/6(21)
- claim_type：sector-theme 134 / market-cycle 105 / operation 61 / stock-view 61 / catalyst 46 /
  **methodology 37** / macro 31 / risk 17 / technical-signal 16 / technical-knowledge 2
- confidence：high 377 / medium 131 / low 2
- timeframe：short-term 308 / intraday 74 / trend 74 / industry 29 / **permanent 25**
- 关系边：supersedes 204 条发起、contradicts 29 条发起

## 窗口内观点主线叙事（按日轨迹）

- **8/26（缩量止跌，观察窗口）**："顶部结构第六天无明确低点"（claim-20260826-001-a），
  "地量后首次放量判据"（026-a），"今日双情形框架"（007-a）——以观察为主，无方向结论。
- **8/27（晋级率确认，情绪修复）**："晋级率过线加跌停归零确认行情延续性"（claim-20260827-007-a），
  直接 contradict 8/24 的"首板腰斩宽度先塌"——情绪从冰点转修复。
- **8/28（反弹最健康一天）**："8月27日为本轮反弹最健康一天，今日任务是维持"（claim-20260828-007-a），
  量能合意区间 2.2-2.5 万亿。
- **8/30-8/31（内生性回调定性）**：8/30 明确"8月28日回落定性为内生性回调而非外力扰动"
  （claim-20260830-003-a）；8/31 补充"周五冲高回落与7月10日同结构不同量，不定性为破位"
  （claim-20260831-007-a），同时"银行煤炭再新高非防御是提前布局指数反转预期"（005-h）。
- **9/1（4000 点关口，三条件降仓框架）**："3990.3、4000整数关口、潜在高9高点三者位置重合，
  要同时满足技术高9、冲关过不去、成交量被动放大，才要降仓位"（claim-20260901-030-a）——
  这是窗口内最重要的 methodology 级操作纪律更新。
- **9/2-9/3（最后一踩，冰点观察）**："指数缩量阴线属于最后一踩"（claim-20260902-004-a），
  "冰点之后重点观察风格切换而非抢筹"（claim-20260903-027-a）。
- **9/4（缩容环境，聚焦单一主线）**："缩容环境聚焦单一主线"（claim-20260904-025），
  contradict 5/18 的多主线轮动框架，属 cycle-shift。
- **9/6-9/7（非农+CPI 节奏，科技定价逻辑切换）**："非农偏强未点燃通胀恐慌估值压制有边界"
  （claim-20260906-001-a），"AI硬件定价逻辑切换为利率加盈利确定性"（claim-20260907-002-a）。
- **9/8（先分歧再观察修复，方法论收尾）**："先定位调整位置再等量价确认"
  （claim-20260908-003-d）——窗口内最后一条 permanent methodology，与 9/1 的"三条件降仓"
  形成"位置-条件-动作"的完整闭环。

## 观点漂移与矛盾分类

| # | 案例 | 分类 | 说明 |
|---|------|------|------|
| ① | claim-20260809-016（医药主动领涨）→ 8/26 被 contradict "医药过渡方向未成立" | **cycle-shift** | 8/22 报告已标记该观点进入兑现完毕阶段，窗口内正式闭环 |
| ② | claim-20260819-007（全球同源抛售第四棒）被 6 次 supersedes | **cycle-shift** | 8/19 的恐慌定性被后续"内生性回调"框架（8/30、9/3）逐步替代，属市场阶段变化而非逻辑证伪 |
| ③ | claim-20260518-018（多主线轮动）被 claim-20260904-025（缩容环境聚焦单一主线）contradicts | **cycle-shift** | 5 月震荡市的多主线轮动在 9 月缩容环境下不再适用，UP 主动修正为"聚焦单一主线" |
| ④ | claim-20260827-061-x（黄金与农业同步走强改变防御属性）被 claim-20260901-011-a（黄金4416支撑与4501阻力）contradicts | **timeframe-shift** | 8/27 的"防御属性改变"是短期情绪判断，9/1 回到技术位跟踪，属正常 timeframe 分层 |
| ⑤ | claim-20260824-002-k（液冷作为科技先锋）被 claim-20260902-012-a（液冷充当科技先锋并外溢至金刚石）contradicts | **extension** | 液冷逻辑从"先锋"扩展到"外溢至金刚石"，属同一逻辑的延伸而非反转 |

**true-conflict / agent-up-conflict：本期为 0**，无需用户裁决的矛盾。

## Durable Rule 候选（A 类操作纪律）

窗口内新增 A 类候选 **0 条**——上期提名的 6 条已全部落盘，窗口内未出现新的
"明确规则+多次重复+改变操作纪律"三条件同时满足的 A 类候选。

现有 trading-rules.md 的 31 条 active 规则已覆盖窗口内所有操作纪律表述
（买阴不买阳、不见量价确认不追、三条件降仓、周末持仓成本、大涨大减小涨小减等）。

## 新方法论信号（B 类推理模式，8/26~9/8 增量）

对照 17 个现有顶层框架，以下 3 条 permanent/high methodology claims 未被完全覆盖：

| 信号 | claim | 与现有框架关系 | 建议动作 |
|------|-------|---------------|---------|
| 涨价幅度=国产化率倒序表 | claim-20260826-016-a | upstream_cycle / upstream_price_cycle_qualify 关注"涨价真实性"与"受益标的筛选"，但未提供"涨价幅度→国产化率"的反向映射工具 | **新增提案** `framework/proposals/2026-09-09-pattern-price-increase-domestication-inverse.yaml` |
| 攻而不克把犹豫筹码变卖盘 | claim-20260901-016-a | position_context_qualify 的"先定位置再定性"可覆盖，但缺少"被动攻而不克 vs 主动回撤"的筹码结构区分 | **合并为 example** 进 position_context_qualify |
| 先定位调整位置再等量价确认 | claim-20260908-003-d | position_context_qualify 聚焦"中阳定性"，该 claim 扩展到"调整段定位"，是同一方法论的互补场景 | **合并为 example** 进 position_context_qualify |

其余 34 条 methodology claims 均可归入现有框架：
- 宏观传导类（美债对A股传导路径、晚间美国数据是次日开盘定价输入）→ macro_transmission
- 操作纪律类（三条件同时满足才降仓、开盘不卖即是赌、模式交易价值）→ operation_strategy / position_by_cycle
- 产业分析类（光模块参与框架从无到有、超节点价值扩散、存储涨价对国产链）→ ai_industry_chain / upstream_cycle
- 情绪/技术类（确认底部与确认走强是两件事、冰点之后观察风格切换）→ sentiment_cycle / technical_timing

## 一致性检查

- **status 生命周期**：窗口内 204 条 supersedes 发起、29 条 contradicts 发起，
  但 `knowledge/claims/` 中旧 claim 的 status 字段仍全部为 active，未执行机械回填。
  建议运行 `.venv/bin/python scripts/backfill_claim_status.py --dry-run` 预览后执行。
- **framework 与 claims 一致性**：trading-rules.md 的 31 条规则与窗口内 claims 无冲突；
  reasoning-patterns.yaml 的 17 框架与窗口内 37 条 methodology claims 无结构性矛盾。

## 建议后续动作

1. **提案制入库**：将"涨价幅度=国产化率倒序表"按 B 类推理模式提名门槛生成提案
   `framework/proposals/2026-09-09-pattern-price-increase-domestication-inverse.yaml`，
   待 4 周窗口 + ≥2 种市场阶段验证后人审入库。
2. **Example 合并**：将"攻而不克"与"先定位调整位置"两条 claim 作为 examples 合并进
   `position_context_qualify` 框架，由 Step 5.5 批量提取脚本 `extract_reasoning_patterns.py --incremental`
   在下次运行时自动处理（或手工 patch）。
3. **Status 回填**：运行 `backfill_claim_status.py` 处理 204 条 supersedes 与 29 条 contradicts
   的 status 生命周期，保持 Neo4j 图谱与文件层一致。
4. **持续观察**：9 月中下旬是 UP 定义的"本月唯一做多窗口"（claim-20260904-033），
   下一期复盘（9/16）应重点跟踪该窗口内的观点验证情况。

---

*报告生成：2026-09-09，基于 qing-learning-review skill 9 步流程手工执行*
*数据来源：knowledge/claims/ 510 条（8/26~9/8）、framework/reasoning-patterns.yaml（17 框架）、framework/trading-rules.md（31 规则）*
