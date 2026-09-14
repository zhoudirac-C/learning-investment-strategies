# discover 分流设计（多 up 体系阶段二）

## 现状
- `find_similar_claims`: Qdrant embedding 召回 top-3 相似 claim
- `judge_relation`: LLM 从 {supersedes, supplements, contradicts, none} 选一个
- `process_claim`: 按 relation 写入 results[supersedes/contradicts/supplements]
- `write_results_to_yaml`: 文本级改写 YAML

## 问题
现有语义隐含"单一作者"假设：
- supersedes = 同一人观点演进（B 过时）
- contradicts = 同一人自相矛盾（触发 review）
- supplements = 同一人补充

加入多 up 后，跨 up 的"方向相反"会被 LLM 判成 contradicts —— 但那是**两人分歧**，
不是同一人自相矛盾。混淆后果：review 环节把正常的分歧误报为"你改口了"。

## 设计

### 1. 按 up_id 分流判定
取出 claim_a 与 claim_b 的 up_id：
- **同 up**（含同虚拟 up，如都是 chanlun-original）→ 走现有 4 选项
  {supersedes, supplements, contradicts, none}
- **跨 up** → 走新选项集
  {agrees, disagrees, supplements, none}
  - `agrees`      = 两 up 观点一致（不写关系，但记录到 pairs）
  - `disagrees`   = 两 up 观点相反/冲突 → 写 `disagrees_with`
  - `supplements` = 一方补充另一方（细节/标的扩展）
  - `none`        = 无关系
  跨 up **禁止**输出 supersedes/contradicts（语义不成立：谁也取代不了谁）

### 2. Prompt 动态组装
同一份 RELATION_PROMPT 模板，按分流注入不同选项说明：
- 同 up 分支：沿用现有文案
- 跨 up 分支：新增 CROSS_UP_PROMPT，明确"A 和 B 来自不同博主，
  观点不一致是正常的，不要判为矛盾"

### 3. 数据结构
results 扩展：
```python
results = {
  "claim_id": cid,
  "supersedes": [],      # 仅同 up
  "contradicts": [],     # 仅同 up
  "supplements": [],     # 两种都允许
  "disagrees_with": [],  # 仅跨 up
  "pairs": [],           # 记录所有判定（含 agrees/none）
}
```

### 4. YAML 写回
在 `contradicts` / `supplements` 之后插入 `disagrees_with` 行（若为空则不写，
保持存量文件干净）。

写回位置顺序：
```
supersedes: [...]
contradicts: [...]
disagrees_with: [...]   <- 新增（仅跨up有内容时写）
supplements: [...]
last_discovered: ...
```

### 5. 向后兼容
- 存量 claim 的 supersedes/contradicts 保持不变（它们本来就是同 up 判出来的）
- 无 `disagrees_with` 字段的 claim 照常处理（视为空 list）
- 新字段为空时不写入 YAML（避免 4000+ 文件被无意义改动）

### 6. up_id 缺失兜底
- 若任一方 up_id 缺失 → 视为"unknown"，同 unknown 视为同 up
  （保守：不确定时走同 up 路径，不误判为跨 up 分歧）

## 影响面
- `discover_claim_relations.py`：RELATION_PROMPT 拆分 + process_claim 分流 + 写回
- `claim_schema.py`：已有 disagrees_with（阶段一已加）
- Neo4j/Qdrant：待环境可用（本次不动）
- 测试：新增跨 up 分流用例

## 待验证
- Neo4j 未运行 → 无法端到端验证，只能单测 judge_relation 的分流逻辑
- Qdrant 需要 claim 有 up_id payload（当前索引可能未含该字段，需确认）
