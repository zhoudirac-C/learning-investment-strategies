# M0-Chain：产业链知识库与持续跟踪管线

> 级别：M0（前置层，先于缠论引擎 M1-M7 和双引擎 M7-8）
> 核心目标：**像 UP 那样——知道整个产业逻辑，知道什么时候炒作什么**
> 日期：2026-08-30

---

## 一、UP 的工作模式拆解

UP 不是"筛研报→提取产业链"——那是静态的。UP 的模式是**发现+跟踪双引擎**：

### 1.1 UP 的两层能力

**第一层：发现新产业链逻辑（从0到1）**

UP 每天读研报/新闻/公告，从中识别出**新的产业逻辑**：

```
6月初：读到 PCB 行业涨价新闻 → 发现"AI PCB/CCL"产业链逻辑
  → 建立链条：上游材料(铜箔/玻璃布/树脂)→中游CCL(建滔/生益)→下游PCB(沪电/景旺)
  → 判断阶段：涨价初期 → 建议做上游材料（弹性最大）

8月初：读到日本WF6永久停产新闻 → 发现"电子特气"产业链逻辑
  → 建立链条：钨矿(出口管制)→WF6合成(昊华/三孚)→半导体制造
  → 判断阶段：涨价确认 → 建议做中游合成（确定性最高）

8月中：读到东吴证券超节点深度报告 → 发现"AI服务器/超节点"产业链逻辑
  → 建立链条：半导体设备→晶圆代工→服务器整机→液冷散热
  → 判断阶段：技术验证 → 建议观察，等超节点出货信号
```

**关键：UP 不是"从已有产业链里挑"，而是"从新信息里发现新产业链"。**

**第二层：跟踪已有产业链（从1到N）**

对已建立的产业链，UP 每天跟踪关键节点变化，判断阶段推进：

```
CCL 产业链（6月建立）：
  6月初：FR8价格开始上涨 → 阶段1涨价初期 → 做上游材料
  7月中：建滔满产满销 → 阶段2满产确认 → 转向中游CCL
  8月底：Rubin认证中 → 等阶段3业绩兑现 → 准备转向下游PCB

WF6 产业链（8月建立）：
  8月初：日本停产确认 → 阶段2涨价确认 → 做中游合成
  8月底：WF6价格稳定 → 继续阶段2 → 持有
```

### 1.2 管线需要的两层能力

| 能力 | UP 做的 | 管线要做的 |
|------|---------|-----------|
| **发现新产业链** | 读研报→识别新逻辑→建立链条 | 每日扫描→LLM识别新产业链逻辑→提议新增 |
| **跟踪已有产业链** | 跟踪关键节点→判断阶段推进 | 每日扫描→匹配关键节点→LLM判断阶段变化 |
| **时机判断** | 什么时候做上游/中游/下游 | 根据阶段判断→给出环节建议 |
| **标的选择** | 每个环节选1-2只龙头 | 从产业链知识库读取标的 |

---

## 二、产业链知识库设计

### 2.1 核心结构

每条产业链的知识库包含：

```yaml
chain_id: ai-pcb-ccl
name: AI PCB/CCL 产业链

# 产业逻辑（核心）
thesis: |
  AI服务器代际升级（GB200→Rubin→Rubin Ultra）→ PCB层数/材料等级提升
  → CCL从M7向M8/M9升级 → 上游材料（铜箔/玻璃布/树脂）涨价
  → 中游CCL满产满销 → 下游PCB价值量跃迁（单柜+233%）

# 传导路径（上游→中游→下游，每环标注关键节点）
chain:
  upstream:
    materials: [铜箔(HVLP4), 玻璃布(Q-Glass), 树脂, 硅微粉, 球形硅]
    key_nodes:
      - node: FR8价格
        current: 260-270元/张
        trend: 上涨
        signal: 继续上涨=上游受益确认
      - node: M6+高端产能
        current: 缺货
        trend: 持续
        signal: 缓解=上游涨价见顶
    stocks:
      - {code: "002409.SZ", name: 雅克科技, role: 球硅/前驱体, timing: 涨价初期介入}
      - {code: "000960.SZ", name: 中钨高新, role: 钻针原料, timing: PCB扩产时介入}
  
  midstream:
    materials: [覆铜板(CCL)]
    key_nodes:
      - node: 产能利用率
        current: 满产满销
        trend: 持续
        signal: 满产=中游确定性最高
      - node: 订单排期
        current: 排至2027年底
        trend: 延长
        signal: 继续延长=中游涨价可持续
    stocks:
      - {code: "600183.SH", name: 生益科技, role: CCL龙头, timing: 满产确认时介入}
  
  downstream:
    materials: [HDI, 高多层板, Midplane]
    key_nodes:
      - node: Rubin认证进度
        current: 认证中
        trend: 推进
        signal: 认证通过=下游业绩兑现
      - node: 单柜价值量
        current: +233%
        trend: 提升
        signal: 继续提升=下游弹性最大
    stocks:
      - {code: "002463.SZ", name: 沪电股份, role: 高多层板, timing: 业绩兑现时介入}
      - {code: "603228.SH", name: 景旺电子, role: PCB, timing: 业绩兑现时介入}

# 当前阶段判断（核心）
current_stage: 阶段2-满产确认  # 阶段1涨价初期/阶段2满产确认/阶段3业绩兑现/阶段4扩散
stage_confidence: 高  # 高/中/低
stage_evidence: |
  上游：FR8价格260-270元/张（持续上涨）
  中游：建滔/生益满产满销，订单排至2027
  下游：Rubin认证中，业绩待兑现

# 时机判断（什么时候做什么环节）
timing:
  current_recommendation: 中游CCL（确定性最高）
  next_trigger: Rubin认证通过 → 转向下游PCB
  risk: 上游涨价见顶 → 上游材料商毛利率回落

# 跟踪指标（每日检查）
daily_checks:
  - check: FR8价格
    source: 生意社/百川
    frequency: 每日
    threshold: 260-270元/张
    signal: 突破300=加强/跌破200=削弱
  - check: M8/M9认证新闻
    source: 研报/公告
    frequency: 每日
    signal: 认证通过=加强
  - check: 建滔/生益产能利用率
    source: 研报/产业新闻
    frequency: 每周
    signal: 满产=确认

# 历史记录（时机验证）
history:
  - date: 2026-06-21
    stage: 阶段1-涨价初期
    action: 介入上游材料（雅克科技）
    result: 待验证
  - date: 2026-08-28
    stage: 阶段2-满产确认
    action: 持有中游CCL（生益科技）
    result: 待验证
```

