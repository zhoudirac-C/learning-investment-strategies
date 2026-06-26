# 市场大盘分析方法论系统提取方案 v2

> **目标**：从 UP 所有历史早盘/复盘中系统提取大盘分析方法论，追加到知识库和框架中，使 qing-agent 具备 UP 级别的大盘分析能力。同时改造 qing-learning 使其具备**持续学习**新方法论的能力。
>
> **核心原则**：临时索引跟踪进度，最早到最新逐篇消化，不遗漏不重复。完成后删索引。改造 qing-learning 保证后续增量自动捕获。
>
> **范围**：仅 `sources/raw/财经/早盘*` 和 `sources/raw/财经/复盘*`（~190 篇）。盘中动态/午盘/周复盘不纳入本次批量提取。

---

## 一、架构全景

```
┌──────────────────────────────────────────────────────────┐
│                     qing-learning                          │
│                                                           │
│  ┌───────────────────────────────────────────────────┐   │
│  │          【Phase 2 批量回填】临时工作流              │   │
│  │  190 篇早盘/复盘 → 临时索引 → LLM逐篇提取          │   │
│  │  → 方法论 claims → 更新索引                        │   │
│  └───────────────────────────────────────────────────┘   │
│                         │                                 │
│                         ▼ (Phase 3 归纳)                   │
│  ┌───────────────────────────────────────────────────┐   │
│  │  大盘分析方法论.md  ←  market-breadth-framework.md  │   │
│  └───────────────────────────────────────────────────┘   │
│                                                           │
│  ┌───────────────────────────────────────────────────┐   │
│  │        【Phase 3.5 qing-learning 改造】持续学习      │   │
│  │                                                     │   │
│  │  ingestion 管线: Step 6 → 检测新方法论 claims        │   │
│  │  review: Durable Rule 增加方法论框架对照             │   │
│  │  新触发: 「更新方法论」→ 增量合并到 framework        │   │
│  └───────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────────┐
│                  qing-agent (Phase 4)                      │
│  market_analyst 加载 market-breadth-framework.md          │
│  market_analysis_framework.txt 注入分析逻辑链              │
└──────────────────────────────────────────────────────────┘
```

---

## 二、执行流程（五阶段）

### Phase 1: 初始化

```
1. 扫描 sources/raw/财经/早盘* + sources/raw/财经/复盘*
2. 共 190 篇，按 pub_time 排序（最早→最新）
3. 创建 methodology_extraction_index.json
4. 所有 status = "pending"
```

### Phase 2: 批量回填（逐篇提取）

对每篇 pending 文件：

```
Step 1: Agent 读 raw 全文
Step 2: 识别大盘分析方法论（L1-L4 四层维度）
Step 3: 【去重】搜索现有 claims，确认是否已有相同方法论
        - Qdrant 语义搜索 + Neo4j 关键词搜索
        - 若已存在 → 不新建，记录到 methodology_claims_index.md 中标注 "referenced"
        - 若存在但需拆分/修改 → 修改已有 claim，记录标注 "modified"
        - 若是新方法论 → 走 Step 4 新建
Step 4: 写方法论 claim（claim_type=methodology/technical-signal, timeframe=permanent）
Step 5: gate_validate_claims.py 验证
Step 6: 更新两个记录：
        a. methodology_extraction_index.json: status=done, claims_extracted, methodology_tags
        b. methodology_claims_index.md: 追加到对应 L1-L4 分类下，标注 "new/referenced/modified"
Step 7: 输出进度
```

**分批次执行**：每批 10-20 篇，断点可续。

**⚠️ 知识库同步**：Phase 2 完成后（有新 claim 或修改了已有 claim），必须运行完整的 knowledge base sync：
```
discover → Neo4j migrate → Qdrant rebuild → restart Agent
```
详见 `docs/neo4j-relation-pipeline.md`。同步后才能进入 Phase 3。

#### Phase 2 关键产出物

| 文件 | 用途 |
|------|------|
| `methodology_extraction_index.json` | 进度追踪：哪篇 raw 处理了、跳过了 |
| `methodology_claims_index.md` | **汇总文档**：所有 L1-L4 方法论 claims 的完整清单，标注来源 raw、状态（new/referenced/modified）、claim ID。Phase 3 用它归纳。 |

### Phase 3: 归纳总结（全部提取完成后）

```
1. 从索引中读取所有方法论 claims
2. 按 L1-L4 分类归纳 → 写 大盘分析方法论.md
3. 提炼为可执行 playbook → 写 market-breadth-framework.md
4. 更新 framework/README.md + knowledge/wiki/index.md
```

### Phase 3.5: qing-learning 改造（**新增**）

这是确保后续能持续学习的关键。改造 3 个文件：

#### 3.5.1 `skills/qing-learning/SKILL.md` — 新增两个触发路由

```markdown
| 触发词 | 加载子流程 |
|--------|-----------|
| 更新方法论、merge methodology、合并方法论 | **methodology-merge** 工作流 |
| 提取大盘方法、bulk extract methodology | **Phase 2 批量回填** 工作流 |
```

**methodology-merge 工作流**（新增到 SKILL.md）：

