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
