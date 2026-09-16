# Claim Schema 扩展：新增 `stance` 字段（事实 vs 观点）

> **状态：✅ 已实施（2026-09-17，commit a58557d）** —— 采用**四值**方案（用户中途由三值改四值）
> 已落地：Schema / Gate / 提取 prompt / Skill 四层。图库层（Neo4j+Qdrant）与存量回填**暂缓**。
> 提案日期：2026-09-17
> 提案人：用户（提出质疑）+ Agent（方案设计）
> 关联 skill：`qing-claim-schema-evolution`

---

## 一、问题（用户提出，已实证）

用户原话：

> 「我感觉青枫的很多是陈述事实，不是他看好的观点。这里提取 claim 时，不应该算作他推荐或者看好。」

### 实证：9/16 晚间复盘 38 条 claim 的性质分布

| 类别 | 条数 | 占比 |
|---|---:|---:|
| **纯事实陈述**（盘面/数据/政策/研报转述） | **30** | **79%** |
| 含观点/操作判据 | 5 | 13% |
| 事实+观点混合 | 3 | 8% |

**典型"被误当观点"的例子**：

| claim | statement | 本质 |
|---|---|---|
| 003-a | 今日指数低开高走温和放量 | 📊 行情播报 |
| 003-b | 成交额回升至 1.84 万亿打断连续缩量 | 📊 数据 |
| 003-k | 通信设备与半导体行业指数领涨 | 📊 涨幅榜 |
| 003-s | 黄酒概念逆势大涨创历史新高 | 📊 板块表现 |
| 003-t | 六部门意见将酿造列入历史经典产业 | 📰 政策转述 |
| 003-n | 重掺硅片下半年有望继续涨价 | 📄 研报转述 |
| 003-z | 中瓷电子静电卡盘批量供货 | 📄 公司资料 |

**与之平级存放的真观点**（仅 5 条）：

| claim | statement |
|---|---|
| 003-ac | **国产化率低与批量供货构成科技选股双条件** |
| 003-ak | 参与对象收敛至国产化低且批量供货环节 |
| 003-m | 反转取决于新叙事被市场认可 |
| 003-y | 宏观事件影响级别判据 |
| 003-aj | 电网设备为跟随方向且需等招标验证 |

---

## 二、三个下游后果（为什么这是真问题）

### 后果①：`confidence: high` 语义被稀释

- 事实陈述的「high」= **"这个数字我读对了"**
- 观点判断的「high」= **"我押上声誉认为这会发生"**

**两者当前不可区分** → 查询"UP 高置信度看好方向"时，**行情播报会被一并捞出**。

### 后果②：`intensity` 字段对 79% 的 claim 是噪声

`intensity: medium` 本意是观点的**强度**。但"今天涨了 4.14%"**没有强度可言**。

### 后果③：已造成过一次真实误判（本会话实录）

用户问「青枫浦和 Mark__Huang 的观点是否冲突」时，Agent 第一版答案列的
**「冲突②：科技整体方向」**，依据是 `003-d 风格从非科技切回科技获量价确认`。

**但严格说，003-d 是青枫浦在描述"今天发生了什么"，不是"我看好科技"。**
用它去对比 Mark 的「科技还是不行」，**本身就是错误的对比** —— 用户质疑正中要害。

---

## 三、根因

`claim_type` 的 11 个枚举值**全是"主题维度"（讲的是什么）**，无一描述"话语性质"：

```python
VALID_CLAIM_TYPES = {
    "market-cycle", "sector-theme", "stock-view", "methodology",
    "risk", "technical-signal", "technical-knowledge", "macro",
    "operation", "catalyst", "general",
}
```

`gate_validate_claims.py` 的 Gate 1 只校验 `claim_type` **是否在枚举内**——
把行情播报标成 `market-cycle` **完全合法**，管道无任何"事实/立场"门禁。

---

## 四、方案：新增 `stance` 字段

### 4.1 字段定义（**非必填**，故不触发存量全量校验失败）

刻意**不加入 `REQUIRED_FIELDS`**——加入会让 5,234 条存量 claim 全部校验失败
（见 skill §1 铁律）。

```python
# claim_schema.py
VALID_STANCE = {"fact", "view", "mixed"}

OPTIONAL_FIELDS = {
    "up_name",
    "disagrees_with",
    "related_stocks",
    "tags",
    "topic",
    "stance",          # ← 新增
}
```

| 取值 | 语义 | 判别标准 |
|---|---|---|
| **`fact`** | 事实陈述/转述 | 行情数据、涨跌幅、成交额、政策/文件转述、研报引用、公司资料、公开数据 |
| **`view`** | 对**具体标的/板块/事件**的判断 | 看好/看空某方向、操作建议、选股判据、方法论 |
| **`market-regime`** | 对**市场/情绪/风格处于什么阶段**的定性定位 | 周期位置、级别判定、性质定性 |
| **`mixed`** | 两者兼有 | 先陈述事实再给出判断（如「某数据 X，所以我认为 Y」） |

