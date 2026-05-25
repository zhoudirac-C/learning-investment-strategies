# 操作日志

## 2026-05-25 | qing-methodology-review | 最近7天UP文档方法论复盘

- Review 窗口：2026-05-19 至 2026-05-25。
- 输出报告：`docs/superpowers/methodology-review-report-20260525.md`。
- Framework 更新：
  - `framework/market-cycle-framework.md`：新增“退潮尾声缩量修复 vs 新周期确认”规则。
  - `framework/sector-diffusion-framework.md`：新增“BOM扩散后的标的分层”规则，并用 AI PCB/Rubin 链说明核心、扩展、弹性和边界标的差异。
- 宏观政策：跨境券商整治、人民币工业型货币和港股通合规通道溢价暂保留在宏观 wiki，本次未提升为 framework。
- Claim status：本次未修改。最近一周主要是 cycle-shift、timeframe-shift 和 risk-repriced，没有新增 true-conflict。

## 2026-05-25 | qing-learning ingest | 5-24至5-25新增文档按日期学习

- 处理顺序：
  1. `sources/raw/财经/动态：26-05-24：缩量修复超预期，Rubin BOM扩散与退潮尾声.md`
  2. `sources/raw/财经/视频：26-05-24：周复盘，美债收益率上行、6月回调与AI硬件黄金坑.md`
  3. `sources/raw/财经/2026-05-25-早盘-指数反弹与AI硬件国产算力.md`
  4. `sources/raw/财经/研报：26-05-25：AI PCB Rubin产业链深度报告（结构化raw）.md`
- 新增 claim 文件：
  - `knowledge/claims/claim-20260524-013.yaml`：退潮尾声、缩量回踩、Rubin BOM扩散、AI PCB材料工艺耗材、CPO/DCI预期差、退潮尾声不追高
  - `knowledge/claims/claim-20260524-019.yaml`：美债收益率结构性高企、5.2%-5.5%风险阈值、6月回调前仓位纪律、PCB/MLCC鱼尾不追高、穿越期赔率、减持公告风险
  - `knowledge/claims/claim-20260525-001.yaml`：日线顶部后小级别反弹、5-7成仓位、PCB/MLCC持续性、超聚变IPO国产算力、关键盯盘指标
  - `knowledge/claims/claim-20260525-006.yaml`：AI PCB垂直市场、Midplane增量、SerDes驱动材料升级、上游卡脖子、三层标的分层、ABF边界、重仓前风险
- 新增 wiki：
  - `knowledge/wiki/每日复盘/2026-05-24.md`
  - `knowledge/wiki/每日复盘/2026-05-25.md`
- 更新 wiki：
  - `knowledge/wiki/市场分析/AI上游涨价链.md`
  - `knowledge/wiki/市场分析/PCB与先进封装.md`
  - `knowledge/wiki/市场分析/AI资本开支周期与泡沫风险.md`
  - `knowledge/wiki/市场分析/光通信.md`
  - `knowledge/wiki/市场分析/国产CPU_GPU与软件.md`
  - `knowledge/wiki/投资方法论/仓位管理.md`
  - `knowledge/wiki/投资方法论/交易纪律.md`
- 核心学习：
  - 5月22日缩量修复更接近退潮尾声回暖，而不是新周期全面启动；后续还需缩量回踩和核心主线承接确认。
  - Rubin BOM扩散从PCB成品股继续下沉到M9材料、mSAP、LD曝光、图形电镀、钻针等材料、工艺、设备和耗材层。
  - AI PCB不是单一市场，需要拆成HDI、高多层板、Midplane、IC载板、CCL、玻璃布、铜箔、树脂和设备分别验证。
  - Midplane是Rubin时代最大从无到有增量，SerDes/NVLink速率升级是M8/M9、Q-Glass、HVLP4/5和高阶HDI的产业时钟。
  - 美债收益率高企把AI资本开支交易纳入流动性压力测试，30年期美债5.2%-5.5%作为短期风险阈值观察。
  - 退潮尾声和周末充分发酵后，纪律是有先手看承接、没先手等分歧，不追周一一致高开。
- Framework 更新：未更新。本次新增内容主要是单日盘面案例、产业链专题细化和短期风险窗口，未达到跨阶段 durable rule 的新增条件。
- 总纲更新：未更新。原因是本次核心仍是5月下旬特定盘面与Rubin产业链扩散案例，不改变“先周期、再主线、再个股”的总纲级框架。

### 追加修正：AI PCB核心标的池

- 更新 `knowledge/wiki/市场分析/PCB与先进封装.md`：
  - 根据 `研报：26-05-25：AI PCB Rubin产业链深度报告（结构化raw）.md` 补充“大陆AI PCB核心标的池”。
  - 短期 Rubin PCB 核心层明确为：沪电股份、胜宏科技、生益科技。
  - 确定性扩展：景旺电子、方正科技。
  - 进攻弹性：隆扬电子、东材科技、宏和科技、铜冠铜箔。
  - 长期期权/边界观察：中英科技、中材科技、诺德股份、华正新材、深南电路等。
  - 重新强调深南电路主要按 ABF/FC-BGA 封装基板和平台型能力跟踪，不直接混入普通 Rubin PCB 成品核心。

## 2026-05-24 | qing-learning ingest | 整治非法跨境券商的政策逻辑拆解

- 处理来源：`sources/raw/财经/视频：26-05-24：整治非法跨境券商的政策逻辑拆解，从蒙代尔不可能三角到A股港股投资机会.md`
- 新增 claim 文件：
  - `knowledge/claims/claim-20260524-001.yaml`：蒙代尔不可能三角与政策选择
  - `knowledge/claims/claim-20260524-002.yaml`：2022年汇率保卫战与工具创新
  - `knowledge/claims/claim-20260524-003.yaml`：非法跨境券商的资金外流风险
  - `knowledge/claims/claim-20260524-004.yaml`：2026年5月政策闭环
  - `knowledge/claims/claim-20260524-005.yaml`：人民币工业型货币定位
  - `knowledge/claims/claim-20260524-006.yaml`：渐进升值对冲套利空间
  - `knowledge/claims/claim-20260524-007.yaml`：国债收益率接近极限
  - `knowledge/claims/claim-20260524-008.yaml`：资金从债券流向A股
  - `knowledge/claims/claim-20260524-009.yaml`：资金入市三道闸门
  - `knowledge/claims/claim-20260524-010.yaml`：港股通合规通道溢价
  - `knowledge/claims/claim-20260524-011.yaml`：央行货币政策四大约束
  - `knowledge/claims/claim-20260524-012.yaml`：未来货币政策路径预判
