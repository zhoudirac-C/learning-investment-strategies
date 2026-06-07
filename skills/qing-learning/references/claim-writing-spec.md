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
| **Agent** (`/chat`, `/analyze/trigger`) | Qdrant 召回 → payload 中的 `claim_id`, `statement`, `subject`, `source_date`, `confidence`, `status`, `claim_type`, `intensity` | 注入 prompt，按 `claim_type` 分流 + 按 `source_date` 时效分级标注 + 按 `intensity` 分级标注（🔴高/🟡中/⚪低） | 不在运行时遍历 Neo4j 图找标的 |

### Agent 消费规则（时效分级引用）

| freshness_label | 天数 | Prompt 区块 | 引用规则 |
|----------------|------|-------------|---------|
| 方法论 | 不限 | 【博主选股方法论/操作框架】🔧 | 可作为方法论指导引用，不受时效限制 |
| 最新 | ≤7天 | 【UP最新观点】 | **可作为判断的辅助参考**，每 claim 必须配对至少一条实时数据 |
| 近期 | 8-30天 | 【UP近期观点】 | 参考价值递减，需标注时效 |
| 历史 | 31-90天 | 【UP历史观点】 | 仅供背景参考，不得作为判断依据 |
| — | >90天 / superseded | 不展示 | 已过滤 |

**引用纪律——数据必在 claim 前**：
```
每引用一条 claim，必须在同一句话中给出至少一条实时数据交叉验证
格式：（数据）...→（UP观点）...→（结论）...
如果找不到对应的数据支撑，该 claim 不得引用
```

### Agent 消费规则（intensity 分级）

| intensity | 标签 | 含义 | 个股查询行为 | 大盘查询行为 |
|-----------|------|------|-------------|-------------|
| `high` | 🔴 | UP 专题分析/视频重点推荐/方法论 | 可引用，配实时数据；排序 boost -7天 | 正常进入（方法论不受过滤） |
| `medium` | 🟡 | UP 复盘提及/方向判断/默认 | 正常排序，需标注时效 | 正常进入 |
| `low` | ⚪ | UP 盘中随口/转发/评论回复 | **排序 penalty +365天，排到末尾不进入 prompt** | 保留但不突出 |

**核心推论**：`intensity=low` 的 claims 在个股查询中几乎不会被 LLM 看到。编写 claim 时，UP 随口一提（非分析性内容）应标 `low`。

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
4. **控制长度在 100-300 字，但「总入口」claim-a 必须 ≤200 字**。太短缺乏信息量，太长稀释语义密度。

   > **⚠️ 硬约束**：Agent 的 `/chat` 端点将 statement 截断至 200 字符注入 prompt（`main.py:368: c.get('statement', '')[:200]`）。总入口 claim-a 必须在此限制内完成「方法论摘要 + 方向汇总 + 港股/规避」三件事。压缩技巧：去冗余连接词（「处于」→「」）、用符号替代（「/」替代「和」）、括号省略。示例见 §4.1。

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

### 2.3 `claim_type` — Neo4j 实体标签 + Agent 隐式过滤 + prompt 分流

**消费者**：Neo4j（决定节点标签：Stock/Sector/Macro/Methodology/Theme）、Agent（`market_analyst` 按方法论关键词过滤）、**Agent prompt 构建（`/chat` 端点按 claim_type 分流：methodology/operation → 可引用区块，其他 → 按 freshness_label 分级）**

**枚举值**（以 `claim_schema.py` 为准）：

| claim_type | Neo4j 实体标签 | prompt 分流 | 典型用途 |
|-----------|---------------|-------------|---------|
| `market-cycle` | Macro | 进入时效分级（≤7天→最新/可参考，>7天→递减） | 市场阶段判断 |
| `macro` | Macro | 进入时效分级 | 宏观/流动性判断 |
| `sector-theme` | Sector | 进入时效分级 | 板块/方向判断 |
| `methodology` | Methodology | **方法论区块（不受时效限制）** | 选股/操作方法 |
| `operation` | Methodology | **方法论区块（不受时效限制）** | 交易纪律 |
| `technical-knowledge` | Theme (默认) | 进入时效分级 | 技术分析教学 |
| `risk` | Theme (默认) | 进入时效分级 | 风险提示 |
| `stock-view` | Stock | 不展示（market_analyst 过滤） | 单一个股观点 |
| `general` | Theme (默认) | 进入时效分级 | 一般性观点 |

**规则**：

1. **方向/板块推荐用 `sector-theme`**，不要用 `stock-view`。
2. **市场阶段判断用 `market-cycle`**。
3. **选股方法论/操作纪律用 `methodology` 或 `operation`**——它们会进入「方法论区块」不受时效限制。
4. **不要随意用 `general`**——`general` 在 Agent 侧可能被方法论过滤器屏蔽。

> **注意**：Agent 的 `_filter_methodology_only()` 不是按 `claim_type` 字段过滤的，而是按 statement 文本中是否含方法论关键词（框架/周期/规则/冰点/回暖/主线/仓位/纪律/风控/选股法 等）。但 `claim_type` 影响 Neo4j 图结构和 prompt 分流，所以两个维度都要对。

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
  - 选股方法论（低位+Q1超预期）
  - 港股左侧建仓
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