### 4.1.1 ⚠️ 「市场处于什么阶段」归 `market-regime`（用户专门追问）

**用户提问**：「如果是当前市场处于什么阶段这样的判断，是否能归到观点？」

**答：归，且单独成值。**

**理由**：它既是观点（不可换个作者说仍成立），又是**高频且独立的检索需求**
——实测 9 月 claim 中含「阶段/性质/级别」判定的有 **179 条**。

**判别法（看判断对象）**：

| 判断对象 | stance | 例 |
|---|---|---|
| 大盘/全局/风格/情绪周期 | **`market-regime`** | 「风格切换已经完成，但级别仍是反弹而非反转」<br>「本轮情绪周期已进入尾部释放阶段」<br>「用混沌期描述有直观意义，但不足以确认退潮结束」 |
| 某个板块/个股/主题 | **`view`** | 「依然看好国产替代方向」<br>「电网设备属于跟随方向，独立行情需等招标数据」 |

**关键规则**：**即使句子里带数据，只要落点是阶段/级别/性质定位，就是 `market-regime`**；
数据部分放进 `evidence_quote`。

> 判据同门槛：把「成交额 1.84 万亿」换个人说还成立 → `fact`；
> 把「已进入尾部释放阶段」换个人说**不成立** → 观点。

**实测预标**（9/16 的 15 条应提条目）：**9 条 `market-regime` + 6 条 `view`，零歧义**。

### 4.2 与 `claim_type` 的关系（正交，不替代）

```
claim_type = 讲的是什么（主题维度）  →  market-cycle / sector-theme / ...
stance     = 怎么讲的（话语性质）    →  fact / view / mixed
```

**两者正交**。例：
- `claim_type=market-cycle` + `stance=fact` → 今日指数收报 3891.60
- `claim_type=market-cycle` + `stance=view` → 风格切换完成但级别仍是反弹
- `claim_type=stock-view` + `stance=fact` → 中瓷电子静电卡盘批量供货
- `claim_type=stock-view` + `stance=view` → 看好中瓷电子的卡位

### 4.3 查询收益

```python
# 只看 UP 真正表达立场的观点
claims = [c for c in all_claims if c.get("stance") == "view"]

# 排除行情播报噪音
clean = [c for c in all_claims if c.get("stance") != "fact"]
```

`discover_claim_relations` 也可据此**降低 fact 间的相似度召回权重**
（两个行情播报天然高度相似，会污染关系判定）。

---

## 五、五层影响面（改前必读，来自 skill §0）

| 层 | 文件 | 改什么 | 状态 |
|---|---|---|---|
| Schema | `src/qing_investment/claim_schema.py` | `VALID_STANCE` + `OPTIONAL_FIELDS` + `Claim` dataclass 默认值 | ⬜ 待改 |
| 生成 | `scripts/extract_claims_pipeline.py:126` | Step 1 prompt 字段清单（19 → 20，并加判别规则） | ⬜ 待改 |
| 校验 | `scripts/gate_validate_claims.py` | Gate 2 增 `stance` 枚举校验（**仅当字段存在时**） | ⬜ 待改 |
| 关系 | `src/qing_investment/agent/tools/discover_claim_relations.py` | （可选）fact 间降权 | ⬜ 可选 |
| 图库 | `neo4j_client.py` + Qdrant payload | （可选）加 `stance` 属性供过滤 | ⬜ 可选 |

### 5.0 ⚠️ 另有两层必改（2026-09-17 用户指出，Agent 首版漏掉）

用户原话：

> **「提取 claim 的 skill 和历史数据也要处理吧」**

**这两层在首版方案中被漏掉了，是本次提案的重要修正。**

---

### 🔴 第六层：Skill 层（`qing-learning-claim` 等）

**为什么必改**：Skill 里硬编码了「19 个必需字段」及字段清单。
**改 schema 不改 skill → 下一个 agent 照抄旧清单，新字段永远不被填。**
这正是 skill 自己的 §7 警告过的「字段数过期 → 直接导致新提取漏填新字段」。

**实测的过时表述位置（8 处 / 5 个文件）**：