- 更新 wiki：待补充（宏观政策、汇率框架、国债市场、港股通等板块）
- Framework 更新：待评估（是否满足 durable rule 条件）
- 核心学习：
  - 蒙代尔不可能三角是中国所有汇率政策和资本管制的基础框架
  - 2022-2023年汇率保卫战创造了精细化工具组合，几乎不消耗外汇储备
  - 非法跨境券商整治是资本管制堵漏，不是单一监管事件
  - 2026年5月政策组合（MLF加量+打击跨境券商+人民币渐进升值）构成完整闭环
  - 人民币已从金融型货币转为工业型货币，核心目标是维持工业体系稳定
  - 渐进升值年化约3.6%，恰好对冲中美利差，完全消除套利空间
  - 国债收益率接近极限（1.65%），剩余下行空间仅约45个基点
  - 高股息A股将推动2-3万亿长期增量资金入市
  - 资金入市三道闸门（心理创伤、政策催化剂、基本面拐点），大概率2026年7月后打开
  - 港股通享受合规通道溢价，南向资金占比升至36%
- 总纲更新：未更新。本次属于宏观政策框架学习，尚未改变"先周期、再主线、再个股"的总纲级框架，但补充了宏观流动性分析的维度。

## 2026-05-23 | wiki maintenance | 市场分析板块核心标的池补全

- 审计范围：`knowledge/wiki/市场分析/*.md`。
- 处理原则：产业链/板块文档必须有核心标的、观察池或观察锚点；情绪判断、量能判断、关键点位、指数调整、修复性质判断和行情全景属于方法论/总览，不强行加入个股。
- 更新文档：
  - `knowledge/wiki/市场分析/国产CPU_GPU与软件.md`：补充国产AI芯片、CPU/GPU、服务器整机、CANN软件、数据库、中间件、操作系统和AI应用分层标的池。
  - `knowledge/wiki/市场分析/量子计算.md`：补充国盾量子、格尔软件、科大国创及海外事件锚点，明确仍按事件驱动低优先级处理。
  - `knowledge/wiki/市场分析/科创50虹吸.md`：补充寒武纪、中芯国际、华虹公司、海光信息、澜起科技、中微公司、北方华创、封测扩散等虹吸观察锚点。
- 核心学习：标的池不是买入池。板块文档中的个股只用于判断主线地位、扩散强度和资金承接，仍需结合当日量能、趋势、位置和证伪条件。

## 2026-05-23 | qing-learning ingest | Rubin BOM拆解与AI硬件价值扩散

- 处理来源：`sources/raw/财经/视频：26-05-23：Rubin BOM拆解，PCB、MLCC、ABF涨价与半导体光互联扩散.md`
- 新增 claim 文件：`knowledge/claims/claim-20260523-001.yaml`
- 更新 wiki：
  - `knowledge/wiki/市场分析/AI上游涨价链.md`
  - `knowledge/wiki/市场分析/PCB与先进封装.md`
  - `knowledge/wiki/市场分析/AI电源与超级电容.md`
  - `knowledge/wiki/市场分析/玻璃基板与Micro-LED.md`
  - `knowledge/wiki/市场分析/光通信.md`
  - `knowledge/wiki/市场分析/半导体产业链.md`
  - `knowledge/wiki/市场分析/半导体设备.md`
  - `knowledge/wiki/市场分析/半导体设备零部件.md`
  - `knowledge/wiki/博主/2025-12-2026-05-主线与标的追踪.md`
- Framework 更新：`framework/sector-diffusion-framework.md` 增加“BOM拆解式扩散”规则。
- 核心学习：Rubin BOM 拆解说明 AI 硬件主线从 GPU/光模块核心向存储、PCB、MLCC、ABF、电源液冷、ODM 和半导体设备材料零部件扩散；远期 Micro-LED 光互联仍需按客户验证、样品、小批量订单、良率和成本下降逐级确认。
- 后续补充：将 ABF 材料/类 ABF 增层膜从 ABF/FC-BGA 载板中单独拆出观察池，按“客户验证、小批量供货、收入确认”逐级确认，避免把材料厂和载板厂混为一类。
- 总纲更新：未更新。本次属于产业链专题细化，尚未改变“先周期、再主线、再个股”的总纲级框架。

## 2026-05-24 | qing-learning ingest | 2028 AI资本狂潮终局推演

- 处理来源：`sources/raw/财经/视频：26-05-23：2028那场必来的危机，AI资本狂潮的终局推演.md`
- 新增 claim 文件：`knowledge/claims/claim-20260523-002.yaml`
- 新增 wiki：
  - `knowledge/wiki/市场分析/AI资本开支周期与泡沫风险.md`
- 更新 wiki：
  - `knowledge/wiki/市场分析/AI上游涨价链.md`
  - `knowledge/wiki/投资方法论/仓位管理.md`
- Framework 更新：
  - `framework/ai-investment-cycle.md`
  - `framework/stock-analysis-playbook.md`
- 核心学习：VR200价格上升既是AI硬件价值量扩散信号，也是摩尔定律衰减、终端ROI压力和资本开支周期风险的长期提醒。AI硬件链短中期仍按主线强度、订单和量能交易，但长期需要新增云厂商资本开支、GPU二手价、HBM价差、GPU租赁公司融资利差等压力测试。
- 总纲更新：未更新。本次是单篇长周期推演，且具体2026-2028时间线和阈值仍待验证，暂不提升为总纲级稳定框架。

## 2026-05-16 | qing-learning ingest | 2025-12 至 2026-05 历史全量批处理

- 处理来源：`sources/raw/财经` 下 391 篇 Markdown；本轮补处理此前未记录的 387 篇。
- 新增 claim 文件：`knowledge/claims/2025-12-2026-05-历史全量-claims.md`
- 新增 wiki：
  - `knowledge/wiki/市场分析/2025-10-2026-05-行情全景.md`
  - `knowledge/wiki/投资方法论/博主方法论总纲.md`
  - `knowledge/wiki/博主/2025-12-2026-05-主线与标的追踪.md`
- 新增案例：`knowledge/cases/methodology-cases/2025-12-2026-05-行情阶段案例.md`
- 方法论更新：市场周期、板块轮动、技术分析、仓位风控、选股框架、F10 基本面、决策流程。
- Framework 更新：`framework/stock-analysis-playbook.md` 增加周期识别、主线生命周期、个股身份、技术纠错和量能估值约束。
- 核心学习：先周期、再主线、再个股；量能是承接与估值容忍度底层参数；顶部钝化与高 9 触发风控但允许纠错；主线全链条补涨后优先保护利润。

## 2026-05-16 | qing-learning ingest | 2026-05-14 至 2026-05-15 强分歧承接

- 处理来源：
  - `sources/raw/财经/复盘：26-05-14：急跌调整与新周期酝酿，AI算力CPO先进封装.md`
  - `sources/raw/财经/视频：26-05-14：A股大跌后走势分析，指数错杀震荡，调整后仍有大行情.md`
  - `sources/raw/财经/早盘：26-05-15：今日不是看反弹，而是看承接是否成立.md`
  - `sources/raw/财经/动态补发：26-05-15：多点耐心，没到卖的时候.md`
- 新增 claim 文件：`knowledge/claims/2026-05-14-15-强分歧承接-claims.md`
- 新增 wiki：
  - `knowledge/wiki/每日复盘/2026-05-14.md`
  - `knowledge/wiki/每日复盘/2026-05-15.md`