### 2.2 阶段划分（修正版，对齐 UP 推理框架）

UP 的阶段不是简单的"涨价初期→满产确认→业绩兑现"，而是基于**量价行为**的四阶段：

| 阶段 | 定义 | UP 的操作 | 关键信号 | 与缠论的对应 |
|------|------|----------|---------|------------|
| **阶段0-观察** | 无信号，等催化 | 不介入 | 无 | — |
| **阶段1-启动期** | 涨价信号出现，可介入 | **可介入**（右侧确认） | 涨价函/现货价上行/交期拉长 + 板块联动 | 缠论：中枢下方→中枢内（一买/二买区域） |
| **阶段2-加速期** | 涨价确认，但不追高 | **不追高，等分歧回踩** | 现货价加速上行 + 龙头股放量 | 缠论：中枢内→中枢上方（三买区域） |
| **阶段3-分歧期** | 高位分歧，等回踩确认 | **等回踩，确认后再介入** | 板块内部分化 + 高低切 | 缠论：中枢上方回试中枢上沿 |
| **阶段4-见顶期** | 量价背离，退出 | **退出** | 现货价回落 + 龙头放量滞涨 | 缠论：中枢上方顶背驰 |

**与原方案的区别**：
- 原方案的"阶段2-满产确认"= UP 的"阶段2-加速期"的一部分（满产是加速期的特征之一）
- UP 的"加速期不追高"比"满产确认做中游"更保守——满产确认时价格可能已高，追高风险大
- UP 的"分歧期"是原方案没有的——高位分歧时等回踩确认，比"业绩兑现"更早

### 2.3 16 条产业链的阶段划分（修正版）

| 产业链 | 当前阶段 | 时机建议 | 关键节点 |
|--------|---------|---------|---------|
| ai-pcb-ccl | 阶段2-满产确认 | 中游CCL | M8认证/Rubin量产 |
| ai-optical | 阶段1-技术验证 | 光模块龙头 | CPO量产/OCS商用 |
| ai-storage | 阶段2-涨价确认 | 上游设计+中游封测 | DRAM价格/长江存储IPO |
| ai-server | 阶段1-技术验证 | 整机龙头 | 超节点出货/液冷渗透 |
| ai-chip-design | 阶段0-观察 | 暂不介入 | FPGA国产化率 |
| ai-power | 阶段0-观察 | 暂不介入 | AIDC装机量 |
| mlcc-passive | 阶段2-涨价确认 | 上游粉体+中游MLCC | 国巨B/B值/涨价函 |
| electronic-gas | 阶段2-涨价确认 | 中游合成 | WF6价格/日本停产 |
| copper-aluminum | 阶段1-供给缺口 | 冶炼龙头 | 铜价/铝产能关停 |
| rare-metals | 阶段1-涨价初期 | 提纯龙头 | 铟价/磷化铟需求 |
| coal-coke | 阶段2-涨价确认 | 焦炭龙头 | 提涨轮次/煤炭PPI |
| photovoltaic | 阶段0-观察 | 暂不介入 | 组件价格/装机量 |
| semiconductor-equipment | 阶段0-观察 | 暂不介入 | EUV国产化进展 |
| aerospace | 阶段0-观察 | 暂不介入 | 可回收火箭首飞 |
| pharma | 阶段0-观察 | 暂不介入 | license-out交易 |
| robotics | 阶段0-观察 | 暂不介入 | Optimus量产 |

---

## 三、每日管线：发现 + 跟踪 双引擎

### 3.1 数据源（已有）

- 研报：`infra/data/research/reports/<date>.json`（227条/日）
- 公告：`infra/data/research/notices/<date>.json`（6342条/日）
- 板块行情：东财板块 API
- 大宗商品价格：生意社/百川（需新建采集）

### 3.2 每 30 分钟 tick 流程