| 文件 | 行 | 现文 | 改为 |
|---|---|---|---|
| `skills/qing-learning-claim/SKILL.md` | 15 | `Gate 1 校验 19 字段` | `校验 19 必需字段 + 可选 stance` |
| 同上 | 70 | `### 19 个必需字段` | 补 `stance` 到**可选字段**表 |
| 同上 | 134 | `☐ 19 个必需字段齐全（含 up_id…）` | 追加 `☐ stance 已填（fact/view/mixed，可选）` |
| `~/.hermes/skills/qing/qing-claim-extraction-ops/references/` ×4 | — | `19 字段`×4 | 标注 + stance 说明 |
| `~/.hermes/skills/qing/qing-pipeline-ops/SKILL.md` | 19 | 19 字段表说明 | 同步 |
| `~/.hermes/skills/qing/qing-claim-schema-evolution/SKILL.md` | 32 | `Step 1 prompt 内嵌的 19 字段列表` | `20 字段` |
| `~/.hermes/skills/qing/qing-learning-claim`（repo 侧同名） | — | 同上 | 同 step（**双份架构**，见下） |

**⚠️ 双份架构坑**（memory 已记）：
- `~/.hermes/skills/` = curator 可写
- `~/learning-investment-strategies/skills/` = 也在 `external_dirs` 内，**同样可改**（2026-09-14 实测，skill §7 已更正"只读"误述）
- **同名 skill 会被拒载** → 两处都要同步改，否则行为不一致

**审计命令**（skill §7 提供，避免凭记忆找漏）：
```bash
grep -rn "19 字段\|19个字段\|19 个必需字段\|18 字段" \
  ~/.hermes/skills/ ~/learning-investment-strategies/skills/ --include="*.md"
```

**判别规则（skill §7 关键区分）**：只改**抄了当时事实**的，不改**举例提及**的。
例：`pipeline-session-quirks` 里的「一次加入 18 个模式」指假阳性模式数，**不改**。

---

### 🔴 第七层：历史数据层（5,234 条存量 claim）

**实测口径**（2026-09-17，用 skill §2.1 的三种 YAML 结构解析器）：

```
文件 602 / 唯一 id 5,234 / 出现次数 5,234
```

> ⚠️ 首版文档写的「4,765」是**过时数字**（2026-09-14 id 冲突修复后的口径）。
> **实际当前 5,234 条**。任何回填脚本的规模估算必须以此为准。

**处置决策**：**本次不回填，但必须留可回填的路径。**

| 方案 | 内容 | 结论 |
|---|---|---|
| 全量回填 5,234 条 | 立刻统一 | ❌ 否——工作量与风险大，且 skill §6.1 教训："独立议题混入会让 diff 无法审查" |
| **不回填 + 下游容错** | 存量 `stance` 缺失 → 视为 `unknown`，不过滤 | ✅ **是** |
| 仅回填近期（9月） | 折中 | ⬜ 可选第二阶段 |

**下游容错是必须的**——否则查询代码 `c.get('stance') == 'view'` 会把
**5,234 条存量全部排除**，反而制造数据不可见。

**推荐查询写法**：
```python
# ✅ 正确：缺字段视为 unknown，保留可见
view_claims = [c for c in claims if c.get("stance", "unknown") in ("view", "mixed")]
# ❌ 错误：会丢掉全部存量
view_claims = [c for c in claims if c.get("stance") == "view"]
```

**若未来决定回填**，按 skill §6 安全模式执行：
1. 启发式预标脚本 + `--dry-run` + `--limit N` 小范围实测
2. 人工抽验准确率
3. **对照实验**（skill §6.1）：回填前后同一 gate 脚本比对错误分布
4. 逐文件**文本级**写入（禁 `yaml.dump` 全量重写）
5. 备份 `cp -r knowledge/claims /tmp/claims_backup/`

---

## 六、⚠️ 最关键的改动：提取纪律（不是加字段，是改行为）

用户 2026-09-17 追加指正：

> **「我感觉不然很多事实描述被错误的当成了观点」**

**这是本提案的核心。** 加 `stance` 字段只是**给错误打了标签**——
如果不改提取纪律，`stance=fact` 的行情播报**依然会以 claim 形式进入库**，
只是多了一个可过滤的标记。**用户要的是"不该进来的别进来"。**

### 6.1 现状：Extractor 没有任何"该不该提"的判别

实测 `scripts/extract_claims_pipeline.py:120-140` 的 Step 1 prompt，
**6 条要求里没有一条涉及"事实 vs 观点"**：

```
1. 每条 claim 包含 19 个必需字段（…）
2. up_id 取值规则（…）
3. 不要包含 related_stocks 和 tags（Step 2 补）
4. 不同的 up 观点可以不一致，这是正常的——不要强行为不同来源的观点做一致性调和
5. 宽松格式，先关注内容完整性
6. 写入后运行编排脚本
```

**第 5 条「宽松格式，先关注内容完整性」明确鼓励多提** → 
**盘面播报被无差别吸入 = 设计使然，不是 bug。**

### 6.2 修正：Step 1 prompt 增加"提取门槛"

**新增第 7 条（判别规则）**：

