# 方法论合并工作流（Methodology Merge）

> **触发词**：更新方法论、merge methodology、合并方法论
> **定位**：将新提取的 methodology claims 增量合并到 framework 和 wiki 文档中。
> **前置**：已完成 knowledge base sync（新 claims 已在 Neo4j + Qdrant 中）。

---

## 执行流程

### Step 1: 扫描新方法论 claims

```bash
# 找出所有 methodology 类型的 claims（timeframe=permanent 的方法论是永久的）
cd ~/learning-investment-strategies
grep -rl "claim_type: methodology" knowledge/claims/ --include="*.yaml" | sort
```

或用 Qdrant 语义搜索最近新增的方法论：

```
搜索关键词："多级别顶底" "全A判断" "量能阈值" "情绪判断" "微盘股" "双冰点" "假摔"
limit=10，筛选 claim_type=methodology
```

### Step 2: 对照目标文件

| L1-L4 分类 | 目标 wiki | 目标 framework |
|-----------|----------|---------------|
| L1: 指数结构 | `knowledge/wiki/投资方法论/大盘分析方法论.md` §一 | `framework/market-breadth-framework.md` §Step 2 |
| L2: 全A广度 | 同上 §二 | 同上 §Step 1 + §Step 4 |
| L3: 微盘联动 | 同上 §三 | 同上 §Step 3 |
| L4: 情绪判断 | 同上 §四 | 同上 §Step 5 |

先读取目标文件的完整内容（不用 offset/limit），逐条对比新 claim 是否已收录。

### Step 3: 分类处理

对每条新 methodology claim：

| 情况 | 操作 | 记录 |
|------|------|------|
| **已收录**（语义一致） | 跳过 | `already_covered` |
| **新方法论**（未收录且有独立价值） | 追加到 wiki + 更新 framework | `new_methodology` |
| **矛盾**（与已有方法论冲突） | 标记，需人工裁决 | `contradiction` — 不自动改 |
| **细化**（补充已有方法论的边界条件） | patch 已有条目 | `clarification` |

### Step 4: 生成合并报告

输出 `reports/methodology-merge-YYYYMMDD.md`：

```markdown
# 方法论合并报告 — 2026-06-12

## 新增方法论（N 条）
- claim-xxx: 主题 → 追加到 L1 §1.X

## 已覆盖（M 条）
- claim-yyy: 与已有 §1.Y 一致，跳过

## 矛盾（K 条）
- claim-zzz 与已有 §2.Z 冲突，需人工裁决

## 建议操作
1. patch framework/market-breadth-framework.md: ...
2. patch knowledge/wiki/投资方法论/大盘分析方法论.md: ...
```

### Step 5: 用户确认后执行写入

等用户说"执行合并"后：
1. `patch` 对应 framework/wiki 文件
2. 更新关联文件索引
3. `git add + git commit`

---

## 判断标准：什么算"新方法论"

**✅ 合并**：
- 新的判断规则（如"量能+振幅双维度变盘"）
- 新的操作链路（如"结构形成→减仓，钝化消失→纠错"）
- 量化阈值的更新（如 DIF>30 纠错）
- 新的验证维度（如"20cm晋级率"作为情绪锚点）

**❌ 不合并**：
- 单日市场判断（"今天全A弱修复"）
- 已有的方法论换一种说法重新表述
- 只适用于特定市场环境的判断（除非特殊标注适用范围）

---

## 与 qing-learning-review 的配合

- **review** 负责发现：扫描 claims → 统计漂移 → 识别矛盾 → 输出 durable rule 候选
- **merge** 负责执行：读 review 报告中的候选列表 → 对照 framework → 用户确认 → 写入

两者是前后道关系。review 报告可以作为 merge 的输入。

---

## 相关文件

- [大盘分析方法论](../../knowledge/wiki/投资方法论/大盘分析方法论.md)
- [market-breadth-framework.md](../../framework/market-breadth-framework.md)
- [market-cycle-framework.md](../../framework/market-cycle-framework.md)
