# Claim 编写规范：面向 Neo4j / Qdrant / Agent 的系统化约定

> 基于 2026-06-06「磨底期非科技方向」检索调试的实战经验，结合三个消费路径的代码审查编写。
>
> **前置阅读**：`claim-schema.md`（字段定义）、`src/qing_investment/agent/AGENTS.md` §10（架构决策）

---

## 一、三个消费者的职责边界

| 消费者 | 读哪些字段 | 做什么 | 不做什么 |
|--------|-----------|--------|---------|
| **Neo4j** (`migrate_claims_to_neo4j.py`) | `id`, `statement`, `subject`, `claim_type`, `links`, `supersedes`, `contradicts` | 建节点+关系边，正则提取股票代码 | 不做语义搜索 |
| **Qdrant** (`index_claims_to_qdrant.py`) | **仅** `subject` + `statement` | 拼接为 `"{subject} \| {statement}"` → embedding → 语义搜索 | 不读 `interpretation`/`evidence_quote`/`links` |
| **Agent** (`/chat`, `/analyze/trigger`) | Qdrant 召回 → payload 中的 `claim_id`, `statement`, `subject`, `source_date`, `confidence`, `status`, `claim_type` | 注入 prompt 作为「博主历史观点（仅供参考）」 | 不在运行时遍历 Neo4j 图找标的 |

**核心推论**：`subject` 和 `statement` 是唯一影响 Qdrant 搜索召回率的字段。如果这两个字段写不好，Agent 搜不到。

---

## 二、字段职责矩阵与编写规范

### 2.1 `subject` — Qdrant 搜索锚点 + Neo4j 实体名

**消费者**：Qdrant（嵌入）、Neo4j（实体节点名称、正则提取代码）

**规范**：

```
✅ 好的 subject：
   市场阶段判断——磨底期
   磨底期非科技方向——燃气轮机（类比上一轮锂电池）
   科技股阶段性别规避

❌ 差的 subject：
   观点一                         ← 无信息量
   关于最近市场的一些看法           ← 太长、无关键词
   半导体                          ← 太泛，无法区分市场判断 vs 产业分析
```

**规则**：

1. **包含用户会搜索的关键词**。如果方向是「燃气轮机」，subject 里必须有「燃气轮机」四个字。用户搜「燃气轮机核心标的」→ Qdrant 对 subject 做语义匹配 → 命中。
2. **多层信息用「——」分隔**。格式：`大类——子类——具体主题`。例：`市场阶段判断——磨底期`、`板块判断——科技规避——半导体估值过高`
3. **多方向 raw 的命名策略见 §4**。
4. **不要超过 50 字**。过长的 subject 稀释关键词语义密度。

### 2.2 `statement` — 核心召回载体

**消费者**：Qdrant（嵌入）、Neo4j（正则提取代码）、Agent（注入 prompt）

**这是最重要的字段**。`interpretation`、`evidence_quote` 都不参与 Qdrant 索引。

**规则**：

1. **必须自包含**。读者只读 `statement` 就应该知道 UP 的观点是什么、涉及哪些标的。不允许「详见 claim-b」「详见下文」等引用——Agent 不一定同时召回引用的另一条 claim。
2. **标的必须写代码**。写「杰瑞股份(002353)」而非「杰瑞股份」。原因：
   - Neo4j 用正则 `\b(\d{6})\b` 从 `subject + statement` 提取代码建 `Claim→Stock` 边
   - Agent prompt 中标的名称+代码一起出现，LLM 可以交叉验证
3. **方向推荐类 claim 必须在 statement 中列出标的**。这是架构决策（见 `AGENTS.md` §10）：Agent 不通过 Neo4j 图遍历找标的，标的必须随 claim 文本传递。
4. **控制长度在 100-300 字**。太短缺乏信息量，太长稀释语义密度。
5. **优先使用 UP 原话中的术语**。UP 说「六氟磷酸锂」就不要写「锂电池电解液」，保持与 Qdrant 搜索词的术语一致性。

```
✅ 好的 statement（方向推荐类）：
   燃气轮机是经历过回调、有业绩支撑、确定性高的方向，UP类比上一轮牛市的锂电池。
   核心标的：杰瑞股份(002353,燃机交付Q1超1亿美元)、中国动力(600482,703燃机出海)、
   万泽股份(000534,涡轮叶片)、银轮股份(002126,卡特燃气发电机后处理)、
   联德股份(605060,燃机板块增速50%+)

❌ 差的 statement：
   燃气轮机方向值得关注。                                        ← 无标的、无论据
   详见 claim-20260604-004-f 的 related_stocks。                  ← 不自包含、Agent 搜不到
   燃气轮机是经历过回调的方向，核心标的见 related_stocks 字段。     ← 依赖 Neo4j 边，Agent 运行时不会遍历
```