- 新增案例：`knowledge/cases/methodology-cases/2026-05-14-15-高位强分歧承接.md`
- 方法论更新：市场周期、板块轮动、技术分析、仓位风控、决策流程。
- Framework 更新：`framework/stock-analysis-playbook.md` 增加强分歧承接检查。
- 核心学习：强分歧后不看单日反弹，优先确认指数关键位、量能、跌停家数和主线回流；分歧初期活口需区分退潮活口与复苏活口。

## 2026-05-17 | qing-learning ingest | 2026-05-17 宏观再通胀与科技拥挤

- 处理来源：`sources/raw/财经/视频：26-05-17：5月中旬A股周复盘，CPI-PPI、人民币汇率、美联储与A股策略.md`
- 新增 claim 文件：`knowledge/claims/2026-05-17-宏观再通胀与科技拥挤-claims.md`
- 新增 wiki：`knowledge/wiki/每日复盘/2026-05-17.md`
- 方法论更新：市场周期、板块轮动、仓位风控、决策流程。
- Framework 更新：`framework/stock-analysis-playbook.md` 增加科技拥挤度、宏观压力测试和结构性再通胀筛选。
- 核心学习：AI 与半导体中长期逻辑未结束，但融资、换手和拥挤度会决定短期风险；4 月 CPI/PPI 被定义为结构性再通胀，利好 PPI 修复和上游盈利；人民币温和升值有贸易支撑，高利率、强美元和高油价是高估值科技的外部压力测试。

## 2026-05-18

### 学习内容

- 处理 `sources/raw/财经/午盘：26-05-18：长鑫产业链新生启动，指数共振乏力待观察.md`
- 处理 `sources/raw/财经/早盘：26-05-18：连续大跌后博弈反弹，半导体设备最强主线.md`
- 处理 `sources/raw/财经/早盘补充：26-05-18：耐心持股，切换核心.md`
- 处理 `sources/raw/财经/研报：26-05-18：半导体设备零部件与存储耗材产业链三公司跟踪.md`
- 处理 `sources/raw/财经/周复盘：26-05-15：动态周复盘.md`
- 处理 `sources/raw/财经/动态补发：26-05-15：多点耐心，没到卖的时候.md`
- 处理 `sources/raw/财经/早盘：26-05-15：今日不是看反弹，而是看承接是否成立.md`
- 处理 `sources/raw/财经/周复盘：26-04-06：现实的误判，全球资产重新配置新策略.md`
- 处理 `sources/raw/财经/周复盘：26-04-14：是反弹不是反转，市场为什么对中东冲突麻木了.md`
- 处理 `sources/raw/财经/周复盘：26-04-20：跟上节奏，AI算力四阶段炒作路径.md`
- 处理 `sources/raw/财经/周复盘：26-04-26：交易需要不完美，也需要接受不完美.md`

### 抽取 Claims

| ID | 类型 | 主题 | 状态 |
|----|------|------|------|
| claim-20260406-001 | macro | 全球滞胀交易 | expired |
| claim-20260406-002 | macro | 油价周期 | expired |
| claim-20260406-003 | stock-view | A股全球定位 | superseded |
| claim-20260406-004 | sector-theme | A股安全/成长主线 | active |
| claim-20260414-001 | macro | 中东冲突定价 | active |
| claim-20260414-002 | market-cycle | 美股判断 | contradicted |
| claim-20260414-003 | sector-theme | A股四条主线 | active |
| claim-20260414-004 | methodology | 仓位管理 | active |
| claim-20260414-005 | macro | PPI判断 | active |
| claim-20260420-001 | operation | 仓位策略 | active |
| claim-20260420-002 | methodology | 牛市持仓纪律 | active |
| claim-20260420-003 | operation | 右侧交易 | active |
| claim-20260420-004 | operation | 选股纪律 | active |
| claim-20260426-001 | operation | 仓位策略 | active |
| claim-20260426-002 | technical-signal | 油价预警 | expired |
| claim-20260426-003 | market-cycle | 关键时间窗口 | expired |
| claim-20260426-004 | operation | 选股纪律 | active |
| claim-20260426-005 | methodology | 产业扩散规律 | active |
| claim-20260426-006 | methodology | 牛市纪律 | active |
| claim-20260426-007 | technical-signal | 出货判断 | active |
| claim-20260515-001 | market-cycle | 市场周期判断 | active |
| claim-20260515-002 | methodology | 劣性轮动识别 | active |
| claim-20260515-003 | operation | 操作策略 | active |
| claim-20260515-004 | sector-theme | 存储产业链 | active |
| claim-20260515-005 | technical-signal | 轮动质量判断 | active |
| claim-20260515-006 | methodology | 活口分类方法论 | active |
| claim-20260515-007 | operation | 板块观察方法 | active |
| claim-20260515-008 | methodology | 结构性行情判断 | active |
| claim-20260515-009 | technical-signal | 关键点位判断 | active |
| claim-20260515-010 | technical-signal | 量能判断 | active |
| claim-20260515-011 | market-cycle | 情绪修复标准 | active |
| claim-20260515-012 | market-cycle | 修复性质判断 | active |
| claim-20260515-013 | operation | 交易纪律 | active |
| claim-20260518-001 | sector-theme | 长鑫存储产业链 | active |
| claim-20260518-002 | market-cycle | 市场情绪 | active |
| claim-20260518-003 | methodology | 板块判断方法论 | active |
| claim-20260518-004 | sector-theme | 长鑫存储产业链 | active |
| claim-20260518-005 | operation | 操作策略 | active |
| claim-20260518-006 | market-cycle | 指数调整节奏 | active |
| claim-20260518-007 | technical-signal | 量能判断 | active |
| claim-20260518-008 | sector-theme | 半导体设备 | active |
| claim-20260518-009 | sector-theme | Token算力 | active |
| claim-20260518-010 | sector-theme | 新型储能 | active |
| claim-20260518-011 | operation | 主线优先级 | active |
| claim-20260518-012 | market-cycle | 调整性质判断 | active |
| claim-20260518-013 | sector-theme | 长鑫存储产业链 | active |
| claim-20260518-014 | methodology | 交易方法论 | active |
| claim-20260518-015 | stock-view | 富创精密 | active |
| claim-20260518-016 | stock-view | 珂玛科技 | active |
| claim-20260518-017 | stock-view | 京仪装备 | active |

### 矛盾链接更新

| Claim A | 关系 | Claim B | 类型 |
|---------|------|---------|------|
| claim-20260406-003 | superseded by | claim-20260420-001 | cycle-shift |
| claim-20260406-001 | contradicted by | claim-20260414-001 | risk-repriced |
| claim-20260420-001 | contradicted by | claim-20260426-001 | cycle-shift |

### 更新 Wiki

- 新建/更新 `市场分析/长鑫存储产业链.md`
- 新建/更新 `市场分析/量能判断.md`
- 新建 `市场分析/指数调整.md`
- 新建 `市场分析/半导体设备.md`
- 新建 `市场分析/半导体设备零部件.md`
- 新建 `市场分析/Token算力.md`
- 新建 `市场分析/新型储能.md`
- 新建 `市场分析/关键点位.md`
- 新建 `市场分析/情绪判断.md`
- 新建 `市场分析/修复性质判断.md`
- 新建/更新 `投资方法论/主线判断.md`
- 新建/更新 `投资方法论/仓位管理.md`
- 新建 `投资方法论/分歧中找机会.md`
- 新建 `投资方法论/劣性轮动识别.md`
- 新建 `投资方法论/活口分类.md`
- 新建 `投资方法论/板块观察方法.md`
- 新建 `投资方法论/结构性行情判断.md`
- 新建 `投资方法论/交易纪律.md`