```
1. 扫描所有 claim_type=methodology + timeframe=permanent 的 claims
2. 对比 market-breadth-framework.md 已有内容
3. 找出未收录的新方法论
4. 输出：新增条目列表 + 建议的 framework 更新
5. 用户确认后：patch framework + 更新 wiki
```

#### 3.5.2 `skills/qing-learning-ingestion/SKILL.md` — 新增 Step 6: Methodology Check

在现有 Step 5（commit）之后，新增 Step 6：

```
### Step 6: Methodology Check（方法论感知）

每轮 ingestion 完成后，自动检查本次新增的 claims：

1. 是否有 claim_type = methodology 或 technical-signal（且 timeframe = permanent）？
2. 是否涉及大盘分析四层维度（L1-L4）？
3. 若是 → 输出提示："本次消化了 N 条方法论，建议运行「更新方法论」合并到 framework"

此步骤不阻塞管线，仅提醒。Agent 不应自动合并——等用户说"更新方法论"时再执行。
```

#### 3.5.3 `skills/qing-learning-review/SKILL.md` — 增强 Step 5 Durable Rule 筛选

在现有 Durable Rule 筛选条件中，新增：

```markdown
6. **方法论框架对比**：将本次 review 窗口内的 methodology claims 与 market-breadth-framework.md 交叉对比，标记「已收录 / 新方法论 / 矛盾」状态。矛盾归入 contradiction 分类处理。
```

这样 review 跑的时候会自动发现新方法论。

#### 3.5.4 新增引用文件：`skills/qing-learning/references/methodology-merge-workflow.md`

详细的操作步骤文档。从方法论 claims → 对比 framework → 输出更新建议 → 执行 patch 的完整流程。Agent 加载后按步执行。

---

### Phase 4: qing-agent 集成

```
1. market_analyst 节点加载 market-breadth-framework.md
2. market_analysis_framework.txt 注入 L1-L4 分析逻辑链
3. 新增 microcap_index 数据源（微盘股指数实时行情）
4. 测试验证
```

### Phase 5: 清理

```
1. 确认所有文件 done/skipped
2. 提交所有新增内容
3. 删除 methodology_extraction_index.json
4. 后续增量更新：标准 ingestion 管线 + Step 6 检查 + 用户说"更新方法论"时合并
```

---

## 三、学习目标（L1-L4 四层维度）

| 层级 | 提取内容 | 关键词（文件名匹配） |
|------|---------|-------------------|
| **L1: 指数结构** | 多级别顶底（120/90/60/30分）、MACD钝化vs结构、九转序列（低9/高9）、波浪修正、关键位推理 | `分钟` `钝化` `结构` `顶` `底` `序列` `低9` `高9` `波浪` `ABC` `纠错` `突破` |
| **L2: 全A广度** | 全A趋势结构、中阳线确认信号、历史对照、下跌模式（台阶式/温水煮蛙）、量能配合 | `全A` `中阳线` `广度` `趋势下跌` `震荡` `历史对照` |
| **L3: 微盘联动** | 三指数共振/背离、微盘股破位对主线压制、游资动态、大小盘同步 | `微盘` `背离` `共振` `大小盘` `压制` `同步` |
| **L4: 情绪判断** | 情绪锚点（北证）、20cm晋级率、大票带动作用、跌停结构分析、分歧→修复转换 | `情绪` `跌停` `涨停` `连板` `晋级` `分歧` `修复` `锚点` `北证` |

---

## 四、临时进度索引

```json
// config/stock_monitor/methodology_extraction_index.json
{
  "version": "2.0",
  "scope": "早盘+复盘 only",
  "total_files": 190,
  "files": {
    "早盘：26-01-05：日线高10，12连阳关口，商业航天AI机器人.md": {
      "status": "pending",
      "pub_date": "2026-01-05",
      "claims_extracted": [],
      "methodology_tags": []
    }
    // ... 190 entries
  },
  "methodology_categories": {
    "L1_指数结构": {"claims": [], "count": 0},
    "L2_全A广度": {"claims": [], "count": 0},
    "L3_微盘联动": {"claims": [], "count": 0},
    "L4_情绪判断": {"claims": [], "count": 0},
    "Lx_其他": {"claims": [], "count": 0}
  }
}
```

---

## 五、文件改动清单

### 新增

| 文件 | 阶段 | 说明 |
|------|------|------|
| `config/stock_monitor/methodology_extraction_index.json` | Phase 1 | 临时索引（Phase 5 删） |
| `config/stock_monitor/methodology_claims_index.md` | Phase 2 | 方法论 claims 汇总清单（Phase 3 用，Phase 5 保留） |
| `knowledge/wiki/投资方法论/大盘分析方法论.md` | Phase 3 | 系统方法论 |
| `framework/market-breadth-framework.md` | Phase 3 | 可执行 playbook |
| `skills/qing-learning/references/methodology-merge-workflow.md` | Phase 3.5 | 方法论合并工作流 |
| `docs/plans/market-analysis-methodology-extraction-plan.md` | 本文档 | 保留 |

### 修改

