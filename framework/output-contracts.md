# 输出契约

## Learning Update Report

- 处理来源
- 新增 Claims
- 方法论更新
- Framework 更新
- 标的/板块追踪更新
- 矛盾、过期或被替代观点
- 需要人工确认
- 变更文件

## Methodology Review Report

- Review 窗口
- 长期方法论变化
- 方法论澄清
- 矛盾观点
- 过期或降权 Claims
- 更新的 Framework 文件
- 遗留问题

## 个股分析报告

- 标的身份与数据覆盖
- 博主框架定位
- 市场与板块语境
- 技术面与资金面分析
- F10 基本面分析
- 博主历史提及与观点演化
- 多空证据表
- 证伪条件
- 下一期跟踪字段
- 学习结论
- 风险提示

## 双学派分析报告（6 段式）

**触发**：分析涉及 qing + gator 两个学派时（输入含 gator 内容，或用户说「两派都看」）。
**Prompt**：`src/qing_investment/agent/prompts/system/dual_school_output.txt`
**设计**：`docs/design/dual-school-architecture.md` §5.2

1. 共识区 — 两派一致的部分（无共识则明写）
2. 青枫浦上Q 视角 `[qing]` — 缠论结构 + 量价 + 板块温度 + claims，绑价格锚点
3. 鳄鱼派视角 `[gator]` — 规则清单逐条核对（✅/❌/❔）+ 章节来源
4. 矛盾与裁决 — 引用 `framework/school-conflicts.yaml` 辩论卡；未裁决**双列不选边**
5. 操作建议 — 方向层 + 节奏层 + 触发/失效条件；有未裁决矛盾时给出两派各自路径
6. 涌现发现（可选）— 交叉洞察，标 `candidate`，不得当结论用

**硬约束**：
- 两派平权，不预设主次；引用必须在句中标 `[qing]` / `[gator]`
- 未裁决矛盾严禁调和成模糊表述，也不允许 agent 自行选边
- `resolution` 只能来自回测或人工，LLM 不得生成
- gator-method 为第三方提炼库，引用须标注「第三方提炼」，不得当 UP 原话

**用户指定学派时**：`按缠论看` → 只出 qing 视角 + 操作建议；`按鳄鱼派看` → 只出 gator 视角 + 操作建议（对应 `school_filter`）。