### 更新 Framework

- 新建 `framework/ai-investment-cycle.md`
- 新建 `framework/sector-diffusion-framework.md`
- 新建 `framework/livestock-classification.md`
- 新建 `framework/market-participant-framework.md`
- 更新 `framework/README.md`

#### Methodology Review（2026-05-18）

**Review 窗口**: 5/11–5/18
**新增 Claims**: 25 条
**Status 更新**: claim-20260414-002（美股判断）active → contradicted
**矛盾链接**: 2 组（美股被证伪、油价被证伪）

**Framework 更新**:
- 新建 `framework/market-cycle-framework.md`（市场周期四阶段、调整性质、修复性质、分歧操作、事件催化vs资金扩散）
- 扩展 `framework/livestock-classification.md`（劣性轮动系统定义）
- 扩展 `framework/ai-investment-cycle.md`（阶段1.5 Token经济商业化）
- 更新 `framework/README.md`

**Durable Rule 判定**:
- 入 framework：劣性轮动识别、事件催化vs资金扩散、修复性质判断、调整=调仓换股、分歧中找机会（5条）
- 保留 wiki：板块建制判断（待重复验证）

## 2026-05-18 | qing-learning ingest | 复盘与B站视频波浪理论分析

### 学习内容

- 处理 `sources/raw/财经/复盘：26-05-18：市场复盘.md`
- 处理 `sources/raw/财经/复盘：26-05-18：B站视频复盘-大盘将迎来反弹.md`

### 抽取 Claims

| ID | 类型 | 主题 | 状态 |
|----|------|------|------|
| claim-20260518-018 | market-cycle | 市场从主升浪转入震荡轮动 | active |
| claim-20260518-018 | technical-signal | 3万亿成交额强弱分水岭 | active |
| claim-20260518-018 | technical-signal | 5.19是重要节点观察日 | active |
| claim-20260518-018 | sector-theme | 长鑫存储产业链已成为明牌 | active |
| claim-20260518-018 | sector-theme | 物理AI与机器人是5.19最值得观察的方向 | active |
| claim-20260518-018 | stock-view | 柏诚股份半导体洁净室龙头 | active |
| claim-20260518-018 | stock-view | 北自科技机器人方向核心风向标 | active |
| claim-20260518-018 | stock-view | 中天精装向半导体转型 | active |
| claim-20260518-018 | stock-view | 上峰水泥半导体股权投资进入收获期 | active |
| claim-20260518-018 | stock-view | 华峰测控国产测试设备受益AI芯片和HBM | active |
| claim-20260518-018 | methodology | 节点交易模式最具可操作性 | active |
| claim-20260518-018 | operation | 缩量市场适合低吸不适合追高 | active |
| claim-20260518-019-a | technical-signal | A浪下杀基本结束B浪反弹开启 | active |
| claim-20260518-019-b | technical-signal | B浪反弹目标约4200点 | active |
| claim-20260518-019-c | technical-signal | C浪下跌关键支撑4080点 | active |
| claim-20260518-019-d | market-cycle | ABC调整6月中下旬结束 | active |
| claim-20260518-019-e | sector-theme | 长鑫存储是B浪反弹主线 | active |
| claim-20260518-019-f | operation | 长鑫存储低开买点 | active |
| claim-20260518-019-g | sector-theme | 三大运营商面临调整 | active |
| claim-20260518-019-h | stock-view | 润建股份不建议关注 | active |
| claim-20260518-019-i | macro | 英伟达财报大概率没问题 | active |
| claim-20260518-019-j | technical-signal | 英特尔止跌企稳 | active |
| claim-20260518-019-k | stock-view | 兆易创新炸板次日阴线买点 | active |
| claim-20260518-019-l | stock-view | 中国长城收阳概率大 | active |
| claim-20260518-019-m | methodology | B浪买阴不买阳纪律 | active |

### 更新 Wiki

- 更新 `市场分析/关键点位.md` — 新增波浪理论关键点位（4200/4180/4100/4080）和时间空间规则
- 更新 `投资方法论/交易纪律.md` — 新增B浪买阴不买阳、完整吃完再减仓、炸板次日阴线买点、产业链联动选股
- 更新 `投资方法论/博主方法论总纲.md` — 技术结构框架补充波浪理论应用规则（时间空间锁定一个确定项、拐点概率思维、形态验证、ABC后黄金坑）
- 更新 `市场分析/长鑫存储产业链.md` — 新增B浪反弹主线定位、与其他热点对比表

### Durable Rule 判定

- **入 framework**：波浪理论时间空间锁定一个确定项、拐点判断的概率思维、产业链联动选股逻辑（3条）
- **保留 wiki**：B浪操作纪律买阴不买阳、炸板次日阴线买点（待更多案例验证）

## 2026-05-19 | qing-learning ingest | 5月19日早盘修复博弈窗口

### 学习内容

- 处理 `sources/raw/财经/早盘：26-05-19：指数修复博弈窗口，长鑫IPO催化，谷歌大会与物理AI发酵.md`

### 抽取 Claims

| ID | 类型 | 主题 | 状态 |
|----|------|------|------|
| claim-20260519-001-a | technical-signal | 日线顶部结构第二次止跌信号 | active |
| claim-20260519-001-b | technical-signal | 调整低点大概率出现在5月20日 | active |
| claim-20260519-001-c | market-cycle | 空方力量明显衰竭 | active |
| claim-20260519-001-d | sector-theme | 长鑫存储IPO审核状态已问询 | active |
| claim-20260519-001-e | stock-view | 深科技承接长鑫60%-70%封测订单 | active |
| claim-20260519-001-f | sector-theme | 物理AI是2026年核心投资方向 | active |
| claim-20260519-001-g | operation | 先买后卖日内交易+二次恐慌是最后低吸机会 | active |
| claim-20260519-001-h | sector-theme | 谷歌开发者大会催化AI应用 | active |
| claim-20260519-001-i | sector-theme | AI驱动电力需求激增 | active |
| claim-20260519-001-j | operation | 蒙娜丽莎跌停显示资金缺高度意愿 | active |
| claim-20260519-001-k | stock-view | 领益智造或绑定英伟达大额订单 | active |
| claim-20260519-001-l | sector-theme | 算力网向统一调度入口转变 | active |

### 矛盾链接更新

| Claim A | 关系 | Claim B | 类型 |
|---------|------|---------|------|
| claim-20260518-019-a | contradicted by | claim-20260519-001-b | timeframe-shift |

### 核心结论

