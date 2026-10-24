# 产业链持续跟踪管线 — 立项文档

> 日期：2026-08-30
> 性质：基础设施立项（选股层核心能力建设）
> 核心设计：**以产业链为线，每日增量跟踪**。不是每月筛一次深度研报，
>   而是每天扫描新信息，判断对已有产业链逻辑的影响（确认/加强/削弱/证伪），
>   并评估对标的的股价影响。

---

## 一、设计思路

### 1.1 与"筛深度研报"的本质区别

| 模式 | 频率 | 单位 | 输出 |
|------|------|------|------|
| ~~筛深度研报~~ | 每月 1 次 | 以研报为单位 | 一次性产业链全景 |
| **产业链持续跟踪** | **每日 1 次** | **以产业链为单位** | **增量影响评估** |

核心区别：产业链不是"一篇研报写完了就结束"——它是**持续演化的**。CCL 涨价链从 6 月建立至今仍在演进（FR8 价格、M8 认证进度、订单排队情况每天都在变化）。UP 做的不是"每月读一篇深度报告"，而是**每天跟踪已有方向的增量信息**。

### 1.2 UP 的实际工作模式（从 strategy_pack/watchlist 反推）

UP 的 watchlist.yaml 里每个主题有 `market_checks`（验证指标），这些指标就是**跟踪线索**：

```
CCL 产业链的 market_checks：
  - CCL技术等级：M7→M8→M9 认证进度
  - 涨价持续性：FR8 价格是否继续上行
  - 供给瓶颈：M6+高端缺货是否缓解
  - 国产化进度：Df 0.0015 性能控制 vs SABIC 差距
  - Midplane增量：Rubin NVL144 认证进度
```

UP 每天做的事：**检查这些验证指标是否有新变化**，然后判断对产业链逻辑的影响。

**管线要做的就是把"检查验证指标"自动化。**

---

## 二、架构设计

### 2.1 数据流

```
产业链注册表（chain_registry.yaml）
  │
  ├─ 每个产业链一条线，含：
  │    - chain_id / name / thesis（核心逻辑）
  │    - tracking_metrics（跟踪指标列表）
  │    - stocks（标的映射）
  │    - current_status（当前状态：确认/加强/削弱/证伪）
  │    - last_updated / last_verified
  │
  ▼
每日增量信息扫描
  │
  ├─ 研报 API（新发布的研报，匹配产业链关键词）
  ├─ 公告 API（提价/扩产/签单/投产，匹配标的或环节）
  ├─ 大宗商品价格（生意社/百川，匹配价格指标）
  ├─ 板块行情（东财，验证标的是否按逻辑反应）
  └─ 外盘映射（overnight_us_fetch，验证海外催化）
  │
  ▼
LLM 增量分析
  │
  ├─ 输入：新信息 + 产业链当前状态
  ├─ 判断：这条信息对产业链逻辑是 确认/加强/削弱/证伪/无关
  ├─ 评估：对标的的潜在股价影响（方向+幅度+时间窗口）
  └─ 输出：增量影响报告
  │
  ▼
产业链状态更新
  │
  ├─ 更新 chain_registry.yaml 的 current_status
  ├─ 更新 tracking_metrics 的最新值
  ├─ 如果状态变为"证伪"→ 标记退出观察
  └─ 如果状态变为"加强"→ 更新标的评级
  │
  ▼
标的池更新
  │
  └─ dynamic_watchlist.yaml（每日更新）
```

### 2.2 产业链注册表（chain_registry.yaml）

每条产业链线的完整结构：

