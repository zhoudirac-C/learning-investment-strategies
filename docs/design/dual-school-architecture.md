# 双专家（多学派）知识体系架构方案

> 版本：v1.1（2026-10-15，经同类项目调研优化 + 鳄鱼派 50 章全量入册修正）
> 状态：**待拍板，暂不实施**
> 目标：在现有「青枫浦上Q 单 UP」知识体系上，引入鳄鱼派（像鳄鱼一样思考）为第二专家，
> 并为未来任意新 UP/学派预留扩展位，保证各学派知识**可共存、可隔离、可对照、不互相污染**，
> 最终服务于 qing-agent 的多视角分析输出。

---

## 1. 设计目标与原则

| # | 目标 | 衡量标准 |
|---|---|---|
| G1 | **来源可追溯**：任何一条 claim/pattern/结论都能回答"这是谁的观点" | 所有知识载体强制 up_id/school 字段，linter 校验 |
| G2 | **更新隔离**：各学派的增量更新（日报→claim→pattern）互不覆盖、互不污染 | 每学派独立管线实例+独立状态文件+写入前 up_id 校验 |
| G3 | **对照可见**：两派在同一问题上的一致/互补/矛盾可被显式检索 | 一致性对照表 + 冲突登记表，agent 检索时按 school 分组输出 |
| G4 | **最小改造**：复用现有 claim 管线、Qdrant、Neo4j、pattern_router，不另起炉灶 | 不新增数据库，只加维度字段与过滤参数 |
| G5 | **数据裁决**：矛盾项最终由回测/命中率裁决，不由 LLM 和稀泥 | 冲突项关联 qing-strategy-backtest 产物字段 |

**核心原则：单一物理库 + 逻辑分域（school 维度），而不是双份基础设施。**

---

## 2. 学派注册表（核心新概念）

新建 `config/schools.yaml` ——全系统唯一的学派定义源：

```yaml
version: 1
schools:
  - school_id: qing            # 青枫浦上Q（默认学派，兼容存量）
    display_name: 青枫浦上Q
    up_ids: ["1420210197"]     # B站
    sources: ["bilibili_dynamic", "raw_finance"]
    style: 结构化技术分析（缠论+七轨布林+双引擎）
    is_default: true
  - school_id: gator           # 鳄鱼派（新增）
    display_name: 像鳄鱼一样思考
    up_ids: ["wechat-ecyu-0001", "470672214"]   # 公众号 + B站
    sources: ["wechat_mp", "bilibili_dynamic", "third_party/gator-method"]
    style: 资金生态位 + 预案-信号-执行规则体系
    is_default: false
    provenance_note: "第三方提炼库 gator-method 为参考源，非UP原文，提claim须标注"
  - school_id: watchlist       # 观察池 UP（莫大/Mark/卢本圆…默认归此类）
    display_name: 观察池
    up_ids: ["525121722", "424405794", "550494308"]
    style: 杂
```

**规则**：up_id → school 的映射只在此文件定义一次；所有下游（claim 校验、检索过滤、agent 注入）
都读它。新增 UP = 在注册表加一行 +（可选）决定归入哪个 school，不碰任何代码。

---

## 3. 数据层改造（claim / pattern / 检索 / 规则）

### 3.1 claim 侧（改动最小）

- `claim_schema.py`：
  - `VIRTUAL_UP_IDS` 扩展注册 `wechat-ecyu-0001`（真实虚拟 UP，类比 chanlun-original）
  - 校验逻辑不变（up_id 必填）→ **天然隔离**：每条 claim 已带 up_id，检索时按 school 过滤即可
- 新增 linter 规则：claim 的 `source_path` 前缀必须与其 up_id 所属 school 的 `sources` 匹配
  （防止 gator 的文章被记到 qing 头上）

### 3.2 reasoning-patterns 侧

- 每个顶层 pattern 增加 `school: qing|gator|shared` 字段：
  - `shared`：两派一致的通用推理（决策六步、不浮盈加仓、触发/失效条件格式）→ 现有 18 框架默认 `qing`，人工复审后逐个改判
  - **gator 新 pattern = 50 章全量入册**（修正：原方案精选 6-8 个过保守，鳄鱼派 50 章是 4 年精华，每章都是独立成型方法论单元，全量保留）：
    - **程序化拆解**：脚本扫描 `sources/third_party/gator-method/03-规则体系/*.md`，按 `##` 章号 + `###` 小节号解析，提取 来源/规则/阈值/执行 结构化字段
    - 每章生成一个 pattern（id = `gator-<章号>-<slug>`），自动填 school=gator
    - 带 `[可计算]` 标记的 21 章**同时**生成 `gator_rules.py` 代码规则草案（阈值从文中提取）——代码用于盘中实时跑，pattern 保留作语义检索兜底
    - 人工 review 只聚焦**与 Q 框架重叠/矛盾的章节**（如止跌信号 vs 缠论背驰信号），进 `school-conflicts.yaml`