1. **claim-a 必须是「总入口」**。作为 `market-cycle` 类型，在 statement 中汇总：选股方法论 + 港股 + 全部方向+代表性标的。
2. **总入口 claim-a ≤ 200 字**。Agent 截断 200 字，超出部分 LLM 看不到。示例——压缩前（242字，港股被截断）：

   > ❌ 指数处于磨底期，4033为生命线、4130为满仓线，两点之间持股做T；不看向下跌太多。选股核心：找低位+一季报超预期的标的（打开F10看毛利/净利/收入，「炸裂」就是一季报超预期，中报不会差）。UP推荐磨底期布局的非科技方向：燃气轮机（杰瑞股份/中国动力/万泽股份）、储能六氟磷酸锂（天赐材料/恩捷股份/鹏辉能源）、消费（罗莱生活/亚朵）、创新药（药明康德/百济神州/信达生物）、出海链（大金重工/银轮股份/涛涛车业）、商业航天（窗口期有限）。**港股左侧建仓OK**。规避：科技股、有色金属
   >                                                                                                                     ↑ 200字截断线——港股被切掉

   压缩后（207字，全部可见）：

   > ✅ 指数磨底期，4033生命线/4130满仓线。选股核心：找低位+一季报超预期（「炸裂」=Q1超预期→中报不差），UP推荐的方向内也要优先选低位+Q1好的。港股左侧建仓OK。非科技方向：燃气轮机(杰瑞股份/中国动力/万泽股份)、储能六氟(天赐材料/恩捷股份/鹏辉能源)、消费(罗莱生活/亚朵)、创新药(药明康德/百济神州/信达生物)、出海链(大金重工/银轮股份/涛涛车业)、商业航天(窗口期有限)。规避科技股+有色金属

   压缩技巧：去连接词、括号替代逗号、用符号缩写。

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
- [ ] `claim_type` 是否正确？（方向推荐 → `sector-theme`，选股方法 → `methodology`，操作纪律 → `operation`。Agent 用此字段做 prompt 分流：methodology/operation 进入「可引用」区块，其他进入时效分级）
- [ ] 多方向 raw 是否有「总入口」claim？
- [ ] `related_stocks` 中的代码是否在 `statement` 中出现过？
- [ ] `supersedes`/`contradicts` 是否附带了 reason？
- [ ] `links.wiki_pages` 是否指向存在的 wiki 页面？
- [ ] `intensity` 是否合理？（方法论/视频分析 → `high`，复盘提及 → `medium`，随口/转发 → `low`）
- [ ] YAML 格式是否为**完整 schema 格式**？（必须包含全部 REQUIRED_FIELDS。简化格式 `topic`/`text` 虽被 backfill 脚本兼容，但 `validate_claim_dict` 会拒绝——写完必须 pytest 验证）

---

## 六、YAML 格式兼容性陷阱

项目中的 claims YAML 存在**两种格式**：完整 schema 格式（含 `source_path`/`source_date`/`subject`/`statement`/`links` 等全部 REQUIRED_FIELDS）vs 简化格式（`topic`/`text` 替代 `subject`/`statement`）。`migrate_claims_to_neo4j.py` 有 fallback (`claim.get("statement", claim.get("text", ""))`) 所以两种都能迁移，但 `claim_schema.py` 的 `validate_claim_dict()` 只接受标准字段名。**新建 claim 必须用完整 schema 格式**，写完立即 pytest 验证。反例：本次 session 006.yaml 先用简化格式 → `ValueError: Missing required claim fields` → 重写为完整格式。

## 七、补充标的清单模式

已有方向 claims 只写了核心标的、用户要求补完整清单时：创建新 claim 文件（如 `-006.yaml`），用完整标的清单覆盖该方向，同时在原 claim 的 `interpretation` 中添加交叉引用。新 claim 的 `statement` 必须自包含全部标的+代码。

## 八、版本历史

| 日期 | 变更 | 触发 |
|------|------|------|
| 2026-06-06 | 初稿 | 「磨底期非科技方向」检索调试 → 发现 statement 缺乏标的代码 + 缺少总入口 claim → 代码审查 Neo4j/Qdrant/Agent 三个消费路径后系统化 |
| 2026-06-07 | +200字硬约束 + 压缩示例 | Agent 截断 200 字导致港股部分丢失 → 总入口压缩到 207 字。原则：claim 层修复优先于 Agent 代码改动 |
| 2026-06-07 | +Agent 时效分级引用规则 + 引用纪律 | 全面修改 Agent prompt：六级框架重写、核心原则重写、claims 按时效分级注入。改为「≤7天可参考但需配对数据」 |
| 2026-06-07 | +intensity 字段 + Agent intensity 分级规则 | 方案C实现：561条 claims 全量回填。个股查询 low 排末尾，high boost。prompt 中 🔴🟡⚪ 标注 |