| 文件 | 阶段 | 改动 |
|------|------|------|
| `skills/qing-learning/SKILL.md` | Phase 3.5 | 新增「更新方法论」+「提取大盘方法」触发路由 + methodology-merge 工作流 |
| `skills/qing-learning-ingestion/SKILL.md` | Phase 3.5 | 新增 Step 6 Methodology Check |
| `skills/qing-learning-review/SKILL.md` | Phase 3.5 | Step 5 新增方法论框架对比 |
| `framework/README.md` | Phase 3 | 新增 market-breadth-framework.md 索引 |
| `knowledge/wiki/index.md` | Phase 3 | 新增 大盘分析方法论.md |
| `market_analysis_framework.txt` | Phase 4 | 注入 L1-L4 分析逻辑链 |
| `nodes.py` | Phase 4 | 加载 market-breadth-framework.md |

### 不改

| 文件 | 原因 |
|------|------|
| `extract_claims_pipeline.py` | 方法论 claims 复用现有 C2 管线 |
| `gate_validate_claims.py` | 同上 |
| `情绪判断.md` / `关键点位.md` / `量能判断.md` | 已有 wiki，新方法论引用它们 |

---

## 六、Phase 3.5 详细设计：qing-learning 改造

### 6.1 为什么 Phase 3 和 Phase 4 之间需要这一步

| 阶段 | 解决的问题 |
|------|-----------|
| Phase 2-3 | 历史数据一次性回填 → 产出 framework |
| Phase 3.5 | **保证后续新增动态中的方法论不会丢失** |
| Phase 4 | 让 Agent 用上方法论 |

没有 Phase 3.5，Phase 5 删索引后，新 UP 动态中的方法论提取就断了——ingestion 管线只按 C2 流程提取一切 claim，不区分方法论 vs 普通观点，也不做"这条方法论要不要加入 framework"的判断。

### 6.2 改造后的完整链路

```
新 UP 动态
  │
  ▼
B站监控采集 → sources/raw/财经/
  │
  ▼
qing-learning-ingestion（标准管线）
  ├─ Step 1-5: 标准 claims 提取 + wiki + commit
  └─ Step 6: 【新】检测到 methodology claims → 提示用户
       │
       ▼
用户说「更新方法论」
  │
  ▼
methodology-merge 工作流（新的子流程）
  ├─ 扫描所有 methodology claims
  ├─ 对比 market-breadth-framework.md
  ├─ 输出新增/矛盾
  └─ 用户确认 → patch framework
       │
       ▼
qing-learning-review（每周）
  ├─ Step 5: Durable Rule 筛选
  └─ 【增强】方法论框架对比检查
```

### 6.3 methodology-merge 工作流伪代码

```
输入: 无（自动扫描所有 methodology claims）
输出: methodology-merge-report.md

1. 加载 market-breadth-framework.md 全文
2. 加载所有 claim_type=methodology/technical-signal + timeframe=permanent 的 claims
3. 对每条 claim:
   a. 语义对比 framework 已有内容
   b. 分类: already_covered / new_methodology / contradiction / needs_clarification
4. 生成报告:
   - 新增方法论 N 条
   - 已有覆盖 M 条
   - 矛盾 K 条（需人工裁决）
5. 用户确认后:
   a. patch market-breadth-framework.md（追加新条目）
   b. 同步更新 大盘分析方法论.md（汇总 wiki）
   c. commit
```

### 6.4 ingestion Step 6 的实现细节

```markdown
### Step 6: Methodology Check（方法论感知）

**触发条件**: 每次 `extract_claims_pipeline.py done` 后自动执行。

**执行**:
```bash
# 检查本次新增的 claims 中是否有方法论
grep -l "claim_type: methodology\|claim_type: technical-signal" \
  knowledge/claims/claim-YYYYMMDD-*.yaml | while read f; do
  grep "timeframe: permanent" "$f" && echo "  → $f"
done
```

**输出示例**:
```
本轮 ingestion 新增方法论 claims:
  - claim-20260613-001-e: 全A中阳线是建仓唯一信号
  - claim-20260613-001-g: 60分钟以上周期底部结构=纠错信号

建议后续运行「更新方法论」合并到 framework。
```

**注意**: 此步骤不自动写 framework。必须等用户明确指令。
```

---

## 七、验收标准

- [ ] Phase 2: 190 篇全部 done/skipped，每篇的 methodology claims 写入索引
- [ ] Phase 3: `大盘分析方法论.md` 包含 L1-L4 四层完整方法论
- [ ] Phase 3: `market-breadth-framework.md` 可作为 Agent prompt 直接注入
- [ ] Phase 3.5: `qing-learning` 新增「更新方法论」触发路由
- [ ] Phase 3.5: `qing-learning-ingestion` Step 6 可检测新方法论
- [ ] Phase 3.5: `qing-learning-review` Step 5 可做方法论框架对比
- [ ] Phase 4: Agent 输出体现多级别顶底结构判断
- [ ] Phase 4: Agent 输出体现微盘股/全A/主线共振判断
- [ ] Phase 5: 临时索引删除，后续增量学习正常
- [ ] 回归: pytest stock_monitor 不受影响