### 2.3 `claim_type` — Neo4j 实体标签 + Agent 隐式过滤

**消费者**：Neo4j（决定节点标签：Stock/Sector/Macro/Methodology/Theme）、Agent（`market_analyst` 按方法论关键词过滤）

**枚举值**（以 `claim_schema.py` 为准）：

| claim_type | Neo4j 实体标签 | market_analyst 行为 | 典型用途 |
|-----------|---------------|-------------------|---------|
| `market-cycle` | Macro | ✅ 不屏蔽（含「周期」「磨底」等关键词） | 市场阶段判断 |
| `macro` | Macro | ✅ 不屏蔽 | 宏观/流动性判断 |
| `sector-theme` | Sector | ⚠️ 可能被部分屏蔽（不含方法论关键词） | 板块/方向判断 |
| `methodology` | Methodology | ✅ 不屏蔽 | 选股/操作方法 |
| `operation` | Methodology | ✅ 不屏蔽（含「纪律」「风控」等关键词） | 交易纪律 |
| `technical-knowledge` | Theme (默认) | ✅ 不屏蔽（关键词命中率高） | 技术分析教学 |
| `risk` | Theme (默认) | ⚠️ 可能被部分屏蔽 | 风险提示 |
| `stock-view` | Stock | ❌ 被 `_filter_methodology_only()` 屏蔽 | 单一个股观点 |
| `general` | Theme (默认) | ⚠️ 可能被屏蔽 | 一般性观点 |

**规则**：

1. **方向/板块推荐用 `sector-theme`**，不要用 `stock-view`。
2. **市场阶段判断用 `market-cycle`**。
3. **选股方法论/操作纪律用 `methodology` 或 `operation`**。
4. **不要随意用 `general`**——`general` 在 Agent 侧可能被方法论过滤器屏蔽。

> **注意**：Agent 的 `_filter_methodology_only()` 不是按 `claim_type` 字段过滤的，而是按 statement 文本中是否含方法论关键词（框架/周期/规则/冰点/回暖/主线/仓位/纪律/风控/选股法 等）。但 `claim_type` 影响 Neo4j 图结构，所以两个维度都要对。

### 2.4 `interpretation` — 仅供人类阅读

**消费者**：无自动化消费。Agent 不读、Qdrant 不索引、Neo4j 仅存为属性。

**规则**：
1. 可以写长，无字数限制。
2. 用于记录 LLM 对 UP 观点的解读、逻辑链条、与前序观点的关联。
3. 不要依赖 `interpretation` 传递关键信息——Agent 看不到。

### 2.5 `evidence_quote` — 证据追溯

**消费者**：无自动化消费。Neo4j 存为属性，Agent prompt 中不展示。

**规则**：
1. 必须包含原文引用（`> ` 块引用格式）。
2. 用于人工验证和 review 时追溯。

### 2.6 `related_stocks` — Neo4j 辅助边

**消费者**：Neo4j（如果 statement 中已有代码，正则也能提取，但 YAML 显式声明便于调试）。

**规则**：
1. 代码必须与 statement 中的标的**完全一致**。
2. **不能**只写 `related_stocks` 而不在 statement 中提及——Agent 看不到这个字段。
3. 格式：`["杰瑞股份(002353)", "中国动力(600482)"]`。

### 2.7 `supersedes` / `contradicts` — Neo4j 关系边

**消费者**：Neo4j（Claim→Claim 边）、Agent（prompt 中展示演化/矛盾标记）。

**规则**：
1. `supersedes`：引用被本条取代的旧 claim ID。
2. `contradicts`：引用与本条矛盾的 claim ID。
3. 需要补充 `supersedes_reason` / `contradicts_reason`（Neo4j 边的属性）。

### 2.8 `links` — Neo4j Wiki/Methodology 边

**消费者**：Neo4j（Claim→WikiPage、Claim→MethodologyPage 边）。

**规则**：
1. `wiki_pages`：关联的 wiki 页面路径（如 `knowledge/wiki/市场分析/燃气轮机.md`）
2. `methodology_pages`：关联的 methodology 页面路径
3. `cases`：关联的案例

---

## 三、多方向 raw 的 claim 结构模式

### 问题

