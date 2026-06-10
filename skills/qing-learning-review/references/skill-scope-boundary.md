# Skill 职责边界与内容归属

## 本 Skill 的职责范围（方法论复盘）

`qing-learning-review` 是**只读分析** skill：
- 读 claims → 统计分析 → 主题漂移 → 矛盾识别 → 生成报告
- **不执行写操作**：不修改 positions.yaml、watchlist.yaml、strategy_pack.yaml
- **不给操作建议**：输出是复盘报告，不是交易建议

## 不属于本 Skill 的内容（常见错放）

以下三类内容**不应**出现在本 skill 中，历史上曾因 skill 合并导致错放：

### 1. 持仓更新 pipeline → 属于 `qing-stock-monitor-update`

❌ 错放示例："当用户要求更新持仓时，执行完整 pipeline：读取 positions.yaml → 获取行情 → 更新 positions.yaml..."

✅ 正确归属：`qing-stock-monitor-update` 的 Step 2（收集变化源：用户操作）和 Step 4（执行修改）。

原因：方法论复盘是只读分析，持仓更新是写操作，触发词也不同（`qing review` vs `更新持仓`）。

### 2. 操作建议必须关联 claims → 属于 `qing-stock-analysis` / `qing-agent-router`

❌ 错放示例："给出操作建议时，必须引用具体的 claim ID..."

✅ 正确归属：`qing-stock-analysis`（个股分析时给建议）、`qing-agent-router`（Qing-Agent 混合输出模式要求标注 claim ID）。

原因：复盘报告不给操作建议，给建议的 skill 已有此约束。

### 3. 跨 Skill 兼容性说明 → 属于 `qing-learning`（总入口）

❌ 错放示例：在本 skill 中定义"qing-learning 采用双轨制架构..."

✅ 正确归属：`qing-learning` 总入口 skill 统一定义，下游 skill 引用即可。

原因：架构设计应由总入口定义，避免每个下游 skill 都抄一份导致维护负担。

## 新增内容时的自查清单

在 patch 本 skill 前，问自己：

1. 这个新 pitfall/step 是否涉及**写 config**？是 → 放到 `qing-stock-monitor-update`
2. 这个新 pitfall/step 是否涉及**给用户操作建议**？是 → 放到 `qing-stock-analysis` 或 `qing-agent-router`
3. 这个新 pitfall/step 是否描述**qing-learning 体系的整体架构**？是 → 放到 `qing-learning` 总入口
4. 这个新 pitfall/step 是否只涉及**读 claims、分析一致性、生成报告**？是 → 可以放在本 skill

## 历史背景

2026-06-10 合并 `qing-methodology-review` → `qing-learning-review` 时，曾误将上述三类内容带入。本文件作为边界声明，防止未来类似错放。