1. 昨晚复盘判断5.19是拐点，早盘判断调整低点大概率在5.20，时间差1天，属于正常分歧
2. 长鑫IPO"已问询"是确定性催化，与昨日复盘主线判断一致
3. 物理AI/机器人方向被提升为2026年核心投资方向，与5.18文字复盘方向一致
4. 空方衰竭+二次恐慌=最后低吸机会，与B站视频"A浪结束B浪开启"判断一致
5. 操作策略：先买后卖日内交易，半导体增配，去弱留强

### 方法论更新

- **新增方法论**：拐点确认看连续两日走势组合（假摔+次日强修复，或直接修复）
- **新增方法论**：拐点节点操作核心不是押注今天涨跌，而是判断明天方向
- **Durable Rule**：假摔判定与拐点确认的两种路径 → 入 framework

## 2026-05-19 | qing-learning ingest | 5月19日复盘：左侧止跌拐点与AI上游涨价链

### 学习内容

- 处理 `sources/raw/财经/复盘：26-05-19：左侧止跌拐点，情绪带指数修复，AI上游涨价链成暗线.md`

### 抽取 Claims

| ID | 类型 | 主题 | 状态 |
|----|------|------|------|
| claim-20260519-003-a | market-cycle | 左侧止跌拐点确认 | active |
| claim-20260519-003-b | technical-signal | CPO补跌=退潮最后一轮恐慌释放 | active |
| claim-20260519-003-c | sector-theme | AI上游涨价链是最值得重视的暗线 | active |
| claim-20260519-003-d | operation | 策略从全面防守转向适度积极 | active |
| claim-20260519-003-e | operation | 明日验证标准：大长腿个股溢价率 | active |
| claim-20260519-003-f | risk | 后面大概率还有一次回踩冰点 | active |
| claim-20260519-003-g | stock-view | 风华高科：MLCC国产龙头 | active |
| claim-20260519-003-h | stock-view | 海星股份：电极箔量价齐升 | active |

### 矛盾链接更新

| Claim A | 关系 | Claim B | 类型 |
|---------|------|---------|------|
| claim-20260519-001-b | superseded by | claim-20260519-003-a | timeframe-shift |

说明：早盘claim-20260519-001-b判断"调整低点大概率出现在5月20日"，复盘确认5月19日即为左侧止跌拐点，今日低点已现。两者不矛盾，复盘是对早盘判断的提前验证。

### 更新 Wiki

- 新建 `每日复盘/2026-05-19.md`
- 新建 `市场分析/AI上游涨价链.md`
- 更新 `市场分析/情绪判断` — 新增左侧止跌拐点判定标准
- 更新 `市场分析/修复性质判断` — 新增良性假摔定义

### Durable Rule 判定

- **入 framework**：高位核心板块补跌=调整尾声信号、大长腿溢价率=接力情绪验证指标（2条）
- **保留 wiki**：AI上游涨价链扩散路径（待更多案例验证）

## 2026-05-20 | qing-learning ingest | 早盘与补发：坚持做T，验证龙回头修复还是二波启动

### 学习内容

- 处理 `sources/raw/财经/早盘：26-05-20：验证龙回头修复还是二波启动，科技承接与主线聚焦.md`
- 处理 `sources/raw/财经/早盘补发：26-05-20：坚持做T.md`

### 抽取 Claims

| ID | 类型 | 主题 | 状态 |
|----|------|------|------|
| claim-20260520-001-a | market-cycle | 龙回头修复 vs 二波启动 | active |
| claim-20260520-001-b | technical-signal | 弱分歧质量 | active |
| claim-20260520-001-c | operation | 大长腿承接阈值 | active |
| claim-20260520-001-d | sector-theme | 低位新分支接力 | active |
| claim-20260520-001-e | sector-theme | 泛科技修复但无绝对主线 | superseded |
| claim-20260520-001-f | risk | 英伟达财报窗口压制海外AI链 | active |
| claim-20260520-001-g | operation | 做T为主，三条件满足才小幅加仓 | active |
| claim-20260520-002-a | market-cycle | 反弹第二天仍有3到5天修复窗口 | active |
| claim-20260520-002-b | sector-theme | 长鑫链条主动但内部分化 | active |
| claim-20260520-002-c | operation | 轮动式反弹坚持做T | active |

### 更新 Wiki

- 更新 `市场分析/修复性质判断.md` — 新增龙回头修复 vs 二波启动、良性弱分歧判断
- 更新 `市场分析/情绪判断.md` — 新增大长腿承接分档和低位新分支接力验证
- 更新 `市场分析/长鑫存储产业链.md` — 新增5月20日早盘长鑫链观察和扩散质量
- 更新 `市场分析/Token算力.md` — 新增Token工厂/国产算力/华为昇腾超节点交易验证
- 更新 `市场分析/量能判断.md` — 新增轮动反弹与放量二波判断
- 更新 `投资方法论/主线判断.md` — 新增泛科技修复中的主线筛选条件
- 更新 `投资方法论/仓位管理.md` — 新增反弹初期加仓三条件
- 更新 `投资方法论/交易纪律.md` — 新增反弹初期做T纪律

### Framework 更新

- 更新 `framework/market-cycle-framework.md` — 新增“龙回头修复 vs 二波启动”判别表和加仓三条件
- 更新 `framework/stock-analysis-playbook.md` — 个股分析流程中补充左侧止跌后验证日的仓位纪律

### Durable Rule 判定

- **入 framework**：龙回头修复 vs 二波启动判别、反弹初期加仓三条件（2条）
- **保留 wiki**：5月20日长鑫链条局部强势与内部分化、英伟达财报窗口对海外AI链压制（单日语境，待后续验证）

## 2026-05-21 | qing-learning ingest | 5月20日复盘：科创虹吸与半导体接棒

### 学习内容

- 处理 `sources/raw/财经/复盘：26-05-20：科创虹吸加剧，半导体接棒主线，全市场未共振.md`

### 抽取 Claims

| ID | 类型 | 主题 | 状态 |
|----|------|------|------|
| claim-20260520-003-a | market-cycle | AI硬科技结构牛 + 科创50局部虹吸 | active |
| claim-20260520-003-b | technical-signal | 科创50虹吸型上涨非带动型上涨 | active |
| claim-20260520-003-c | sector-theme | 半导体正式接过科技主线扩散接力棒 | active |
| claim-20260520-003-d | methodology | AI硬科技从光通信向半导体上游扩散 | active |
| claim-20260520-003-e | sector-theme | 光通信进入去伪存真阶段 | active |
| claim-20260520-003-f | risk | 2.95万亿未突破，警惕缩量冲高分化 | active |
| claim-20260520-003-g | operation | 核心持股、分歧低吸、做T、回避后排补涨 | active |
| claim-20260520-003-h | stock-view | 通富微电AI CPU封测核心资产重估 | active |
| claim-20260520-003-i | stock-view | 中科飞测检测量测核心弹性 | active |
| claim-20260520-003-j | stock-view | 新易盛光通信核心，重点看订单兑现 | active |
| claim-20260520-003-k | sector-theme | 昇腾分销机制与生态协同预期 | active |
| claim-20260520-003-l | risk | 英伟达财报利好兑现风险 | active |

### 矛盾/上修链接

