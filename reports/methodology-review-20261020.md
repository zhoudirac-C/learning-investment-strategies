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

---

## 执行记录（2026-10-20，动作 1/2 已落地）

### A类：已写入 framework/trading-rules.md

新增章节 **「加仓门槛：底部钝化不等于结构形成」**（含关联索引 + 更新记录）。

- 依据：claim-20261009-001、claim-20261013-001、claim-20261015-001（均为 up_id=1420210197）
- 核心：钝化只说明下行动能可能减弱（可延长/消失）→ 不构成加仓依据；只有钝化发展为底部结构形成（配合价格回收 + 成交改善）才进入加仓标准
- 明确写入"常见误用"：把钝化直接读成买点，在第一段满仓
- ⚠️ 已记录：「2.2 万亿量能开仓门槛」经核非 UP 本人表述，**未收录**

### B类：已建提案（pending-review，未入库）

`framework/proposals/20261020-pattern-nomination-equity-credit-dual-verify.yaml`

- 候选模式：`equity_credit_dual_verify`（股价与信用双市场验证）
- 证据：10-15（CoreWeave 利差作为跟踪变量）+ 10-18（真企稳/假反弹判据）
- **gate_check 结果：未达门槛**（窗口 2 周 < 4 周；仅"调整"1 种 regime）
- 按规定挂 pending-review 观察，禁止此时写入 reasoning-patterns.yaml

### 管线缺陷：已修复（代码层）

**根因（两层，均已验证）**：

1. **检索层**：`context_builder` 的 Qdrant 检索调用从未传 `schools` 参数，且 Recall 结果未保留 `school`/`up_id` 字段，导致下游 `_claim_school()` 兜底返回空 → 学派过滤全程失效。§ 印证：全库 grep `school_filter` 只有定义、**无任何调用方传值**。
2. **写入层**：schools.yaml 对 watchlist 写着「仅通知，不进 claim 库」，但该约定**只是注释**，无任何代码执行。

**修复内容**：

| 文件 | 修复 |
|------|------|
| `src/qing_investment/agent/tools/context_builder.py` | 新增 `DEFAULT_SCHOOL_FILTER = ["qing"]`；两个函数默认值改为该常量；Qdrant 检索传入 `schools=`；payload 保留 `school`/`up_id` |
| `src/qing_investment/agent/tools/neo4j_client.py` | RETURN 补 `coalesce(c.up_id)`/`coalesce(c.school)`，使学派兜底过滤有据可依 |
| `config/schools.yaml` | 新增 `claims_enabled` 字段（qing/gator=true，watchlist=**false**） |
| `src/qing_investment/schools.py` | `School.claims_enabled` + `claims_enabled_for_up()` |
| `src/qing_investment/claim_schema.py` | 写入校验拦截 `claims_enabled: false` 学派的 claim |
| `scripts/quarantine_school_claims.py` | 存量迁移工具（默认 dry-run） |

**验证**：`claims_enabled_for_up('550494308')=False`、`('1420210197')=True`；watchlist claim 写入被 `validate_claim_dict` 拒绝，qing claim 正常通过。

### ❗待决策：存量 365 条 watchlist claim 如何处置

dry-run 结果（比本窗口统计的 21 条大得多）：

- **365 条** watchlist claim，散落 **46 个文件**
- 其中 **22 处引用边**被其它 claim 指向（supersedes/contradicts/disagrees_with）
- 数据完整性顾虑：`framework/trading-rules.md` 的「节前持仓管理纪律」条目就引用 `claim-20260918-008-a`（watchlist）——直接删除会让框架文档引用悬空

**未执行迁移**，等确认处置方案：

| 方案 | 做法 | 优点 | 风险 |
|------|------|------|------|
| A. 隔离归档 | 迁到 `archive/schools/watchlist/`，清引用边 | 库干净，可追溯 | 22 处引用被切断，需更新 framework 文档引用 |
| B. 只隔离不删引用 | 保留 id 但 status 标 `quarantined` | 引用不断 | 需要 schema/检索支持新 status |
| C. 维持现状 | 只靠默认学派过滤挡住 | 零风险 | 库仍脏，任何人手动查 claims 仍会被污染 |

