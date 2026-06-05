# qing-learning 更新协议

1. 用脚本列出未处理 raw。
2. LLM 逐篇阅读全文。
3. 先抽取 claims，再更新 wiki、methodology、framework。
4. 只有满足 durable rule 的观点才进入 framework。
   - 若更新的 framework 涉及大盘分析输出格式（如 11 项分析框架、周期判断标准），需同步检查 `prompts/system/market_analysis_framework.txt`。
5. 更新 index 和 log。
6. 输出 Learning Update Report（含 framework 更新内容和 prompt 同步状态）。