```
7. **提取门槛（重要）**：只提取"UP 表达的判断/观点/方法论"，跳过纯事实播报。
   - ❌ 不要提：行情数据（涨跌幅/成交额/家数）、涨幅榜描述、政策文件转述、
     研报数据引用、公司公开资料罗列 —— 除非 UP 借此表达了立场
   - ✅ 要提：看好/看空、操作建议、选股判据、对未来预判、方法论、
     对某个事实的**解读**（如"这说明…""意味着…"）
   - ⚠️ 判别法：**问"这句话换个作者还成立吗？"**
     成立 = 事实（跳过或标 fact）；只有该 UP 会这么说 = 观点（提为 view）
   - 若同时含事实与判断（"某数据X，所以我认为Y"）→ 提取**判断部分**，标 stance=mixed，事实部分放 evidence_quote
```

### 6.3 与现有"跳过纯盈亏截图"先例一致

管道**已有**同类过滤先例（`qing-bilibili-manual-fetch` 口径：「跳过纯盈亏截图」），
所以**加"跳过纯行情播报"不是新范式，是补齐同类规则**。

### 6.4 双轨效果对比

| | 只加 `stance` 字段 | 加字段 **+** 提取门槛 |
|---|---|---|
| 9/16 那 38 条 | 仍是 38 条，其中 30 条标 `fact` | **约 8-12 条**（真观点），事实类大幅减少 |
| 查询 `stance=view` | 能筛出 5 条真观点 | 库里本来就只剩真观点 |
| 库体量 | 继续膨胀（5,234 条，79% 噪音） | 增速显著放缓 |
| 关系判定 | fact 间高度相似 → 污染 discover | 噪音源被切除 |

**结论：`stance` 字段与提取门槛是互补的——前者让存量可过滤，后者让增量不再脏。**

### 6.5 实施顺序（重要）

**先改提取门槛，再加字段**（或同批）：
1. 改 Step 1 prompt（门槛规则）← **优先级最高，立竿见影**
2. 加 `stance` 字段（让新 claim 自带标签）
3. Skill 层同步（第六层）
4. 存量回填（可选，第七层）

**若只做 2 不做 1**，等于"给垃圾贴上可回收标签"——垃圾还在库里。

---

## 七、验收标准（实施时用）

```python
import yaml
from qing_investment.claim_schema import VALID_STANCE, validate_claim_dict

# 1) 枚举合法
assert VALID_STANCE == {"fact", "view", "mixed"}

# 2) 新 claim 带 stance 且合法（pipeline strict 模式）
# 3) 存量 claim 缺 stance 不报错（--all 应零新增 error）
#    python scripts/gate_validate_claims.py --all | tail
#    期望：错误数与改动前一致（当前存量 374 条历史错误，见 skill §8）

# 4) 新字段真被生成（不能只改 schema 不改 prompt）
#    跑一篇新提取 → 断言 step1_raw.json 每条都有 stance
```

**⚠️ 必查**：`tests/test_claim_schema.py` 的 fixture 是否因新增字段失败
——因设为 **OPTIONAL**，预期**不失败**，但需实测确认。

---

## 八、待用户拍板的事项

| # | 事项 | 建议 |
|---|---|---|
| 1 | 字段名用 `stance` 还是 `nature` / `epistemic_type` | ✅ 已定：`stance` |
| 2 | ~~三值~~ **四值** `fact/view/market-regime/mixed` | ✅ 已定：四值（用户中途改） |
| 3 | 是否**同步实施**图库层（Neo4j 属性 + Qdrant payload） | ⬜ **暂缓**，待用户决定 |
| 4 | 是否回填存量 5,234 条 | 建议**暂不回填**，新 claim 生效即可 |
| 5 | 是否改 `discover` 的 fact 降权 | 建议**先不动**，观察轮后再评估 |
| 6 | ~~是否同步改 Step 1 提取门槛~~ | ✅ **已做**（commit f56822c/2df5723） |
| 7 | 门槛需否保留一份"事实表" | ✅ 已定：**完全跳过**，事实只在 raw/wiki 留痕 |

---

## 九、不做的事（明确排除）

- ❌ 把 `stance` 加进 `REQUIRED_FIELDS`
- ❌ 用 `yaml.dump` 全量重写存量 claim
- ❌ 顺手修存量 374 条历史字段错误（独立议题）
- ❌ 改动 `claim_type` 枚举（与 `stance` 正交，无必要）

---

## 附：本方案与"方案 B/C"的对比（已排除）

| 方案 | 内容 | 为何不选 |
|---|---|---|
| B | 在 `claim_type` 加 `market-fact` 枚举值 | 与 `market-cycle` 语义重叠；无法标注"research-catalyst 其实是转述" |
| C | 只改 prompt 纪律，纯事实不进 claim 库 | 丢失盘面事实（复盘有用）；存量混淆依旧 |
| **A** | **加 `stance` 字段** | ✅ **采用**（可过滤、可保留、可增量） |
