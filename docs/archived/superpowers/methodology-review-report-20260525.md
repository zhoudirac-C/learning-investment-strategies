# Methodology Review Report - 2026-05-25

## Review Window

- Review date: 2026-05-25
- Timezone: Asia/Shanghai
- Window: 2026-05-19 to 2026-05-25
- Scope: `sources/raw/财经` 中 5月19日至5月25日 UP 文档、对应 claims、wiki 更新和既有 framework。
- Method: 按 `qing-methodology-review` 流程区分 evidence、interpretation、inference；仅将满足 durable rule 的内容写入 framework。

## Reviewed Documents

1. `早盘：26-05-19：指数修复博弈窗口，长鑫IPO催化，谷歌大会与物理AI发酵.md`
2. `早盘补充：26-05-19：假摔与拐点的节奏判断.md`
3. `复盘：26-05-19：左侧止跌拐点，情绪带指数修复，AI上游涨价链成暗线.md`
4. `早盘补发：26-05-20：坚持做T.md`
5. `早盘：26-05-20：验证龙回头修复还是二波启动，科技承接与主线聚焦.md`
6. `复盘：26-05-20：科创虹吸加剧，半导体接棒主线，全市场未共振.md`
7. `早盘补发：26-05-21：继续持股做T.md`
8. `早盘：26-05-21：反弹途中不追高，聚焦AI与存储主线轮动.md`
9. `午盘：26-05-21：情绪分歧日，半导体设备洗盘与Micro-LED补涨分化.md`
10. `午盘补发：26-05-21：仓位管理.md`
11. `尾盘补发：26-05-21：可以抄底.md`
12. `复盘：26-05-21：大盘结构修正，半导体操作节奏与4700反弹目标.md`
13. `复盘：26-05-21：真恐慌非崩盘，科技洗牌与二次冰点策略.md`
14. `研报：26-05-21：京东方康宁合作，Micro-LED光互连与AI光学价值重塑.md`
15. `早盘：26-05-22：极致冰点后看修复质量，主线承接与30分钟底部钝化.md`
16. `早盘补发：26-05-22：假摔确定，后面看修复.md`
17. `午盘补发：26-05-22：保持耐心，注意观察早盘观点的连续性.md`
18. `视频：26-05-23：Rubin BOM拆解，PCB、MLCC、ABF涨价与半导体光互联扩散.md`
19. `视频：26-05-23：2028那场必来的危机，AI资本狂潮的终局推演.md`
20. `视频：26-05-24：整治非法跨境券商的政策逻辑拆解，从蒙代尔不可能三角到A股港股投资机会.md`
21. `视频：26-05-24：周复盘，美债收益率上行、6月回调与AI硬件黄金坑.md`
22. `动态：26-05-24：缩量修复超预期，Rubin BOM扩散与退潮尾声.md`
23. `2026-05-25-早盘-指数反弹与AI硬件国产算力.md`
24. `研报：26-05-25：AI PCB Rubin产业链深度报告（结构化raw）.md`

## Change Classification

| Topic | Type | Evidence | Review Decision |
|-------|------|----------|-----------------|
| 退潮尾声缩量修复 vs 新周期确认 | extension | 5/19左侧止跌、5/20龙回头/二波验证、5/22冰点修复、5/24缩量修复、5/25高开风险 | 达到 durable rule，写入 `framework/market-cycle-framework.md` |
| Rubin BOM扩散后的标的分层 | extension | 5/23 Rubin BOM拆解、5/25 AI PCB深度报告、PCB wiki追加核心标的池 | 达到 durable rule，写入 `framework/sector-diffusion-framework.md` |
| AI资本开支与美债收益率压力测试 | clarification | 5/23 AI资本狂潮推演、5/24周复盘提出30年期美债5.2%-5.5%压力阈值 | 既有 `framework/ai-investment-cycle.md` 已覆盖长期压力测试，本次不重复改 framework |
| 国内宏观政策与资本管制框架 | extension | 5/24跨境券商政策拆解提出蒙代尔不可能三角、人民币工业型货币、港股通合规通道溢价 | 单篇深度框架，先沉淀在宏观 wiki；尚未提升为 framework |
| 机器人优先级变化 | contradiction | 5/21午盘降低机器人级别，5/21复盘和5/25早盘又把机器人作为AI走弱后的回流方向 | 判定为 cycle-shift，不是 true-conflict；保留既有 claim contradict 关系 |
| 外部风险权重变化 | clarification | 5/21更重内部结构，5/24开始强调6月美债和流动性压力 | 判定为 timeframe-shift/risk-repriced；不改旧 claim 状态 |
| 4700技术目标与6月回调预期 | no-change | 5/21技术反弹目标和5/24利润保护并存 | 前者是反弹剧本，后者是后续风险窗口；不构成矛盾 |

## Methodology Updates

### 市场周期

Evidence: 最近一周从 5/19 左侧止跌、5/20 龙回头修复验证、5/21 真恐慌非崩盘、5/22 极致冰点修复，演化到 5/24 缩量修复和 5/25 小级别反弹。

Interpretation: UP 的框架不是简单从“跌了就买”切到“涨了就追”，而是把放量恐慌后的缩量反弹定义为退潮尾声回暖。新周期需要量能、主线、核心承接和亏钱效应修复共同确认。

