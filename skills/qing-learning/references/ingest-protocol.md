# Ingest Protocol

1. 确认 source path、date、source_type。
2. 阅读全文。
3. **判断内容轨道**：
   - 若是每日盘面（早盘/午盘/复盘/动态）→ 走轨道A
   - 若是技术课程（video-course/technical-lesson）→ 走轨道B
4. **轨道A**：抽取 atomic claims → 分类 claim_type/timeframe/confidence → 对比现有 claims 和 methodology → 更新 wiki/cases → 只有 durable rule 成立才更新 methodology/framework
5. **轨道B**：直接更新 `framework/technical-analysis-framework.md` 和 `methodology/technical-analysis.md`，不抽取 claims（技术知识不是观点）
6. 更新 index/log。
7. 输出 Learning Update Report（说明处理了哪个轨道）。

## 置顶评论补充流程

**场景**：UP 在已发布的动态/视频下追加置顶评论（如"刚想起来，今天视频忘了讲一件事..."），用户要求将其补充到已有 raw 文件中。

**处理步骤**：
1. **定位目标 raw**：根据日期和内容定位到对应的 raw 文件（如复盘 `复盘：26-06-08：...`）
2. **追加到 raw 末尾**：在 raw 文件末尾新增章节（如 `## 六、UP置顶评论补充`），完整保留 UP 原话 + 要点提炼
3. **抽取补充 claim**：
   - `claim_type`：根据内容判断（通常为 `market-cycle` 或 `sector-theme`）
   - `intensity: high`（UP 追加的重要补充）
   - `evidence_quote`：完整引用置顶评论原文
   - `interpretation`：说明这是复盘后的追加补充，与主 claims 的关系（补充/修正/强化）
   - `related_claims`：链接到同一 raw 的主 claims（如 `claim-20260608-004-a`）
   - `tags`：包含 `置顶评论` 以便后续检索
4. **更新 claim 文件**：将补充 claim 追加到同一日期的 claim YAML 文件末尾（不要新建文件）
5. **走知识库同步流水线**：discover → migrate → Qdrant → restart

**示例**（2026-06-08 北证情绪锚点）：
```yaml
- id: claim-20260608-004-j
  topic: 北证是情绪锚点——聪明资金动向
  statement: UP置顶评论补充：周五最先动的方向是北证，今天早盘冲得最厉害的也是北证...
  claim_type: market-cycle
  intensity: high
  evidence_quote: "刚想起来，今天视频忘了讲一件事，复盘也忘了讲..."
  interpretation: UP在复盘后追加的重要补充——北证是本次情绪周期的先行指标...
  related_claims:
    - claim-20260608-004-a
  tags:
    - 北证
    - 情绪锚点
    - 置顶评论
```