```
┌─────────────────────────────────────────────────────────┐
│  引擎 A：发现新产业链（Discovery）                         │
│                                                         │
│  输入：当日研报 + 公告 + 板块异动                         │
│  规则筛选：                                               │
│    - 标题含"涨价/扩产/缺货/供需/产业链/深度/专题"          │
│    - 或板块涨幅 > 3% 且无明确产业链归属                   │
│  LLM 判断：                                               │
│    "这是一条新的产业链逻辑吗？如果是，提取：               │
│     产业链名称 / 驱动因素 / 传导路径 / 关键环节 / 标的"    │
│  输出：新产业链提议（写入 chain_registry.proposed）        │
│                                                         │
│  频率：每 30 分钟一个 tick（含 48h 去重 DB）              │
│  人工确认：新产业链提议需人工确认后才注册为 active         │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│  引擎 B：跟踪已有产业链（Tracking）                        │
│                                                         │
│  输入：当日研报 + 公告 + 板块行情 + 大宗价格               │
│  匹配：                                                   │
│    - 关键词匹配到 chain_registry 的 tracking_metrics     │
│    - 标的匹配到 chain_registry 的 stocks                 │
│  LLM 判断：                                               │
│    "这条信息对产业链哪个节点有影响？影响方向？"            │
│    "当前阶段判断是否需要调整？"                           │
│    "时机建议是否需要更新？"                               │
│  输出：产业链状态更新 + 日报                              │
│                                                         │
│  频率：每 30 分钟一个 tick（与发现引擎同节奏）            │
└─────────────────────────────────────────────────────────┘
```

### 3.3 引擎 A：发现新产业链（详细设计）

**触发条件**：
- 研报标题含"涨价/扩产/缺货/供需/产业链/深度/专题"且**不匹配已有产业链**
- 板块涨幅 > 3% 且无明确产业链归属
- 大宗商品价格异动（涨幅 > 5%）且无明确产业链归属

**LLM Prompt（发现模式）**：
```
你是产业链研究分析师。以下是今日的新信息，请判断是否存在"新的产业链逻辑"。

【已有产业链清单】（避免重复）：
{existing_chains}

【新信息】
{new_reports_and_notices}

判断标准：
1. 是否有一个清晰的"驱动因素"（涨价/技术升级/政策催化/供需缺口）？
2. 是否有一个可拆解的"传导路径"（上游→中游→下游）？
3. 是否有明确的"A股标的"可以承接这个逻辑？
4. 是否与已有产业链不重复？

如果满足以上 4 条，输出新产业链提议：
{
  "chain_id": "简短英文ID",
  "name": "产业链名称",
  "driver": "驱动因素（≤50字）",
  "thesis": "产业逻辑（≤100字）",
  "chain": {
    "upstream": {"materials": [...], "key_nodes": [...], "stocks": [...]},
    "midstream": {"materials": [...], "key_nodes": [...], "stocks": [...]},
    "downstream": {"materials": [...], "key_nodes": [...], "stocks": [...]}
  },
  "current_stage": "阶段0-观察/阶段1-涨价初期/阶段2-满产确认/阶段3-业绩兑现",
  "timing": "当前建议（做哪个环节/观察/回避）",
  "confidence": "高/中/低",
  "source": "信息来源（研报标题/公告/新闻）"
}

如果不满足，输出 null。
```

**输出**：`infra/data/chain_tracking/proposals_<date>.json`

**人工确认**：新产业链提议写入 `chain_registry.yaml` 的 `proposed` 区，需人工确认后转为 `active`。

### 3.4 引擎 B：跟踪已有产业链（详细设计）

**匹配规则**：
- 关键词匹配：研报/公告标题含 tracking_metrics 的关键词
- 标的匹配：公告涉及的股票代码在产业链 stocks 列表中
- 环节匹配：提到的环节在产业链 segments 中

**LLM Prompt（跟踪模式，嵌入 UP 推理框架）**：
```
你是产业链跟踪分析师。以下是产业链"{chain_name}"的当前状态和新信息。

【产业链当前状态】
产业逻辑：{thesis}
当前阶段：{current_stage}（置信度：{stage_confidence}）
关键节点：{key_nodes}
时机建议：{timing}

【新信息】
{new_info}

请按 UP 的 5 步推理框架分析：

Step 1 - 确认真实性：
  这条信息是否确认/加强/削弱/证伪了产业链逻辑？
  至少两个独立来源同向才确认（如研报+公告同时指向）。

Step 2 - 分析供需结构：
  这条信息影响的是需求侧、供给侧还是技术升级？
  对产业链的哪个环节（上游/中游/下游）影响最大？

Step 3 - 对比历史周期位置：
  当前处于底部/启动/加速/见顶哪一阶段？
  与历史高点的差距有多大？（如价格/产能利用率/订单排期）

Step 4 - 筛选受益标的：
  按三条逻辑筛选：①高端承接（能吃下外溢需求）
  ②上游供货（面向大厂）③弹性最大（产能占比大、对涨价敏感）

Step 5 - 判断持续性并给出操作建议：
  当前阶段是否变化？（不变/推进/回退）
  时机建议：现在该做哪个环节？
  - 阶段1-启动期：可介入（右侧确认）
  - 阶段2-加速期：不追高，等分歧回踩
  - 阶段3-分歧期：等回踩确认
  - 阶段4-见顶期：退出

输出 JSON：
{
  "step1_verification": {"verified": true/false, "sources": [...], "confidence": "高/中/低"},
  "step2_supply_demand": {"driver": "需求/供给/技术", "affected_segment": "上游/中游/下游"},
  "step3_cycle_position": {"current_stage": "...", "distance_to_peak": "..."},
  "step4_beneficiaries": [{"code": "...", "name": "...", "logic": "高端承接/上游供货/弹性最大"}],
  "step5_recommendation": {"stage_change": "unchanged|forward|backward", "new_stage": "...", "timing": "...", "action": "..."}
}
```

