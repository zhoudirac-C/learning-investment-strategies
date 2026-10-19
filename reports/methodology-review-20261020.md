# 方法论复盘 2026-10-20（窗口：2026-10-07 ~ 2026-10-20，14天）

> **来源归属更正（本版修订）**：首版误将 21 条「卢本圆复盘」(up_id=550494308, school=watchlist) 与 11 条「像鳄鱼一样思考」(gator-ecyu-0001, school=gator) 混入青枫浦上Q 的复盘口径，导致"2.2万亿量能总开关"被误判为 UP 的 durable rule。本版只以 **up_id=1420210197 (school=qing)** 的 378 条为准，其余 32 条单列并排除。

## 核心结论

1. **有效样本 378 条**（总 410 条，剔除非 UP 来源 32 条）。分布：sector-theme 129、market-cycle 88、methodology 84、operation 37、macro 18、technical-signal 7、risk 5、stock-view 3、catalyst 2、technical-knowledge 1（近似）。主题高度集中在「调整市的承接与量能质量验证」。

2. **✅ 唯一达标的 durable rule 候选（A类，建议入 trading-rules.md）**：
   **「加仓标准两段论」**（10-09，claim-20261009-001）：60分钟底部**钝化**只说明下行动能可能减弱（随后仍可能延长或消失），不等于买点；只有**钝化发展为底部结构形成**才进入既定加仓标准，不把一次急拉当成结构完成。
   - 支撑：10-13 再次出现「序列是观察窗口、钝化是动能线索，需价格与成交配合，不因序列临近完成就提前确认见底」；10-15「结构未成不以猜底加仓」。
   - 判据：直接回答"现在能不能加"，且有明确阈值（钝化→结构），跨 3 个交易日重复。

3. **🆕 推理模式提名候选 1：股票+信用双市场验证框架**（10-18，claim-20261018-002 三条）：
   「股价反弹 + CoreWeave 类高资本开支企业债券价格企稳 + 信用利差持续收窄 = 真企稳；股价短暂反弹后再下探 + 信用利差继续扩大 = 假反弹」。配套观点：科技调整与普通估值回撤的关键差异在**信用风险**（估值压缩只影响价格，信用风险影响企业能否创造未来利润）。
   - 现有 18 框架无此维度（macro_transmission / ai_industry_chain 均只覆盖股价与订单）。
   - **门槛状态**：窗口内出现 1 次（10-18），另有 10-15「CoreWeave 等高收益债利差是否继续走阔」作为跟踪变量佐证 → 计 2 次、但同处"调整"这一 regime，**未满足≥2 种市场阶段**。建议建提案 `pending-review`，不入库。

4. **📌 ETF 放量≠净流入：应并入现有框架（非新框架）**：10-11、10-12、10-16、10-19 共 4 次重复（均为 UP 本人），核心是「ETF 成交额只反映交易活跃度；净流入须看基金份额变化+申赎；新增开户数≠入市资金」。现有 `volume_source_qualify` 覆盖"量能来自存量换手 vs 增量入场"，但**缺 ETF 份额/申赎通道**——建议作为 example + data_channel 增补。

5. **补充候选（门槛未达，留 wiki 观察）**：
   - 「底部永远分化：普涨只是打底，超额来自先走完下跌周期、结构先稳住的抗跌品种」（10-18）——与 `volume_source_qualify` / 强者恒强部分重叠，但"抗跌品种=下轮主线"是独立推论，单次出现。
   - 「美债转强看数据公布后收益率反应方式而非数据好坏」（10-14）：CPI 超预期但收益率回落 = 买盘增强；符合预期但收益率涨 = 预期已透支。该条与 macro_transmission 已有框架接近，属 clarification。
   - 「承接三条：放量回升+回落抛压减轻；放量在下跌段+反抽无量=兑现」（10-19）——既有框架已覆盖，no-change。

6. **Step 5.5 批量提取已执行**：窗口内 75 个候选 raw 文件，处理 20 个，新增 6 个 examples（technical_timing / mainline_identification / operation_strategy 等），无 others 落袋告警 → 无框架改造信号。reasoning-patterns.yaml +361 行。

7. **矛盾分类**：本窗口**无 true-conflict**。4 条 claim 已标 superseded，无悬空引用问题。存量待办：29 条 superseded 待机械回填、199 条 contradicts 待人工裁决（非本窗口新增）。

## 非 UP 来源 claim（排除，32 条）

| 来源 | up_id | 条数 | 处理建议 |
|------|-------|------|---------|
| 卢本圆复盘（watchlist） | 550494308 | 21 | **schools.yaml 标注"仅通知，不进 claim 库"** —— 建议核查提取管线为何入库；其内容（2.2万亿门槛、AI漫剧、国瓷T操作）不得进入 UP 框架 |
| 像鳄鱼一样思考（gator） | gator-ecyu-0001 | 11 | 属双轨制第二学派，方法论复盘应走 gator 独立口径，不混入 qing |

> ⚠️ **红线**：2.2 万亿"科技仓位总开关"来自卢本圆，**不是 UP 的方法论**。UP 本人的仓位门槛是「60分钟底部结构形成」，两者不可互换。首版报告的结论 2 已作废。

## 建议后续动作（按序）

1. **A类写入**：`trading-rules.md` 增加「加仓门槛：60分钟钝化≠结构形成」条目，引用 claim-20261009-001 / claim-20261013-001。
2. **B类提案**：新建 `framework/proposals/20261020-pattern-nomination-equity-credit-dual-verify.yaml`（status: pending-review，附 10-15 + 10-18 证据），不入库。
3. **example 增补**：ETF 份额/申赎验证口径并入 `volume_source_qualify`（数据通道 + example）。
4. **管线缺陷修复**：核查 watchlist school 的 claim 为何进入 `knowledge/claims/`（schools.yaml 明确写"不进 claim 库"），并清理 21 条卢本圆 claim 或迁移至独立库。
5. 存量：跑 `backfill_claim_status.py` 落地 29 条 superseded。
6. 同步：yaml 变更后走 qing-learning-sync 重建 Qdrant。
