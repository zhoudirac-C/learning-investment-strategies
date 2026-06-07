# 混合内容 Ingestion：单篇 raw 同时覆盖轨道A和轨道B

> 创建于 2026-06-07，基于技术分析第二课的实际处理经验。

## 问题

UP 的技术课程视频中经常穿插对当前行情的判断。例如：
- 主线是讲长黑线的三种形态（轨道B，技术知识）
- 但开头会用美股暴跌/标普500高档长黑作为案例（轨道A，行情观点）
- 中间会暗示当前科技方向可能已出现流星线、老灯股出现倒装铁锤线（轨道A）

如果所有 claims 放入同一个文件，会导致：
- 轨道B的 permanent 知识和轨道A的 time-limited 观点混在一起
- 时效管理困难（30天后行情观点过期，但技术知识永不过期）
- Agent 检索时无法区分"这是永久知识还是短期观点"

## 规则

**单篇 raw 同时包含轨道A和轨道B内容时，必须拆分为两个独立的 claim 文件**：

| 文件 | claim_type | timeframe | 示例 |
|------|-----------|-----------|------|
| `claim-YYYYMMDD-001.yaml` | `market-cycle`, `sector-theme`, `operation` | `short-term` / `medium-term` | 轨道A：行情观点 |
| `claim-YYYYMMDD-002.yaml` | `technical-knowledge` | `permanent` | 轨道B：技术教学内容 |

## 执行步骤

1. **识别**：通读 raw 全文，用高亮标记轨道A（"现在"、"当前"、"周五"等时间词+行情判断）和轨道B（"技术分析"、"K线形态"、"定义"等教学语言）
2. **分轨**：轨道B内容写入 `-002.yaml`，轨道A内容写入 `-001.yaml`
3. **轨道B 额外处理**：技术教学内容除了进 claims，还必须更新 `framework/technical-analysis-framework.md`
4. **编号规则**：轨道A 用 `-001`（优先，因为行情观点时效性强），轨道B 用 `-002`（permanent，不急）
5. **交叉引用**：两个文件的 `source_path` 指向同一个 raw 文档

## 反面案例

2026-06-07 的技术分析第二课 raw 中，UP 在教学长黑线定义的同时穿插了：
- "周五美股跌成那个样子" → 这是行情判断，应进轨道A
- "黄金坑开始挖了" → 这是行情判断，应进轨道A
- "长黑线光头光脚的定义是..." → 这是技术知识，应进轨道B

如果混在一个文件里，Agent 在讲"黄金坑"时检索到的是 permanent claim（claim_type: technical-knowledge），就会错误地把它当作永久知识引用。反之，如果行情观点混入技术知识文件，30天后观点过期但被标记为 permanent，会导致 Agent 引用过期的"科技股看空"观点。

## 验证清单

- [ ] 轨道A 文件的所有 claims 都有明确的时间框架（short-term/medium-term）
- [ ] 轨道B 文件的所有 claims 都是 `claim_type: technical-knowledge`, `timeframe: permanent`
- [ ] 两个文件的 `source_path` 指向同一个 raw
- [ ] 轨道B 内容已同步到 `framework/technical-analysis-framework.md`
- [ ] 课程进度表已更新
