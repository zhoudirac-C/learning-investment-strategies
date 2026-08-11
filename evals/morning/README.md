# 早盘三方对照归因（evals/morning/）

每个交易日傍晚，对照三方材料做归因，找出系统早盘分析的**信息源缺失**与**逻辑推理缺失**：

```
UP 早盘文（sources/original/bilibili/ 当日 09:xx 长文）
    vs
qing-agent 早盘输出（qing-agent-request.<date>.log 的 09:26/09:50/10:xx 各次 final_output）
    vs
实际盘面（指数/量能/板块/梯队，infra/data/limit_pool + 快照）
```

## 流程

1. 提取当日 UP 早盘文的判断清单（方向/情形/定性/纪律）。
2. 提取 qing-agent 当日早盘各次 final_output（`response_payload.final_output`），
   并检查 `reasoning_steps` 中 `市场总结` 是否 fallback。
3. 用午收/收盘数据验证 UP 与系统各自的判断。
4. 归因分类：
   - **数据缺**：UP 用了而系统没有的信息源（附证据字段）。
   - **推理缺**：UP 用了而系统/模式库没有的推理步骤（→ 走 framework/proposals/ 提案制）。
   - **工程缺**：链路失败/幻觉/引用失败等（→ 直接修，不开提案）。
5. 归因落盘 `attributions/<date>.md`；处置项转 spec/proposal 后在归因文件中标注去向。

## 与 18:05 shadow 的关系

shadow 盲判（evals/shadow/）是"无 UP 输入"的纯净对照；本目录是"系统实盘早盘输出"
对照 UP 早盘——两者互补：前者验证方法论蒸馏质量，后者验证工程链路与信息源完备性。