```yaml
chains:
  - chain_id: ccl-ai-pcb
    name: "CCL/覆铜板产业链（AI PCB Rubin 驱动）"
    created: "2026-06-21"  # 首次建立日期
    thesis: "AI服务器代际升级→CCL材料等级提升（M7→M8→M9）→上游材料涨价→中游满产满销→下游PCB价值量跃迁"
    status: active  # active / watch / exited
    current_signal: confirmed  # confirmed / strengthening / weakening / falsified
    signal_updated: "2026-08-28"
    
    tracking_metrics:
      - metric: "FR8 价格"
        current_value: "260-270 元/张"
        direction: "上涨=确认"
        source: "生意社/百川"
        last_checked: "2026-08-28"
      - metric: "M8/M9 认证进度"
        current_value: "M8 认证中"
        direction: "认证通过=加强"
        source: "研报/公告"
        last_checked: "2026-08-20"
      - metric: "高端产能利用率"
        current_value: "满产满销"
        direction: "满产=确认"
        source: "研报/产业新闻"
        last_checked: "2026-08-15"
    
    segments:
      - name: "上游材料"
        items: ["铜箔", "玻璃布", "树脂", "硅微粉"]
        value_share: "~30%"
        bottleneck: "M6+ 高端缺货"
        trend: "涨价"
      - name: "中游 CCL"
        items: ["覆铜板"]
        value_share: "~25%"
        bottleneck: "客户订单排至2027"
        trend: "满产"
      - name: "下游 PCB"
        items: ["HDI", "高多层板", "Midplane"]
        value_share: "~45%"
        bottleneck: "认证周期"
        trend: "价值量跃迁"
    
    stocks:
      - code: "002409.SZ"
        name: "雅克科技"
        role: "上游材料（球硅/前驱体）"
        chain_segment: "上游材料"
      - code: "600183.SH"
        name: "生益科技"
        role: "中游 CCL 龙头"
        chain_segment: "中游 CCL"
      - code: "002463.SZ"
        name: "沪电股份"
        role: "下游 PCB（高多层板）"
        chain_segment: "下游 PCB"
    
    history:
      - date: "2026-06-21"
        event: "产业链建立"
        signal: "confirmed"
        note: "UP 研报《AI PCB Rubin 产业链深度报告》首次覆盖"
      - date: "2026-08-28"
        event: "FR8 价格 260-270 元/张"
        signal: "confirmed"
        note: "国信证券 6/28 研报确认涨价持续"
```

### 2.3 每日增量分析流程

**Step 1：扫描新信息**

从已有数据源读取当日新增：
- 研报：`infra/data/research/reports/<date>.json`（已有 cron）
- 公告：`infra/data/research/notices/<date>.json`（已有 cron）
- 板块行情：东财板块 API 或 `infra/data/sector_intraday/`

**Step 2：匹配产业链**

对每条新信息，用规则匹配到已注册的产业链：
- 关键词匹配（标题/内容含产业链关键词）
- 标的匹配（涉及的股票代码在产业链标的列表中）
- 环节匹配（提到的环节在产业链 segments 中）

**Step 3：LLM 增量分析（核心步骤）**

对每条匹配到的信息，调 LLM 分析：

```
你是产业链跟踪分析师。以下是产业链"{chain_name}"的当前状态和新信息。

【产业链当前状态】
{chain_thesis}
当前信号：{current_signal}（{signal_updated}）
跟踪指标：{tracking_metrics}

【新信息】
{new_info}

请判断：
1. 这条信息与产业链的相关性（直接相关/间接相关/无关）
2. 如果相关，对产业链逻辑的影响（确认/加强/削弱/证伪）
3. 具体影响了哪个跟踪指标或环节
4. 对产业链中标的的潜在股价影响：
   - 影响方向（利好/利空/中性）
   - 影响幅度（大/中/小）
   - 影响时间窗口（短期1-3天/中期1-4周/长期1-6月）
5. 一句话结论（≤30字）

输出 JSON：
{
  "relevance": "direct|indirect|none",
  "signal": "confirmed|strengthening|weakening|falsified",
  "affected_metric": "...",
  "affected_segment": "...",
  "stock_impacts": [
    {"code": "...", "name": "...", "direction": "利好|利空", "magnitude": "大|中|小", "window": "短期|中期|长期", "reason": "..."}
  ],
  "conclusion": "..."
}
```

**Step 4：状态更新**