**输出**：`infra/data/chain_tracking/daily_report_<date>.md`

**Step 6 逻辑演化提案（2026-08-31 补）**：跟踪不只更新阶段——LLM 在同一次调用
里顺带判断新信息是否给产业链【逻辑结构本身】带来结构性增量（环节细化
refine_segment / 新增节点 add_node / 重心转移 focus_shift / thesis 修正
update_thesis / 证伪更新 update_falsification / 跨链传导 add_relation）。
有增量 → 落 `evolution_pending.json` 提案池（同 identity 命中只累积证据），
人工 `python scripts/chain_tracker.py evolution confirm <proposal_id>` 才应用到
chain.yaml（schema 强校验兜底）。阶段更新保持自动（走一格护栏），结构变化走
人工确认——对齐决策 4 的防幻觉哲学。设计与实现细节见
`docs/superpowers/specs/2026-08-31-chain-logic-evolution-design.md`。

---

## 四、与现有系统的对接

### 4.1 与缠论引擎（M7）的关系

```
产业链知识库（M0-Chain）  →  定方向（做哪个产业链的哪个环节）
  ↓
缠论引擎（M7）  →  定买卖点（什么时候买/卖）
  ↓
双引擎（M7-8）  →  定操作（量能/状态/因子确认）
```

**串联逻辑**：
1. 产业链分析：AI PCB/CCL 产业链当前阶段2，建议做中游CCL（生益科技）
2. 缠论引擎：生益科技 60m 中枢上方，30m 三买成立，可介入
3. 双引擎：量能确认放量突破，市场状态正常，因子评分前10

### 4.2 与 factor_rank.py 的关系

factor_rank 的标的池从产业链知识库读取：
- 只评"当前阶段建议介入"的产业链标的
- 排除"阶段0-观察"的产业链标的

### 4.3 系统接线完成记录（2026-08-31，详见 docs/tasks/m0-chain-integration-plan.md）

四步接线全部落地：
1. **链状态注入 agent context**：`store.chain_states_view()` 19 链 compact 视图，
   挂监控 cron 主路径 + market_summary 节点（早盘/盘中/复盘全覆盖）——LLM 分析
   板块异动时能回答"属于哪条链、几阶段、做哪个环节"。uvicorn 已重启生效。
2. **chain_scanner 知识库 fallback**：direction_pool 无配置或全涨时，从 chain.yaml
   找同链其他环节（阶段0链不推荐）。
3. **板块异动触发源**：发现引擎接入本地 fund_flow 落盘（387 概念，|涨跌幅|≥3%
   无归属 → 候选），绕开不可达的东财板块 API。
4. **factor_rank 阶段过滤**：默认排除只属于阶段0链的标的（`--no-chain-filter` 可关）。

---

## 五、实施计划（调研后细化版）

### Phase 1：产业链知识库建设（1 周）

**目标**：把 16 条产业链的完整知识库建好

**调研结论**：
- M0 已有 3 条产业链知识库（changxin-dram / domestic-compute / ai-infra-energy），结构为 `chain.yaml`（schema 校验）+ `research.md`（研究报告）
- 现有 chain.yaml 的 segments 有 16-19 个环节，但 `value_share`/`barrier`/`landscape` 等字段全为 None——需要填充
- 现有 research.md 是完整的研究报告（6867-9144 字），结构为"章节→子章节→标的表格"

**任务拆分**：

| 任务 | 内容 | 工作量 | 依赖 |
|------|------|--------|------|
| T1 | 从 watchlist.yaml 迁移 16 条产业链的标的和定位到 chain_registry.yaml | 0.5 天 | watchlist.yaml 已有 |
| T2 | 为每条产业链编写 thesis（产业逻辑） | 1 天 | 需要 LLM 辅助 + 人工审核 |
| T3 | 为每条产业链拆解 upstream/midstream/downstream 环节 | 1 天 | 需要 LLM 辅助 + 人工审核 |
| T4 | 为每条产业链设定 tracking_metrics（跟踪指标） | 0.5 天 | 参考 UP 的 market_checks |
| T5 | 为每条产业链设定 falsification（证伪条件） | 0.5 天 | 参考 UP 的 upstream_cycle 证伪条件 |
| T6 | 为每条产业链设定 chain_relations（跨链传导） | 0.5 天 | 如 ai-server→ai-power |
| T7 | 填充现有 3 条产业链（changxin-dram/domestic-compute/ai-infra-energy）的空字段 | 1 天 | 已有 chain.yaml 骨架 |
| T8 | 验证：16 条产业链的 YAML 全部通过 schema 校验 | 0.5 天 | T2-T7 完成后 |

**验收**：
- 每条产业链的 thesis 是完整的产业逻辑（不是一句话）
- 每条产业链的 chain 有明确的传导路径和关键节点
- 每条产业链的 timing 有明确的时机判断（现在该做哪个环节）
- 每条产业链的 falsification 有明确的证伪条件
- 每条产业链的 chain_relations 有跨链传导标注（如有）

### Phase 2：跟踪引擎（引擎 B，1 周）

**目标**：**每 30 分钟**扫描增量信息，更新已有产业链状态

**节奏设计（2026-08-30 修订：每日一次 → 每 30 分钟一次）**：