- pattern_router（embedding 语义路由）改为 **两段式**：
  1. 候选池 = shared + 目标学派 patterns（按查询意图或用户指定学派决定）
  2. 路由逻辑不变，只是候选集带 school 过滤

### 3.3 向量/图检索（Qdrant + Neo4j）

- **不建双 collection**。改为 payload 维度过滤 + 性能优化：
  - Qdrant：point payload 加 `school` 字段 + **`is_tenant=true`**（同一学派向量连续存储，顺序读 vs 随机扫）
  - Neo4j：Claim 节点加 `school` 属性；Cypher 查询按需过滤
- `context_builder.py` 新增 `school_filter: list[str] | None` 参数：
  - `None`（默认）= 全部（现状不变，兼容）
  - `["qing"]` / `["gator"]` = 单专家模式
  - claims 排序分组输出：`{school: qing: [...], gator: [...]}`

### 3.4 鳄鱼派规则代码化（新增，借鉴 LLM-TRADE 模式）

鳄鱼派的规则（止跌5信号、剪刀差、情绪冰点阈值）都是带数字阈值的确定性规则——
- 新增 `src/qing_investment/monitor/rules/gator_rules.py`，**直接代码实现**，不占 LLM token
- 每日盘中直接跑，输出「满足 3/5 个信号，激进/保守可出手」
- 对应 qing-strategy-backtest 直接回测每条规则的命中率（比 claim 级盲判更科学）

代码化规则清单（初版）：
```python
# 止跌5信号（逐条判定 + 计数）
- 指数共振：上证vs创业板差距收敛 + 沪深300vs中证2000差距收敛
- 火车头板块：领涨板块有带动作用（板块涨幅>0.5% + 上涨家数>60%）
- 气氛组证券：券商有无涨停板
- 短线增量资金：量比>1.2 或 北向净流入>0
- 股指基差缩小：基差变化方向（下跌途中缩小不算）
# 情绪冰点阈值
- 微盘股跌≥3% AND 跌停家数>30 AND 上证跌>2%
# 剪刀差分级
- 沪深300 vs 中证2000涨跌幅差 >0.5%（分歧）/ >1%（分歧较重）/ >2%（分歧严重）
```

---

## 4. 管线层：更新流程隔离

每学派一条独立管线（脚本复用，配置分域）：

```
qing 学派（现状，不动）:
  B站动态 fetch → sources/original/bilibili/ → claim 提取 → pattern 复盘

gator 学派（新增）:
  公众号 we-mp-rss DB → scripts/fetch_wechat_article.py → sources/original/wechat/
  B站动态 fetch → sources/original/bilibili/（up_id 470672214）
  → claim 提取（up_id=wechat-ecyu-0001，同一套 gate）
  → 月度 pattern 复盘（reasoning-patterns-gator.yaml 增量）
  → 代码规则更新（gator_rules.py 阈值调整）

观察池（现状，不动）: 通知为主，不提 claim
```

**防污染机制（关键）**：
1. **提取时**：claim 文件名前缀 + up_id 字段强制对齐（gate 校验，加 school 映射断言）
2. **聚合时**：`framework-maintenance` 复盘脚本按 school 分组跑，qing 的方法论复盘**只读** qing+shared 的 claims
3. **回测时**：qing-claim-backtest / shadow-dual-track 的盲判命中率**分学派统计**（鳄鱼派盲判独立计分）
4. **代码时**：gator_rules.py 独立文件，与缠论引擎（双引擎）不交叉，分别维护

---

## 5. Agent 层：qing-agent 多专家输出

### 5.1 检索注入

`build_market_context` / `build_stock_context` 输出增加 school 分组；prompts 层新增
`dual_school_output.txt` 约定输出格式。

### 5.2 分析输出契约（借鉴 Claude-Cortex 多视角合成模式，升级为 6 段式）

```
一、共识区（两派一致）      ← shared patterns + 双方观点重合
二、Q 学派视角            ← 缠论结构 + Q claims（含价格锚点）
三、鳄鱼派视角            ← 规则清单核对（止跌5信号逐条打分等）
四、矛盾与裁决            ← 引用 school-conflicts.yaml 辩论卡：
                             冲突描述 / Q依据 / 鳄鱼依据 / 交叉反驳要点 / 回测结果(如有)
五、操作建议              ← 合成层：方向层+节奏层+触发/失效条件（不变）
六、涌现发现（可选）      ← 两派交叉后的新洞察（如"护盘+缠论中枢下沿同时成立 → 确认底"）
```

- 矛盾未裁决时**双列呈现**，标注「待回测裁决」，不允许 agent 自行选边
- 用户提问可指定学派（"按缠论看" / "按鳄鱼派看"），对应 school_filter

### 5.3 冲突登记表（升级为辩论卡格式，借鉴 TradingAgents 模式）