- 如果 signal=confirmed/strengthening → 更新 tracking_metrics 的 current_value
- 如果 signal=weakening → 标记"观察"，下次连续削弱则降级
- 如果 signal=falsified → 标记"证伪"，建议退出观察
- 更新 chain_registry.yaml 的 history

**Step 5：输出**

- `infra/data/chain_tracking/daily_report_<date>.md`（人类可读日报）
- `infra/data/chain_tracking/signals_<date>.json`（结构化信号）
- 更新 `chain_registry.yaml`
- 更新 `dynamic_watchlist.yaml`（受影响标的的优先级调整）

---

## 三、产业链注册表初始化

### 3.1 从 UP 方向池迁移

**UP 26 个主题 → 16 条独立产业链**（AI 算力按上游材料/驱动因素拆分为 6 条子链单独跟踪）

| # | 产业链 ID | 名称 | UP方向数 | 状态 | 环节 | 标的 | 跟踪指标 |
|---|----------|------|---------|------|------|------|---------|
| 1 | ai-pcb-ccl | AI PCB/CCL | 3 | active | 3 | 6 | 5 |
| 2 | ai-optical | AI光互联 | 3 | active | 4 | 7 | 4 |
| 3 | ai-storage | 存储芯片 | 2 | active | 4 | 4 | 4 |
| 4 | ai-server | AI服务器/超节点 | 2 | active | 5 | 4 | 4 |
| 5 | ai-chip-design | AI芯片设计 | 1 | watch | 3 | 3 | 2 |
| 6 | ai-power | AI电力/AIDC | 2 | watch | 3 | 2 | 3 |
| 7 | mlcc-passive | 被动元件 | 2 | active | 3 | 3 | 3 |
| 8 | electronic-gas | 电子特气 | 1 | active | 3 | 3 | 2 |
| 9 | copper-aluminum | 铜铝 | 1 | watch | 3 | 1 | 2 |
| 10 | rare-metals | 稀有金属 | 1 | watch | 3 | 1 | 1 |
| 11 | coal-coke | 煤炭/焦炭 | 1 | active | 3 | 2 | 2 |
| 12 | photovoltaic | 光伏 | 1 | watch | 3 | 3 | 1 |
| 13 | semiconductor-equipment | 半导体设备/EUV | 1 | watch | 3 | 3 | 1 |
| 14 | aerospace | 商业航天 | 1 | watch | 3 | 0 | 1 |
| 15 | pharma | 医药/创新药 | 1 | watch | 3 | 0 | 1 |
| 16 | robotics | 机器人 | 1 | watch | 3 | 0 | 1 |

**聚类逻辑**：判断标准是"上游不同+下游不同+驱动因素不同"。
AI 算力下面 UP 有 11 个方向，但下游都是"AI服务器/数据中心"——不独立。
按上游材料拆分后：PCB/CCL（铜箔）、光互联（光芯片）、存储（DRAM）、
服务器/超节点（半导体设备）、芯片设计（EDA）、电力/AIDC（电力设备）——
每条子链的上游完全不同，驱动因素也不同，因此独立跟踪。

**迁移脚本**：`scripts/migrate_watchlist_to_chains.py`
**注册表文件**：`config/stock_monitor/chain_registry.yaml`

### 3.2 新增产业链

UP 断供后，新产业链通过两个途径发现：
1. **LLM 主动发现**：每日研报扫描时，LLM 发现"这个研报覆盖了一个新产业链"→ 提议新增
2. **人工添加**：用户指定一个新方向 → 管线建立初始 chain_registry 条目

---

## 四、与现有系统的对接

### 4.1 factor_rank.py

factor_rank 读 `dynamic_watchlist.yaml` 作为标的池。
dynamic_watchlist 由产业链跟踪管线每日更新——受影响信号为"strengthening"的标的提升优先级。

### 4.2 双引擎脚本

`qing_position_dual_analysis.py` 持仓不变。
但可以在报告中增加"产业链信号"段——如果持仓标的所属产业链有信号变化，在报告中标注。

### 4.3 复盘 skill