```
每 30 分钟一个 tick：
  1. 拉取增量信息（研报 API + 公告 API + 期货行情）
  2. 去重过滤：查 processed_items DB，48h 内处理过的跳过
  3. 新信息批 → LLM 分析（5 步推理框架）
  4. 有状态变化的链 → 更新 chain.yaml + 追加事件
  5. 有变化的链 → 输出增量报告（无变化则静默）
  6. TTL 清理：删除 processed_at < now-48h 的记录
```

**为什么 30 分钟**：
- 公告/涨价函是盘中事件，每日一次会错过盘中催化（下午出涨价函→次日才知道→炒作已启动）
- 去重后每日信息总量不变，只是批量变小——LLM 总成本持平，单次 prompt 更短更便宜
- 期货行情/盘面异动跟踪天然适合 30 分钟节奏

**去重 DB 设计**（`infra/data/chain_tracking/processed_items.db`，SQLite）：

```sql
CREATE TABLE processed_items (
    info_id     TEXT PRIMARY KEY,   -- 去重键：研报=infoCode，公告=公告ID，期货=品种+日期+窗口
    source      TEXT NOT NULL,      -- report / notice / futures
    title       TEXT,
    published_at TEXT,              -- 信息发布时间
    processed_at TEXT NOT NULL,     -- 处理时间（TTL 依据）
    chain_id    TEXT,               -- 匹配到的产业链（未匹配为 NULL）
    llm_verdict TEXT,               -- LLM 结论摘要（confirmed/strengthening/weakening/falsified/irrelevant）
    analysis    TEXT                -- LLM 完整分析 JSON
);
CREATE INDEX idx_processed_at ON processed_items(processed_at);
CREATE INDEX idx_chain ON processed_items(chain_id);
```

**三条硬规则**：
1. **去重键用 info_id 不用标题**——同一研报会被多个渠道转载，标题去重会漏
2. **空批次静默**——本 tick 无新信息则不调 LLM、不输出任何内容（避免 48 次/天的空报告刷屏）
3. **TTL 清理内置在每个 tick**——顺手 DELETE 过期记录，不设独立清理任务

**调研结论**：
- 东财研报 API 每日 227 条，其中产业链相关行业的约 100 条（半导体 28 + 电池 20 + 通信 19 + 计算机 12 + 电力 9 + 消费电子 6 + 元件 3 + 光学 2 + 通信服务 1）
- 东财公告 API 每日 6342 条，大部分是噪音（质押/减持/股东大会），需要 LLM 筛选
- 大宗商品价格数据源：生意社/百川盈孚需要浏览器渲染（JS 页面），不适合 API 直接抓取；新浪现货价格只有 3 个品种（BDI/钢坯/铁矿），不够用；**建议用东财期货行情（上期所/大商所/郑商所）替代**，覆盖铜/铝/镍/锡/螺纹/焦炭等
- LLM 调用走 **Hermes 全局模型路由**（`model_route`），不硬编码模型名。路由策略：产业链分析用 `cheapest`（GLM-4-flash 级别），复杂产业链拆解用 `smartest`（深度模型）。单次调用 ~2000 token，每日 ~¥0.5。

**任务拆分**：

| 任务 | 内容 | 工作量 | 依赖 |
|------|------|--------|------|
| T9 | 写 `scripts/chain_tracker.py` 主入口（30 分钟 tick 模式） | 0.5 天 | Phase 1 完成 |
| T10 | 实现 processed_items 去重 DB（建表/info_id 去重/TTL 清理） | 0.5 天 | T9 |
| T11 | 实现信息匹配：研报/公告 → 产业链关键词匹配 | 1 天 | chain_registry.yaml 的 tracking_metrics |
| T12 | 实现 LLM 分析：走 Hermes 模型路由，按 5 步推理框架分析 | 1 天 | T10-T11 |
| T13 | 实现状态更新：更新 chain.yaml 的 current_stage / timing + 追加 history 事件 | 0.5 天 | T12 完成 |
| T14 | 实现增量报告输出：仅有变化的链输出，无变化静默 | 0.5 天 | T13 完成 |
| T15 | 实现大宗商品价格跟踪：东财期货行情 → 价格异动检测（30 分钟窗口） | 1 天 | 东财期货 API |
| T16 | 验证：给定一天数据回放，LLM 判断与人工判断一致率 > 70%；重复回放零重复处理 | 0.5 天 | T9-T15 完成 |

**验收**：
- 30 分钟 tick 端到端 < 2 分钟（拉取+去重+分析+落盘）
- 同一信息重复喂入 100%，processed_items 去重后 LLM 调用为 0（幂等）
- 48h 前的记录自动清理，DB 不膨胀
- 给定一天数据，能正确匹配到已有产业链的关键节点
- LLM 判断的阶段变化与人工判断一致率 > 70%
- 每日产出 3-5 条有变化的产业链记录（有空批次静默，不刷屏）
- 大宗商品价格异动能正确匹配到产业链（如铜价涨→铜铝产业链）

**Phase 2 完成记录（2026-08-31）**：

实现：`src/investment_engine/chain_tracker/`（dedup/items/matching/analysis/state/report/futures/core）
+ 薄入口 `scripts/chain_tracker.py`，计划文档 `docs/tasks/m0-chain-phase2-plan.md`。
测试 45 个全绿（`tests/investment_engine/test_chain_tracker_*.py`），全量 513+ 无回归。

实测偏差与修正：
1. `model_route` 在代码中不存在 → 复用 `blindtest.replay.call_deepseek`（自动落账
   `log/llm_calls.jsonl`），sensenova 429 时回落 GLM glm-4.7-flash（`ZHIPU_API_KEY`）。