| Claim A | 关系 | Claim B | 类型 |
|---------|------|---------|------|
| claim-20260520-001-e | superseded by | claim-20260520-003-c | cycle-shift |

说明：早盘判断泛科技修复但未出现绝对主线；复盘确认半导体接过主线扩散接力棒。这是日内盘面完成主线筛选后的上修，不是逻辑冲突。

### 更新 Wiki

- 新建 `每日复盘/2026-05-20.md`
- 新建 `市场分析/科创50虹吸.md`
- 新建 `市场分析/半导体产业链.md`
- 新建 `市场分析/光通信.md`
- 更新 `市场分析/半导体设备.md` — 补充中科飞测、盛美上海和半导体接棒后的设备材料定位
- 更新 `市场分析/长鑫存储产业链.md` — 补充复盘确认的半导体接棒与长鑫扩产四重共振
- 更新 `市场分析/量能判断.md` — 新增接近3万亿但未突破时的虹吸风险
- 更新 `市场分析/Token算力.md` — 新增昇腾分销机制与生态协同预期
- 更新 `投资方法论/主线判断.md` — 新增主线强度与全市场共振判断
- 更新 `投资方法论/交易纪律.md` — 新增科创虹吸纪律
- 更新 `投资方法论/仓位管理.md` — 新增结构牛仓位分层

### Framework 更新

- 更新 `framework/market-cycle-framework.md` — 新增局部虹吸 vs 全市场共振判别
- 更新 `framework/ai-investment-cycle.md` — 新增AI硬科技基础设施传导路径
- 更新 `framework/stock-analysis-playbook.md` — 个股分析流程中补充科创虹吸检查

### Durable Rule 判定

- **入 framework**：局部虹吸 vs 全市场共振、AI硬科技从光通信向半导体上游传导（2条）
- **保留 wiki**：通富微电、中科飞测、新易盛个股逻辑、昇腾分销机制预期、英伟达财报利好兑现风险

## 2026-05-21 | qing-learning ingest | 5月21日早盘、午盘与机构研报批处理

### 学习内容

- 处理 `sources/raw/财经/早盘：26-05-21：反弹途中不追高，聚焦AI与存储主线轮动.md`
- 处理 `sources/raw/财经/研报：26-05-21：京东方康宁合作，Micro-LED光互连与AI光学价值重塑.md`
- 处理 `sources/raw/财经/早盘补发：26-05-21：继续持股做T.md`
- 处理 `sources/raw/财经/午盘：26-05-21：情绪分歧日，半导体设备洗盘与Micro-LED补涨分化.md`
- 处理 `sources/raw/财经/午盘补发：26-05-21：仓位管理.md`
- 处理 `sources/raw/财经/尾盘补发：26-05-21：可以抄底.md`

### 抽取 Claims

| ID | 类型 | 主题 | 状态 |
|----|------|------|------|
| claim-20260521-001-a | technical-signal | 指数与量能 | active |
| claim-20260521-001-b | risk | 英伟达财报与AI硬件 | active |
| claim-20260521-001-c | sector-theme | 存储芯片 | active |
| claim-20260521-001-d | sector-theme | 玻璃基板与Micro-LED | active |
| claim-20260521-001-e | methodology | 科技内部扩散 | active |
| claim-20260521-001-f | sector-theme | 半导体设备 | active |
| claim-20260521-001-g | market-cycle | 情绪分歧日 | active |
| claim-20260521-001-h | methodology | 趋势主线与题材补涨 | active |
| claim-20260521-001-i | operation | 趋势去留 | active |
| claim-20260521-001-j | operation | 仓位管理 | active |
| claim-20260521-001-k | technical-signal | ABC结构与时间换空间 | active |
| claim-20260521-001-l | operation | 尾盘低吸 | active |
| claim-20260521-001-m | sector-theme | AI光互连与精密光学 | active |
| claim-20260521-001-n | risk | Micro-LED商业化 | active |

### 矛盾/上修链接

| Claim A | 关系 | Claim B | 类型 |
|---------|------|---------|------|
| claim-20260520-001-f | superseded by | claim-20260521-001-b | event-landed |
| claim-20260518-019-m | superseded by | claim-20260521-001-j | cycle-shift |

说明：英伟达财报窗口从“落地前压制”切换为“落地后看承接和兑现”；B浪完整吃完的操作建议，在5月21日情绪分歧和时间换空间语境下，上修为半仓轮动做T和趋势筛选。

### 更新 Wiki

- 新建 `每日复盘/2026-05-21.md`
- 新建 `市场分析/玻璃基板与Micro-LED.md`
- 更新 `市场分析/半导体产业链.md` — 新增5月21日分歧洗盘、趋势容量票和科技内部外溢判断
- 更新 `市场分析/半导体设备.md` — 新增半导体设备与Micro-LED抗分歧差异
- 更新 `市场分析/光通信.md` — 新增财报落地后“易中天”承接与CPO/OCS/精密光学扩展
- 更新 `市场分析/量能判断.md` — 新增放量无法上推、无量硬冲和时间换空间判断
- 更新 `市场分析/指数调整.md` — 新增ABC与时间换空间
- 更新 `市场分析/情绪判断.md` — 新增情绪载体缺失时降低预期
- 更新 `投资方法论/主线判断.md` — 新增主线外溢 vs 主线否定
- 更新 `投资方法论/仓位管理.md` — 新增半仓轮动做T和趋势筛选
- 更新 `投资方法论/交易纪律.md` — 新增分歧日趋势去留和2点55尾盘低吸条件单

### Framework 更新

- 更新 `framework/market-cycle-framework.md` — 新增趋势内分歧 vs 破趋势反抽、时间换空间纪律
- 更新 `framework/sector-diffusion-framework.md` — 新增主线外溢与主线否定区分
- 更新 `framework/ai-investment-cycle.md` — 新增AI光互连与精密光学扩展
- 更新 `framework/stock-analysis-playbook.md` — 个股分析流程中补充分歧日趋势分类和主线外溢判断

### Durable Rule 判定

- **入 framework**：趋势内分歧 vs 破趋势反抽、主线外溢 vs 主线否定、时间换空间阶段仓位纪律、AI光互连作为AI硬件链扩展（4条）
- **保留 wiki**：5月21日具体点位、京东方A/彩虹股份/戈碧迦等当日映射、2点55尾盘低吸条件单、Micro-LED公司池

## 2026-05-21 | qing-learning ingest | 5月21日晚间视频复盘：结构修正与半导体节点节奏

### 学习内容

- 处理 `sources/raw/财经/复盘：26-05-21：大盘结构修正，半导体操作节奏与4700反弹目标.md`

### 抽取 Claims

| ID | 类型 | 主题 | 状态 |
|----|------|------|------|
| claim-20260521-002-a | technical-signal | 大盘波浪结构 | active |
| claim-20260521-002-b | technical-signal | 上证指数关键点位 | active |
| claim-20260521-002-c | sector-theme | 半导体产业链 | active |
| claim-20260521-002-d | methodology | 事件节点交易 | active |
| claim-20260521-002-e | stock-view | 北方华创 | active |
| claim-20260521-002-f | sector-theme | 国产CPU/GPU与软件 | active |
| claim-20260521-002-g | sector-theme | 机器人 | active |
| claim-20260521-002-h | sector-theme | 光互联与微透镜 | active |
| claim-20260521-002-i | operation | 交易纪律 | active |
| claim-20260521-002-j | methodology | 业绩与景气度 | active |
| claim-20260521-002-k | macro | 外部风险 | active |