Framework update: `framework/market-cycle-framework.md` 新增 `4.8 退潮尾声缩量修复 vs 新周期确认`。

### 板块扩散

Evidence: Rubin VR200/GB300 价值量拆解把主线从 GPU/CPO 继续扩散到 PCB、MLCC、ABF、CCL、铜箔、玻纤、树脂、设备和工艺耗材。

Interpretation: BOM拆解本身只解决“价值量去哪了”，不解决“谁最确定”。需要再按核心确定性、确定性扩展、进攻弹性、长期期权/边界分层。

Framework update: `framework/sector-diffusion-framework.md` 新增 `BOM扩散后的标的分层`，并用 AI PCB/Rubin 链作为应用示例。

### 选股

Evidence: 5/21以后 UP 明确从“板块普涨”转为“科技内部个股筛选”；5/25 PCB深度报告进一步把沪电股份、胜宏科技、生益科技与景旺电子、方正科技、隆扬电子、东材科技、宏和科技、铜冠铜箔等分层。

Interpretation: 核心标的池不是买入池，而是观察强弱、验证订单和判断主线承接的锚点。深南电路应主要按 ABF/FC-BGA 和平台型能力跟踪，不直接混入普通 Rubin PCB 成品核心。

### F10与产业验证

Evidence: 本周新增的 F10 相关变化主要来自订单、客户认证、小批量、收入确认和利润率验证，而不是报表分析规则变化。

Interpretation: 本次没有形成新的 F10 总规则；只把产业链验证阶梯写入板块扩散框架。

### 宏观政策

Evidence: 5/24 跨境券商政策拆解把 MLF加量、打击非法跨境券商、人民币渐进升值放在蒙代尔不可能三角下解释，并推导出港股通合规通道溢价、国债资金向高股息资产迁移等方向。

Interpretation: 这组内容提供了一个国内宏观政策解释框架：先判断政策在货币独立、汇率稳定、资本流动三者之间的取舍，再看资金被引导到 A股、港股通、高股息或债市的哪条通道。它对宏观配置有价值，但本周只有单篇系统表达，暂不提升为 framework。

### 技术

Evidence: 30分钟底部钝化、日线顶部结构后6个交易日调整、上证能否反包、5日均线和成交量配合，贯穿 5/21 至 5/25 文档。

Interpretation: 技术信号在本周主要用于区分小级别反弹、修复延续和冲高回落风险，不单独决定仓位。

### 仓位风控

Evidence: 5/19至5/25持续出现“5-7成”“半仓至六成”“有先手看承接、没先手等分歧”“6月前保护利润”等表述。

Interpretation: 仓位纪律没有发生总纲级变化，仍是按周期和确认信号动态调整。新增强调是：周末或消息发酵后的一致性高开，不作为追高理由。

## Claim Status Review

- 本次未修改 claim status。
- 原因：最近一周主要是周期推进、时间尺度变化和风险重新定价，没有发现需要把旧 claim 直接标记为 failed 或 expired 的 true-conflict。
- 已存在的机器人优先级冲突关系继续保留：`claim-20260521-003-e` contradicts `claim-20260521-002-g`。
- 需要继续观察的 claim：`claim-20260521-002-k` 对外部风险权重较低的判断，后续若 6月美债收益率或美元流动性持续压制科技估值，再考虑标记为 risk-repriced 或 superseded。

## Durable Rule Decisions

| Rule | Durable? | Reason |
|------|----------|--------|
| 退潮尾声缩量修复需要二次确认 | Yes | 跨 5/19、5/20、5/22、5/24、5/25 多篇文档反复出现，且直接改变追高/低吸纪律 |
| BOM扩散后先分层再交易 | Yes | 5/23 Rubin BOM 与 5/25 AI PCB报告形成连续产业验证框架，能解释核心、弹性和边界标的差异 |
| 蒙代尔不可能三角解释国内资产政策组合 | No | 规则清晰且重要，但本周仅来自单篇政策拆解，先保留在宏观 wiki，等待后续复用后再上升为 framework |
| 30年期美债5.2%-5.5%作为短期科技压力阈值 | No | 属于当前宏观窗口阈值，后续需市场验证，不提升为长期 framework |
| 4700作为本轮反弹目标 | No | 属于短期技术剧本，不具备跨周期通用性 |

## Framework Files Updated

- `framework/market-cycle-framework.md`
- `framework/sector-diffusion-framework.md`

## Follow-up Validation

1. 观察 5月26日至5月29日是否出现缩量回踩后主线核心抗跌；若成立，可作为退潮尾声规则的后验案例。
2. 观察 AI PCB 核心层是否持续强于扩展层和期权层；若期权层先高潮而核心层走弱，应降低 BOM 扩散交易权重。
3. 观察国产算力、Rubin海外链、MLCC/PCB 能否形成共同承接；若只剩单点脉冲，应按修复末端处理。
4. 观察 6月美债收益率、美元和科技高估值股承压程度，决定是否把外部风险从短期压力测试上修为阶段性仓位约束。
5. 观察跨境券商整治、人民币汇率、港股通资金和高股息资产是否形成持续政策交易链；若后续文档反复复用，再考虑新增宏观政策 framework。