2. 东财 push2 本机不可达 → 期货行情改用新浪 `hq.sinajs.cn/list=nf_XX0` 主力连续合约。
3. 匹配洪泛修正：公告只做代码/名称匹配；泛化词停用（工业/电力/通信/AI 等）。
   修正前 615 pairs/天 → 修正后 213 pairs/天。
4. LLM 失败不落账（瞬时故障下一 tick 自愈重试）；逐链即时落账（进程被杀不丢进度，
   实测被 timeout 杀死后 189 条已分析信息丢失的教训）。

回放验证（2026-08-28 全天 6571 条，GLM 通道）：
- 幂等 ✅：重复回放 new=0 / llm=0 / changes=0。
- 13 链全部分析完成；5 链推进阶段、8 链维持。日报产出 5 条变化记录。
- 阶段变化与人工判断一致率 **4/6 = 67%**（低于 70% 门槛）：ai-infra-energy 0→1、
  ai-power 0→1、ai-server 1→2、changxin-dram 1→2 同意；ai-optical 1→2（证据是液冷，
  不对口 CPO/OCS 节点）与 domestic-compute 1→2（"业绩符合预期"强度不足）不同意。
- 整体方向判断（含 unchanged/irrelevant）一致率 ~85%（11/13）。
- 阶段护栏实测有效：LLM 多次 forward 但 new_stage 误填当前阶段，被截断到相邻阶段。
- Phase 4 调优方向：prompt 增加硬约束"stage_change=forward 需直接命中本链
  tracking_metrics 关键节点，泛化 AI 情绪不构成推进证据"。
- 已知限制：GLM 降级通道 ~65s/链，全日回放（13 链）约 15 分钟 > 2 分钟预算；
  正常 30 分钟 tick 批量小（1-3 链），主通道健康时满足预算。

### Phase 3：发现引擎（引擎 A，1 周）

**目标**：每天自动扫描新信息，发现新产业链逻辑

**调研结论**：
- LLM 实测能正确识别新产业链逻辑（5 条测试标题全部正确识别），模型走 Hermes 全局路由
- 需要去重：已有产业链清单必须作为 prompt 输入，避免重复提议
- 需要过滤：不是所有"涨价"都是产业链逻辑（如"煤炭进口数据拆解"是已有产业链的增量信息，不是新产业链）
- 发现频率：每月约 2-5 篇真正的产业链深度研报，每日可能有 0-2 条新产业链提议

**任务拆分**：

| 任务 | 内容 | 工作量 | 依赖 |
|------|------|--------|------|
| T16 | 写 `scripts/chain_discovery.py` 主入口 | 0.5 天 | Phase 1 完成 |
| T17 | 实现触发条件：标题含关键词 + 不匹配已有产业链 | 0.5 天 | chain_registry.yaml |
| T18 | 实现 LLM 判断：调 GLM-4-flash 识别新产业链逻辑 | 1 天 | GLM API 可用 |
| T19 | 实现去重：与已有产业链清单对比，避免重复 | 0.5 天 | T18 完成 |
| T20 | 实现提议输出：JSON 格式，写入 `proposed` 区 | 0.5 天 | T19 完成 |
| T21 | 实现人工确认流程：proposed → active 的确认机制 | 0.5 天 | T20 完成 |
| T22 | 验证：给定一天数据，能识别出至少 1 条新产业链提议 | 0.5 天 | T16-T21 完成 |

**验收**：
- 给定一天数据，能识别出至少 1 条新产业链提议
- 提议质量：驱动因素清晰 + 传导路径可拆解 + 有 A 股标的
- 与已有产业链不重复
- 人工确认流程可用

**Phase 3 完成记录（2026-08-31）**：

实现：`src/investment_engine/chain_tracker/` 新增 discovery（T17 触发过滤/T18 发现
prompt/T19 提议去重）+ proposals（T20 持久化/T21 confirm/reject）+ discovery_core
（T16 编排），薄入口 `scripts/chain_discovery.py`（scan 默认 / list / confirm / reject），
计划文档 `docs/tasks/m0-chain-phase3-plan.md`。测试新增 43 个全绿
（`test_chain_tracker_{discovery,proposals,discovery_core}.py`），复用改动
（analysis.core 接口公开化）后 Phase 2 存量测试无回归；全量 1297 过、5 失败均为
与 chain_tracker 无关的预存失败（test_buy_signal_e2e / test_discover_judge_relation_retry
/ test_pre_fetch_klines，失败文件不 import 本模块）。

实测偏差与修正：
1. 提议不落 chain_registry.yaml（Phase 2 已决策 registry 无代码读写）→ pending 落
   `infra/data/chain_tracking/proposals_pending.json`；confirm 直接创建
   `knowledge/industry-chains/<id>/chain.yaml`（schema 强校验，跟踪引擎自动纳入）。
2. 触发源只有研报+公告标题关键词：板块 API 本机不可达（Phase 2 实测）；期货品种全部
   在 FUTURES_CHAIN_MAP 内，不构成无归属异动。发现 tick 不拉期货。
3. 输出从任务书的单条提议改为 `{"proposals": [...]}`（0..3 条/批）——同日相关新闻
   聚类成一条提议；阶段枚举对齐 schema.STAGE_LEVELS（任务书 §3.3 是旧版阶段名）。