### 矛盾/上修链接

| Claim A | 关系 | Claim B | 类型 |
|---------|------|---------|------|
| claim-20260518-019-a | superseded by | claim-20260521-002-a | cycle-shift |
| claim-20260518-019-b | superseded by | claim-20260521-002-a | cycle-shift |
| claim-20260518-019-c | superseded by | claim-20260521-002-a | cycle-shift |
| claim-20260518-019-d | superseded by | claim-20260521-002-a | cycle-shift |
| claim-20260521-001-k | superseded by | claim-20260521-002-a | cycle-shift |

说明：5月18日视频的 ABC/B浪结构与5月21日午盘补发的“可能走ABC/时间换空间”，在晚间复盘中被一步到位后的新结构替代。新判断不是 true-conflict，而是实际走势触发的波浪级别修正。

### 更新 Wiki

- 更新 `每日复盘/2026-05-21.md` — 增加晚间视频复盘上修、4047/4170/4700、5月27日长鑫节点
- 更新 `市场分析/指数调整.md` — 新增一步到位后结构重判
- 更新 `市场分析/关键点位.md` — 将4200/4080旧点位降为历史预判，新增4047/4170/4700
- 更新 `市场分析/半导体产业链.md` — 新增长鑫上会、上市节点与半导体操作节奏
- 更新 `市场分析/半导体设备.md` — 新增北方华创布林线案例
- 新建 `市场分析/国产CPU_GPU与软件.md`
- 更新 `市场分析/光通信.md` — 新增光互联、微透镜只看一线光板块
- 更新 `投资方法论/交易纪律.md` — 新增结构动态修正纪律和回避蹭热点
- 更新 `投资方法论/仓位管理.md` — 新增事件节点仓位节奏

### Framework 更新

- 更新 `framework/market-cycle-framework.md` — 新增技术结构动态修正规则
- 更新 `framework/stock-analysis-playbook.md` — 个股分析流程中加入结构重判与事件节点拆分
- 更新 `framework/ai-investment-cycle.md` — 补充国产CPU/GPU/软件作为半导体减仓后的科技内部承接方向

### Durable Rule 判定

- **入 framework**：技术结构动态修正、事件节点拆分、半导体减仓后科技内部承接方向（3条）
- **保留 wiki**：4047/4170/4700具体点位、5月27日减仓节奏、北方华创布林线案例、机器人“大盘逆子”表述

## 2026-05-22 | qing-learning ingest | 5月21日复盘：真恐慌非崩盘与二次冰点策略

### 学习内容

- 处理 `sources/raw/财经/复盘：26-05-21：真恐慌非崩盘，科技洗牌与二次冰点策略.md`

### 抽取 Claims

| ID | 类型 | 主题 | 状态 |
|----|------|------|------|
| claim-20260521-003-a | market-cycle | 真恐慌非崩盘 | active |
| claim-20260521-003-b | market-cycle | 高位宽幅震荡 | active |
| claim-20260521-003-c | sector-theme | 科技主线筛选 | active |
| claim-20260521-003-d | sector-theme | PCB与先进封装 | active |
| claim-20260521-003-e | sector-theme | 机器人与具身智能 | active |
| claim-20260521-003-f | sector-theme | AI电源与超级电容 | active |
| claim-20260521-003-g | operation | 二次冰点低吸 | active |
| claim-20260521-003-h | operation | 仓位与持仓分层 | active |
| claim-20260521-003-i | stock-view | 5月22核心观察池 | active |
| claim-20260521-003-j | risk | 调整延长风险 | active |

### 矛盾/上修链接

| Claim A | 关系 | Claim B | 类型 |
|---------|------|---------|------|
| claim-20260521-003-e | contradicts | claim-20260521-002-g | cycle-shift / 条件差异 |

说明：5月21日晚间视频把机器人降级为调整期轮动题材、不适合重仓；本篇复盘把机器人列为二次冰点后的潜在承接方向。两者不是完全互斥：不重仓追机器人，与低开急杀后小仓位低吸主动修复，是两个不同条件下的操作。

### 更新 Wiki

- 更新 `每日复盘/2026-05-21.md` — 新增“真恐慌但非崩盘”、A档活口、潜在承接与二次冰点剧本
- 更新 `市场分析/情绪判断.md` — 新增真恐慌非崩盘与二次冰点观察
- 更新 `市场分析/量能判断.md` — 新增3.5万亿放量杀跌的承接判别
- 更新 `市场分析/半导体产业链.md` — 新增主线杀跌后转为个股筛选
- 新建 `市场分析/PCB与先进封装.md`
- 新建 `市场分析/机器人与具身智能.md`
- 新建 `市场分析/AI电源与超级电容.md`
- 更新 `投资方法论/主线判断.md` — 新增板块普涨后转入龙头筛选
- 更新 `投资方法论/仓位管理.md` — 新增半仓至六成与强中弱持仓分类
- 更新 `投资方法论/交易纪律.md` — 新增二次冰点低吸纪律

### Framework 更新

- 更新 `framework/market-cycle-framework.md` — 新增真恐慌非崩盘与二次冰点低吸条件
- 更新 `framework/sector-diffusion-framework.md` — 新增板块普涨后转入龙头筛选
- 更新 `framework/stock-analysis-playbook.md` — 新增高位放量大阴线判别与二次冰点低吸
- 更新 `framework/ai-investment-cycle.md` — 新增AI电源与超级电容作为算力链预期差分支

### Durable Rule 判定

- **入 framework**：真恐慌非崩盘、二次冰点低吸条件、板块普涨转龙头筛选、AI电源/超级电容作为AI基建链新分支（4条）
- **保留 wiki**：4773只下跌、395只跌超7%、5月22观察池、4200三日收复、跌停超过50只等短线细节

## 2026-05-22 | qing-learning ingest | 5月22日早盘：极致冰点后看修复质量

### 学习内容

- 处理 `sources/raw/财经/早盘：26-05-22：极致冰点后看修复质量，主线承接与30分钟底部钝化.md`

### 抽取 Claims

| ID | 类型 | 主题 | 状态 |
|----|------|------|------|
| claim-20260522-001-a | market-cycle | 极致冰点后修复质量 | active |
| claim-20260522-001-b | technical-signal | 上证关键点位 | active |
| claim-20260522-001-c | operation | 日内四阶段剧本 | active |
| claim-20260522-001-d | technical-signal | 30分钟底部钝化 | active |
| claim-20260522-001-e | operation | 先买后卖做T | active |
| claim-20260522-001-f | sector-theme | 半导体产业链 | active |
| claim-20260522-001-g | sector-theme | AI方向分类 | active |
| claim-20260522-001-h | sector-theme | 玻璃基板 | active |
| claim-20260522-001-i | sector-theme | 机器人 | active |
| claim-20260522-001-j | sector-theme | 量子计算 | active |

