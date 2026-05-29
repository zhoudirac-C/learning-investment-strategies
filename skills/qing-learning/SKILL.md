---
name: qing-learning
description: Use when the user asks to ingest, learn, digest, or update new blogger investment content, including ing, 学习今天内容, 消化早盘, 更新方法论, or processing Raw files.
---

# qing-learning

## 目标

持续学习博主新内容，更新 `sources`、`knowledge/claims`、`knowledge/wiki`、`methodology`、`framework` 和日志。

## 触发

用户表达以下意图时使用：

- `ing`
- 学习今天内容
- 消化这篇早盘/午盘/复盘
- 更新博主方法论
- 处理 Raw 中的新稿

## 必读参考

1. 先读 `framework/learning-update-protocol.md`。
2. 抽取 claim 前读 `skills/qing-learning/references/claim-schema.md`。
3. 遇到矛盾观点时读 `framework/contradiction-policy.md`。

## 工作流程

1. 运行 `scripts/find_unprocessed.py` 找未处理 raw。
2. 每次默认只处理一篇 raw，除非用户明确要求批量。
3. LLM 必须阅读全文后再写入任何结论。
4. 先抽取 claims，再更新 wiki、methodology、framework。
5. 只有满足 durable rule 的观点才进入 framework。
6. 更新 `knowledge/wiki/index.md`、`knowledge/claims/index.md` 和 `knowledge/wiki/log.md`。
7. 判断是否需要更新 `knowledge/wiki/投资方法论/博主方法论总纲.md`。
8. 输出 Learning Update Report。

## 文档分层与总纲更新规则

学习新 raw 时按以下层级沉淀，不要把单日盘面直接写成长期方法论：

1. `sources/raw/财经`：保留原始内容或整理稿，作为可回溯证据。
2. `knowledge/claims`：抽取带 source path、evidence quote、scope、confidence 的观点卡。
3. `knowledge/wiki/每日复盘`：沉淀单日盘面、早午晚盘判断和案例。
4. `knowledge/wiki/市场分析`、`knowledge/wiki/投资方法论`：沉淀可复用专题，如指数、量能、主线、仓位、做T、科创虹吸。
5. `framework`：只写跨阶段可复用、可验证、可执行的 durable rule。
6. `knowledge/wiki/投资方法论/博主方法论总纲.md`：最高层小白教材和导航页，只吸收已经被多篇 raw 或多个市场阶段验证过的稳定框架。

### 双轨制：市场认知层 vs 操作工具层

博主内容分为两个轨道，沉淀路径不同：

**轨道A：市场认知层（大方向思路）**
- 来源：每日早盘/午盘/复盘/动态
- 内容：市场周期、主线判断、板块扩散、资金行为、情绪周期
- 特点：随市场变化，需要持续更新，有保质期
- 沉淀：claims → wiki → methodology → framework

**轨道B：操作工具层（技术分析课程）**
- 来源：视频课程（技术分析第一课/第二课/...）
- 内容：K线形态、技术指标、量价分析、支撑压力、买卖纪律
- 特点：一旦学会永久有效，不随市场变化
- 沉淀：直接进 `framework/technical-analysis-framework.md` 和 `methodology/technical-analysis.md`

**技术课程处理规则**：
- 识别 source_type = `video-course` 或 `technical-lesson` 的内容
- 技术教学内容不进入 `claims/`（因为不是"观点"是"知识"）
- 技术教学内容直接进入 `framework/technical-analysis-framework.md` 和 `methodology/technical-analysis.md`
- 若需标记 claim，使用 `claim_type: technical-knowledge`，`timeframe: permanent`

总纲不是每次学习都必须更新。只有满足以下任一条件时才更新总纲：

- 新观点跨多篇 raw 反复出现，并且能解释不同交易日或不同市场环境。
- 新观点改变核心框架，如周期定位、主线判断、个股分类、仓位管理、交易纪律。
- 新观点补齐总纲缺失模块，并且已经有足够案例支撑。
- 原有总纲表述过窄、过时或与最新稳定框架存在冲突，需要修订。

以下内容不要直接进入总纲：

- 单日指数点位、某天早盘剧本、尾盘临时操作。
- 只依赖一条消息催化、尚未验证持续性的题材。
- 只适用于某只个股或某个短线窗口的策略。
- 与旧观点冲突但还没有足够样本确认的新判断。
- **技术课程中的具体工具**（如长红线定义、布林线公式）——这些进 `technical-analysis-framework.md`，不进总纲。

每次 Learning Update Report 必须说明：

- 本次新增/更新了哪些 raw、claims、wiki、framework。
- `博主方法论总纲.md` 是否更新。
- 如果总纲没有更新，说明原因，例如"本次为单日盘面案例，尚未满足总纲级沉淀条件"或"本次为技术课程，已更新 technical-analysis-framework"。

## 禁止事项

- 不用脚本替代 LLM 判断方法论变化。
- 不把单日语境直接提升为长期 framework。
- 不创建没有 source path 和 evidence quote 的 claim。
- 不删除旧观点；冲突观点使用 supersedes 或 contradicts 连接。