4. 去重三层：discovery_items.db 48h（独立于跟踪 DB，否则跟踪落账的未匹配项会抑制
   发现候选）→ prompt 内嵌已有链+pending 清单 → 后置 chain_id/name 碰撞过滤。

回放验证（2026-08-28 全天 6569 条，GLM 通道）：
- 漏斗：6569 条 → 触发词 5 条 → 匹配已有链 0 条 → 候选 5 条 → 1 次 LLM 调用。
- 幂等 ✅：重复回放 new=0 / llm=0 / proposals=0。
- 产出 2 条提议（达到 ≥1 验收线），与已有 19 链不重复：
  carbon-fiber 碳纤维（阶段2-加速期/高置信）、polyester-fiber 涤纶长丝
  （阶段1-启动期/高置信），均已落 proposals_pending.json 待人工确认。
- 质量观察：两条提议各只有 1 条来源（且 carbon-fiber 源自单家公司半年报点评，
  严格按 prompt"单家公司事件不算新产业链"应被过滤）；LLM 正确拒绝了
  光模块深度报告（已有 ai-optical 链）和北交所专题（非产业链）。
- Phase 4 调优方向：prompt 增加硬约束"单家公司点评需至少有产业链级证据
  （价格/产能/供需数据）才可提议"；置信度高的提议要求 ≥2 独立来源。

**候选池 + 证据累积（2026-08-31 增补，用户决策）**：提议不急着 confirm/reject，
在 pending 候选池里躺一段时间，每个发现 tick 把命中提议信号的新信息挂为证据
（attach_evidence，落账 verdict=evidence，不再耗 LLM）；证据够了人工 confirm
进观察列表——confirm 一律 阶段0-观察 起步（LLM 初判留痕 stage_evidence），
阶段推进交给跟踪引擎。详见 m0-chain-phase3-plan.md 增补节。

### Phase 4：时机判断校准（2-4 周）

**目标**：UP 续费期内做对比校准

**调研结论**：
- UP 的 5 步推理框架（确认→供需→周期→标的→持续性）已内嵌到 LLM prompt
- UP 的证伪条件（4 条）已内嵌到 chain_registry.yaml 的 falsification 字段
- UP 的"加速期不追高/分歧期等回踩"操作建议已内嵌到阶段划分

**⚠️ 双锚校准（2026-08-31 修订，UP 充电内容次月停更）**：
UP 判断是校准信号而非运行依赖——引擎运行时只吃研报/公告/行情，断供不影响
日常运行，影响的是对标调优的对照系。校准锚因此分两段：
1. **UP 期内（~2026-09 底）**：密集跑 T23 每日对比，差异即调 prompt（T24），
   优先做 T26 证伪条件验证（UP 最值钱的是退出纪律）。
2. **断供后**：校准锚切换为**市场结果验证**——chain.yaml `history[].result`
   的"待验证"字段即回写钩子，阶段判断发出 N 个交易日后用实际行情回写
   （判启动后涨了吗？证伪触发后跌了吗？），模式照抄 shadow 预测到期评分回写
   （evals/shadow）。新增 T27 结果回写验证器。

**任务拆分**：

| 任务 | 内容 | 工作量 | 依赖 |
|------|------|--------|------|
| T23 | 每日对比：管线判断 vs UP 判断（工具：scripts/chain_up_compare.py collect/log/stats） | 持续 | UP 续费期内 |
| T24 | Prompt 调优：根据差异调整 LLM prompt | 持续 | T23 发现差异后 |
| T25 | 阶段判断校准：对比管线的阶段划分与 UP 的实际操作 | 持续 | T23 发现差异后 |
| T26 | 证伪条件验证：对比管线的证伪判断与 UP 的实际退出 | 持续 | T23 发现差异后 |
| T27 | 结果回写验证器：history 待验证条目到期用行情回写（断供后的校准锚） | 1 天 | 行情 fetcher 已有 |

**进展（2026-08-31）**：
- T24 首轮调优已完成（依据 Phase 2/3 回放实测差异）：跟踪 prompt 加硬约束
  "forward 需直接命中本链 tracking_metrics 关键节点，泛化情绪/业绩符合预期
  不构成推进证据"；发现 prompt 加"单家公司点评需产业链级证据 + confidence=高
  需 ≥2 独立来源"。
- T24 回放复测（2026-08-28 数据，GLM 通道）**双向生效**：
  - 跟踪侧：ai-optical / domestic-compute 两链重打（52 对匹配、2 次 LLM）
    阶段变化 = 0——上轮被误推进的两链本轮均维持，硬约束生效。
  - 发现侧：carbon-fiber（单家公司半年报点评）被过滤；涤纶长丝/黄磷提议保留但
    confidence 降为 中（单来源正确封顶，chain_id 为 chemical-fiber /
    phosphorus-chemical）。
  - 注意：复测用临时目录，真账 proposals_pending.json 里仍是调优前的
    carbon-fiber / polyester-fiber 两条，处置权在用户（候选池继续躺或 reject）。
- T23 工具底座已建：up_compare.py（claim↔链匹配 / 对比草稿 / 结论落账 /
  重合度统计），16 测试全绿；`collect --date 2026-08-30` 真实冒烟命中 7 链，
  草稿 up_compare_2026-08-30.md 已生成待人工填结论。

**cron 接线（2026-08-31，用户决策：LLM 跟随 Hermes 全局配置不写死）**：
- `default_llm_call` 通道优先级改为：`CHAIN_TRACKER_LLM=glm` 逃生口 →
  **Hermes 全局配置**（resolve_runtime_provider，与调度器同函数）→
  .env sensenova → GLM 兜底。全局换模型两引擎自动跟随。