新建 `framework/school-conflicts.yaml`：

```yaml
conflicts:
  - conflict_id: CF-001
    question: "上涨由护盘/国家队驱动时，是否算止跌信号"
    school_views:
      qing:   {view: "...", evidence: [claim-xxx], hit_rate: null}
      gator:  {view: "上涨由护盘驱动 ≠ 止跌", evidence: [gator-rule-ch12], hit_rate: null}
    round1_cross_exam:          # 交叉反驳（LLM 辅助生成，但标注各自依据）
      qing_critique: "..."
      gator_critique: "..."
    status: pending_backtest   # pending_backtest / backtesting / resolved / agreed
    resolution: null           # 回测结论 + 裁决日期 + 置信度
```

**裁决规则**：冲突项的裁决**必须走回测**（qing-strategy-backtest），未回测的永不给单一答案。
初版预计 5-8 条（护盘定性、左侧买入幅度、情绪冰点阈值 vs 背驰信号、剪刀差 vs 指数共振优先级等）。

---

## 6. 未来扩展：其他 UP

- 新观察 UP：`bilibili_ups.yaml` 加条目（school_id 默认 watchlist）→ 只通知不进知识库（现状）
- 升格为专家：schools.yaml 加 school + claim 管线指派 up_id → 全链路自动获得隔离/分组能力
- **升级路径是配置驱动，不改代码**——这是本架构的核心收益

---

## 7. 实施 Phase（拍板后执行）

| Phase | 内容 | 产出 | 预估 |
|---|---|---|---|
| P1 | schools.yaml + claim_schema 注册 + linter 规则 | 学派注册生效 | 0.5天 |
| P2a | Qdrant/Neo4j 索引加 school 字段（is_tenant 优化）+ context_builder 过滤参数 + 重建索引 | 检索可分域 | 0.5天 |
| P2b | 鳄鱼派确定性规则代码化（gator_rules.py：止跌5信号/剪刀差/情绪冰点） | 盘中规则实时跑 | 0.5天 |
| P3 | gator 50 章全量入册：拆解脚本 → 50 pattern 草案生成 → 21 个可计算规则同步入 gator_rules.py → 人工 review 冲突章节 + 现有18框架 school 标注复审 | 双学派 pattern 库（~68 个总 pattern） | 2-3天 |
| P4 | school-conflicts.yaml 辩论卡初版 + agent 双学派输出契约 + prompts | agent 多专家输出 | 1天 |
| P5 | 公众号 cron（23:00 fetch→claim）+ 盲判分学派计分 | 增量管线运转 | 0.5天 |

**总计约 4.5-5.5 天**（P3 从精选改为全量程序化拆解，工作量扩大但一次到位；P2a/P2b 仍并行）。

---

## 8. 明确不做（本次）

- ❌ 历史文档迁移（gator-method 700 篇不进 claim 库，只作参考）
- ❌ 双 Qdrant collection / 双 Agent 实例
- ❌ 鳄鱼派风格化输出（style_writer 仍只有 Q 口吻；gator 只提供观点不提供文风）
- ❌ LLM 实时多 agent 辩论（辩论卡是持久化登记+回测裁决，不是运行时辩论）

---

## 9. 风险

| 风险 | 缓解 |
|---|---|
| gator-method 为第三方提炼，非UP原文，规则可能失真 | provenance 标注 + 后续用我们自己抓的公众号原文校验/替换 |
| 双学派输出 token 翻倍 | 冲突区只列相关条目；共识区共享；非持仓标的只输出单派摘要 |
| 存量 666 个 claim 无 school 字段 | 由 up_id 批量推导回填（一次性脚本），无需人工 |
| 鳄鱼派阈值时效性（部分规则带时间戳） | pattern 内保留 source_date；代码规则阈值独立维护可调 |
| 代码规则与 pattern 冗余 | 代码规则优先实时输出，pattern 作为语义路由兜底（低频） |
| gator-method 上游更新（50 章外的新章节） | GitHub watch 201901060324/gator-method；每月定期重新克隆覆盖 `sources/third_party/gator-method/`，触发 P3 增量拆解（脚本幂等，只新增不覆盖人工 review 结果） |

---

## 10. 借鉴来源（同类项目调研）

| 项目/模式 | 借鉴点 |
|---|---|
| **TradingAgents**（多智能体辩论框架） | 冲突项结构化辩论卡（round1 → 交叉反驳 → 裁决），但裁决用回测而非 LLM |
| **Claude-Cortex 多视角分析 skill** | 6 段式输出契约（共识区/创造性张力/整合方案/涌现发现） |
| **LLM-TRADE**（A股多Agent工作台） | 规则先行、LLM 轻量精筛——鳄鱼派阈值规则代码化 |
| **Qdrant 多租户隔离文档** | payload 分区 + `is_tenant=true` 优化（同一学派向量连续存储） |