### 更新 Wiki

- 新建 `每日复盘/2026-05-22.md`
- 新建 `市场分析/量子计算.md`
- 更新 `市场分析/指数调整.md` — 新增4100短线修复位、4027长期趋势防线和30分钟底部钝化
- 更新 `市场分析/关键点位.md` — 新增4100、4080、4070、4027点位体系
- 更新 `市场分析/修复性质判断.md` — 新增极致冰点后的强弱修复判别
- 更新 `市场分析/半导体产业链.md` — 新增半导体修复看核心容量票止跌
- 更新 `市场分析/玻璃基板与Micro-LED.md` — 新增快速一致后的分歧承接标准
- 更新 `市场分析/机器人与具身智能.md` — 新增京东擎天租催化和强方向条件
- 更新 `投资方法论/交易纪律.md` — 新增先买后卖做T确认纪律
- 更新 `投资方法论/仓位管理.md` — 新增修复日四阶段仓位节奏

### Framework 更新

- 更新 `framework/market-cycle-framework.md` — 新增极致冰点后的日内四阶段确认和30分钟底部钝化
- 更新 `framework/stock-analysis-playbook.md` — 新增极致冰点次日的盘中执行与做T确认点

### Durable Rule 判定

- **入 framework**：极致冰点后的日内四阶段确认、30分钟底部钝化、先买后卖做T确认点（3条）
- **保留 wiki**：4100/4080/4070/4027具体点位、京东与擎天租合作、量子计算20亿美元事件、5月22盘中时间表

## 2026-05-22 | qing-learning ingest | 5月22日早盘补发：假摔确定，后面看修复

### 学习内容

- 处理 `sources/raw/财经/早盘补发：26-05-22：假摔确定，后面看修复.md`

### 抽取 Claims

| ID | 类型 | 主题 | 状态 |
|----|------|------|------|
| claim-20260522-002-a | market-cycle | 假摔确认 | active |
| claim-20260522-002-b | technical-signal | 趋势股新高反证见顶 | active |
| claim-20260522-002-c | operation | 假摔后的持股待涨 | active |
| claim-20260522-002-d | methodology | 修复等待节奏 | active |

### 上修链接

| New Claim | 关系 | Old Claim | 类型 |
|-----------|------|-----------|------|
| claim-20260522-002-a | supersedes | claim-20260522-001-a | intraday-update / 观察分支上修 |

说明：早盘主文提出“判断5月21日大阴线是假摔还是调整第一根大阴线”，补发将其上修为“假摔确定”。旧观点作为盘前观察框架仍保留，新 claim 记录盘中判断结果。

### 更新 Wiki

- 更新 `每日复盘/2026-05-22.md` — 新增早盘补发“假摔确认”
- 更新 `市场分析/修复性质判断.md` — 新增趋势股新高作为假摔辅助信号
- 更新 `市场分析/指数调整.md` — 新增趋势股新高反证见顶
- 更新 `投资方法论/交易纪律.md` — 新增假摔确认后的持股纪律
- 更新 `投资方法论/仓位管理.md` — 新增假摔确认后的核心仓处理

### Framework 更新

- 更新 `framework/market-cycle-framework.md` — 新增趋势股新高反证见顶
- 更新 `framework/stock-analysis-playbook.md` — 新增假摔确认后的个股处理规则

### Durable Rule 判定

- **入 framework**：趋势股新高反证见顶、假摔确认后的核心持股纪律（2条）
- **保留 wiki**：上午不修复等下午、下午不修复等下周等5月22日短线节奏表达

## 2026-05-22 | qing-learning ingest | 5月22日午盘补发：保持耐心，观察早盘观点连续性

### 学习内容

- 处理 `sources/raw/财经/午盘补发：26-05-22：保持耐心，注意观察早盘观点的连续性.md`

### 抽取 Claims

| ID | 类型 | 主题 | 状态 |
|----|------|------|------|
| claim-20260522-003-a | operation | 早盘策略连续性 | active |
| claim-20260522-003-b | operation | 超预期继续持股 | active |
| claim-20260522-003-c | technical-signal | 午后连续性验证指标 | active |
| claim-20260522-003-d | methodology | 周末产业逻辑复盘 | active |

### 更新 Wiki

- 更新 `每日复盘/2026-05-22.md` — 新增午盘补发“保持耐心，观察早盘观点连续性”
- 更新 `投资方法论/交易纪律.md` — 新增盘中观点连续性纪律
- 更新 `投资方法论/仓位管理.md` — 新增超预期继续持股的条件
- 更新 `投资方法论/主线判断.md` — 新增周末产业逻辑复盘要求

### Framework 更新

- 更新 `framework/stock-analysis-playbook.md` — 新增盘中补发延续早盘策略时的持股规则

### Durable Rule 判定

- **入 framework**：盘中观点连续性与超预期继续持股（1条）
- **保留 wiki**：3点后视频、周末整理等具体时间安排

---

## 关键结论

1. **市场周期**：4/6滞胀防御→4/14脱敏修复→4/20主升浪→4/26高位谨慎→5/15轮动调整→5/18局部新生启动→5/19左侧止跌拐点确认。
2. **活口分类**：分歧初期需区分退潮活口和复苏活口，前者容易补跌，后者才是下一轮主力。
3. **承接判断**：强分歧次日看关键位、量能降温、跌停家数下降、科技主线回流四个维度。
4. **修复性质**：防御上涨≠真正修复，只有科技主线回流才是进攻修复。
5. **长鑫产业链**：是5-18当天唯一建制进攻方向，被定义为新生启动，需观察指数共振。
6. **半导体设备**：5-18最强主线，中微订单上调+分拆IPO双重催化。
7. **Token算力**：商业化加速，运营商推动行业进入按效果付费新阶段。
8. **新型储能**：政策+算力中心配套双轮驱动，进入高速增长期。
9. **策略切换**：从进攻思维切换到防守反击思维，少追高、多等分歧，分歧中找机会、不追一致。
10. **劣性轮动识别**：通过核心分支修复情况判断轮动质量。
11. **个股跟踪**：富创精密（业绩+估值双底反转）、珂玛科技（陶瓷加热器四倍放量）、京仪装备（设备+零部件双重弹性）。
12. **交易纪律**：强分歧次日只做确认不做盲目追高，四个条件同时满足才能低吸。
13. **AI四阶段**：算力租赁→国产芯片→AIDC→CDN，产业扩散规律类比新能源。
14. **板块扩散**：核心资产→同产业链低位高弹性→更小市值更低位置。
15. **牛市纪律**：不要卖掉没涨的去追已涨的，高位爆量阴线就是出货。
16. **波浪理论**：时间空间只需锁定一个确定项；B浪空间4200点，C浪时间6月中下旬结束。
17. **B浪操作**：买阴不买阳，完整吃完再减仓；长鑫存储是B浪主线，低开=买点。
18. **拐点判断**：结合W底形态+外围消息给出概率判断，第二个W底成功率远高于第一个。
19. **产业链联动**：三大运营商调整→润建股份风险；英特尔企稳→中国长城机会。