- Hermes cron 注册两个 no-agent 任务（deliver=local，工作目录=仓库）：
  产业链跟踪tick `84a14f16201a`（5,35 9-16,18-21 * * *）、
  产业链发现tick `83e2c5e4b0ef`（12,42 9-16,18-21 * * *）。
  包装脚本 ~/.hermes/scripts/qing_chain_tracker.py / qing_chain_discovery.py
  （惯例见 AGENTS.md Cron Script Architecture）。
- 冒烟（2026-08-31 12:09 手动触发跟踪 tick）：completed，fetched=1349 /
  new=48 / llm=6 / errors=0 / changes=0；llm_calls.jsonl 出现
  `chain_tracker:hermes:glm-5.3-flash` 标签 = 全局通道生效。
  实测注意：盘中积累批次 6 链 × GLM ~2min/链 ≈ 12min，超出 Phase 2 的
  2min 预算（预算按 1-3 链/tick 估）——全天多 tick 分摊后通常达标，
  但"上午积累首 tick"会偏慢；不影响 30min 节奏（无重叠）。
- 冒烟（2026-08-31 12:21 发现 tick）：completed，fetched=1358 / 候选 3 /
  llm=1 / errors=0。两个机制首次生产生效：① 证据累积——1 条新信息命中
  pending 的 polyester-fiber 并挂为证据（未耗 LLM）；② 新提议
  ptfe-fluorochemical（PTFE/氟化工，阶段0-观察/置信度中）已入候选池。
  LLM 落账标签 `chain_discovery:hermes:glm-5.3-flash` = 全局通道生效。

**验收**：
- 连续 5 天，管线的时机建议与 UP 重合度 > 60%（UP 期内口径）
- 管线能识别出 UP 没覆盖的新产业链（增量价值）
- 管线的证伪判断与 UP 的实际退出一致率 > 70%（UP 期内口径）
- 断供后口径：history 回写中，阶段推进后 5 日标的收益方向一致率 > 60%

---

## 六、关键设计决策

1. **发现 + 跟踪 双引擎**：不是只跟踪已有产业链，而是每天扫描新信息**发现新产业链**。UP 的核心能力一半是"发现新逻辑"（6月发现CCL、8月发现WF6），一半是"跟踪已有逻辑"。管线必须两层都有。

2. **产业逻辑优先于标的**：先理解产业链的传导关系和当前阶段，再谈标的。不是"雅克科技涨了多少"，而是"AI PCB/CCL 产业链当前阶段2，上游材料涨价确认，中游满产确定性最高"。

3. **时机判断是核心**：知道什么时候做上游（涨价初期）vs 中游（满产确认）vs 下游（业绩兑现）。这是 UP 最值钱的能力。

4. **发现引擎需要人工确认**：LLM 提议的新产业链不是直接注册，而是写入 `proposed` 区，人工确认后才转为 `active`。避免 LLM 幻觉导致产业链爆炸。

5. **持续跟踪，不是一次性**：产业链是动态演化的，每天跟踪关键节点的变化，判断对阶段的影响。

6. **与缠论串联，不是替代**：产业链分析定"方向"（做哪个环节），缠论定"买卖点"（什么时候买/卖）。

7. **不追求全，追求准**：16 条产业链里，当前只有 7 条 active（有明确信号），其余 9 条 watch（观察中）。不是所有产业链都要做，而是聚焦在有信号的。

8. **证伪条件系统化**：每条产业链必须有明确的证伪条件（UP 的 4 条：现货价连续2周回落/下游砍单/大盘破位/核心标放量滞涨），写入 `falsification` 字段。LLM 跟踪时必须检查证伪条件是否触发。

9. **跨产业链二级传导**：UP 知道"AI算力爆发→电力需求→绿电/AIDC"——这是跨产业链的二级传导。管线设计一个 `chain_relations` 字段，标注产业链之间的传导关系（如 ai-server → ai-power）。

---

## 七、与 M0 已有成果的关系

M0 已完成：
- ✅ T5 迁移 3 篇深度研究入 `knowledge/industry-chains/`（changxin-dram / domestic-compute / ai-infra-energy）
- ✅ T2 chain.yaml 校验器
- ✅ T3 知识库读写层
- ✅ T4 深度研究 md 解析器

M0-Chain 新增：
- 🆕 产业链知识库扩展：3 条 → 16 条（含完整的 thesis/chain/current_stage/timing/daily_checks）
- 🆕 每日跟踪管线：扫描新信息 → 匹配关键节点 → LLM 分析 → 更新产业链状态
- 🆕 时机判断：知道什么时候做哪个环节
- 🆕 与缠论引擎串联：产业链定方向 → 缠论定买卖点

---

## 八、文档引用

- 产业链知识库模板：`knowledge/industry-chains/<chain_id>/chain.yaml`
- 每日跟踪输出：`infra/data/chain_tracking/daily_report_<date>.md`
- 推理模式库：`framework/reasoning-patterns.yaml`（含 upstream_cycle 等 10 个模式）
- UP 术语表：`framework/up-glossary.md`
- 缠论引擎：`docs/design/chanlun-m7-multitimeframe-skill.md`（M7-1~M7-8）
- 双引擎：`docs/tasks/chanlun-m7-8-application-layer-enhancements.md`