一篇 raw（如 UP 充电视频）可能涵盖 6 个非科技方向 + 多个操作纪律。用户搜索「磨底期有哪些非科技方向」时，Qdrant 需要在多条 claim 中找到完整答案。

### 解决方案：「总入口 + 方向细分」两层结构

```
claim-a (market-cycle)：市场阶段判断——磨底期
  statement 包含：
  - 指数判断（4033/4130 生命线）
  - 全部6个方向的名称 + 代表性标的（每个方向 2-3 只）
  - 明确说「非科技方向」「规避科技」
  → 用户搜「磨底期非科技方向」→ Qdrant 命中 claim-a → 一条 claim 拿到全景

claim-e (sector-theme)：磨底期非科技方向——储能/六氟磷酸锂
  statement 包含：
  - 储能逻辑（六氟 > 锂矿）
  - 全部相关标的（10+ 只）
  → 用户搜「储能标的」→ Qdrant 命中 claim-e → 拿到细分详情

claim-f (sector-theme)：磨底期非科技方向——燃气轮机
claim-g (sector-theme)：磨底期非科技方向——消费
...
```

### 规则

1. **claim-a 必须是「总入口」**。作为 `market-cycle` 类型，在 statement 末尾用一句话汇总全部方向：「UP 明确推荐磨底期布局的非科技方向：燃气轮机（A/B/C）、储能（D/E/F）、消费（G/H）...」
2. **总入口的 subject 必须包含全景关键词**。如「市场阶段判断——磨底期」，不要只写「指数判断」。
3. **方向细分 claim 的 subject 用统一前缀**。如 `磨底期非科技方向——XXX`，便于 Qdrant 语义聚类。
4. **每条方向细分 claim 的 statement 自包含**。不依赖 claim-a 或 other claims。

### 反例

```
❌ claim-a statement：「指数磨底，具体方向见后续 claims」
   → Qdrant 搜「磨底期方向」命中 claim-a，但 statement 里没有方向信息
   → Agent 还要再搜一次才能拿到具体方向

❌ 每条方向 claim 写得很详细，但没有总入口 claim
   → 用户搜「磨底期非科技方向」时，Qdrant 需要在多条 claim 中语义匹配
   → 可能漏掉某些方向
```

---

## 四、常见反模式

| 反模式 | 后果 | 正确做法 |
|--------|------|---------|
| statement 不含标的代码，只写「核心标的见 related_stocks」 | Agent 搜到 claim 但不知道买什么 | 标的代码写入 statement |
| subject 写「观点一」「关于XX的看法」 | Qdrant 搜索无法命中 | 写具体关键词：「科技规避——半导体估值过高」 |
| interpretation 里写了关键逻辑但 statement 很简略 | Agent 看不到 interpretation | 关键逻辑写入 statement |
| claim_type 选 `stock-view` 用于方向推荐 | market_analyst 屏蔽该 claim | 方向推荐用 `sector-theme` |
| 多条 claim 讨论同一方向，但 subject 命名不统一 | Qdrant 语义聚类发散 | 用统一前缀：「磨底期非科技方向——XXX」 |
| statement 写「与前期观点一致」但不引用具体 claim | Agent 不知道前期观点是什么 | 引用具体 claim ID + 一句话概括 |
| related_stocks 里的标的不在 statement 中出现 | Neo4j 有边但 Agent 看不到 | 确保代码至少在 statement 中出现一次 |
| 总入口 claim 的 statement 不含方向汇总 | 全景查询需要召回多条 claim | claim-a 做一站式汇总 |

---

## 五、验证清单

写完 claim 文件后，逐条检查：

- [ ] 每条 claim 的 `statement` 是否自包含？（不依赖其他 claim 的上下文）
- [ ] 方向推荐类 claim 的 `statement` 是否包含标的代码（6 位数字格式）？
- [ ] `subject` 是否包含用户可能搜索的关键词？
- [ ] `claim_type` 是否正确？（方向推荐 → `sector-theme`，不是 `stock-view`）
- [ ] 多方向 raw 是否有「总入口」claim？
- [ ] `related_stocks` 中的代码是否在 `statement` 中出现过？
- [ ] `supersedes`/`contradicts` 是否附带了 reason？
- [ ] `links.wiki_pages` 是否指向存在的 wiki 页面？

---

## 六、版本历史

| 日期 | 变更 | 触发 |
|------|------|------|
| 2026-06-06 | 初稿 | 「磨底期非科技方向」检索调试 → 发现 statement 缺乏标的代码 + 缺少总入口 claim → 代码审查 Neo4j/Qdrant/Agent 三个消费路径后系统化 |