`qing-stock-daily-review` 复盘报告中增加"产业链跟踪"段，
数据源为 `infra/data/chain_tracking/daily_report_<date>.md`。

---

## 五、实施计划

### Phase 1：产业链注册表 + 迁移（1-2 天）

**目标**：把 UP 方向池 26 个主题迁移为 chain_registry.yaml

**交付物**：
- `config/stock_monitor/chain_registry.yaml`（26 条产业链线）
- `scripts/migrate_watchlist_to_chains.py`（迁移脚本）

**验收**：
- 26 条产业链线结构完整
- 每条含 tracking_metrics + stocks + segments
- YAML 校验通过

### Phase 2：每日增量扫描 + LLM 分析（3-5 天）

**目标**：每天自动扫描新信息，匹配产业链，LLM 分析影响

**交付物**：
- `scripts/chain_tracker.py`（主入口）
- Step 1-4 全部实现
- 输出日报 Markdown + 信号 JSON

**验收**：
- 给定一天数据，能正确匹配到已有产业链
- LLM 输出的 signal（confirmed/strengthening/weakening/falsified）与人工判断一致率 > 70%
- 每日产出 1-3 条增量影响报告

### Phase 3：股价影响评估 + 对接（1 周）

**目标**：LLM 评估增量信息对标的的股价影响，对接 factor_rank

**交付物**：
- Step 5 股价影响评估
- factor_rank.py --source dynamic 对接
- dynamic_watchlist.yaml 每日更新
- 复盘 skill 集成

**验收**：
- 股价影响评估与实际走势对比（事后验证）
- factor_rank 能读 dynamic_watchlist

---

## 六、成本估算

| 项目 | 频率 | 单次成本 | 日成本 |
|------|------|----------|--------|
| 数据扫描 | 每日 1 次 | 已有 cron，免费 | ¥0 |
| 产业链匹配 | 每日 1 次 | 规则匹配，免费 | ¥0 |
| LLM 增量分析 | 每日 5-15 条 | ~2000 token/条 | ~¥0.3-0.5（GLM-4-flash） |
| **日总成本** | | | **~¥0.5/天** |

---

## 七、关键设计决策

1. **以产业链为单位，不以研报为单位**——研报是信息的载体，产业链是跟踪的对象。同一产业链可能有多篇研报持续覆盖，管线跟踪的是产业链的状态变化，不是研报的发布。
2. **增量分析，不是全量重读**——每天只处理新信息，判断对已有产业链逻辑的影响。不需要每天重新读 65 页 PDF。
3. **去重标记**——同一信息（如同一研报的转载）只处理一次，重复标记跳过。
4. **信号分级**——confirmed/strengthening/weakening/falsified 四级，不是二元的"对/错"。
5. **不替代缠论**——产业链分析解决"选什么方向"，缠论解决"什么时候买卖"。两者是串联关系。

---

## 八、风险与限制

1. **新产业链发现滞后**：管线只能跟踪已注册的产业链，新出现的产业链需要人工添加或 LLM 提议
   → 缓解：每日研报扫描时，LLM 对未匹配的信息做"新产业链提议"
2. **LLM 判断准确率**：增量信息的影响判断可能不如 UP 准确
   → 缓解：UP 续费期内做对比校准，持续调 prompt
3. **信息噪音**：每日公告 6342 条，大部分是噪音
   → 缓解：先规则过滤（关键词/类型），再 LLM 判断
4. **股价影响评估偏差**：LLM 对"影响幅度"的判断是定性的，不是定量的
   → 缓解：事后验证（实际走势 vs LLM 预判），持续校准

---

## 九、不做的事

- ❌ 不做实时盘中跟踪（每日一次即可，产业链变化不是分钟级的）
- ❌ 不做社交媒体舆情（与产业链逻辑无关）
- ❌ 不替代缠论买卖点判断
- ❌ 不做全市场扫描（只跟踪已注册的产业链 + LLM 提议的新产业链）
- ❌ 不挂 cron 自动跑（LLM 密集任务，每日 19:00 手动/事件驱动触发）
