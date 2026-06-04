# Trading Rules 迁移与维护指南

## 背景

2026-06-04 引入 `framework/trading-rules.md`，用于集中管理**可执行交易规则**（选股规则、买卖点、套利策略、风控线），与 `methodology/` 层的市场判断框架分离。

## 何时进 trading-rules.md

| 内容类型 | 去向 | 示例 |
|----------|------|------|
| 具体操作纪律（选股规则、买卖点条件、套利策略） | `framework/trading-rules.md` | 接力标的选择方法论、尾盘套利法 |
| 技术分析工具（K线形态、指标公式） | `framework/technical-analysis-framework.md` | 长红线定义、布林线用法 |
| 市场认知框架（周期判断、主线分析） | `framework/*.md`（如 market-cycle-framework.md） | 板块扩散三阶段 |
| 原理性方法论 | `methodology/*.md` | 技术分析原理、量价关系 |
| 知识库详情 | `knowledge/wiki/投资方法论/*.md` | 交易纪律详解、案例分析 |

## 迁移流程（已有内容从 wiki → trading-rules）

1. **在 trading-rules.md 中创建规则条目**：包含来源 claim、核心规则、执行步骤、案例、失败信号
2. **在 wiki 中替换为链接**：将原 wiki 中的完整内容替换为 `详见 [framework/trading-rules.md](../framework/trading-rules.md#锚点)`
3. **更新 claim 的 methodology_pages**：指向 `framework/trading-rules.md`
4. **更新 framework/README.md 索引**

## 新增规则流程

1. 从 raw 抽取 claim 时，判断是否为**可执行操作纪律**（有明确步骤、条件、阈值）
2. 若是，在 claim 的 `methodology_pages` 中预填 `framework/trading-rules.md`
3. 创建/更新 `framework/trading-rules.md`，添加新规则条目
4. 在相关 wiki 页面添加链接（不要重复写完整内容）
5. 更新 `framework/README.md` 索引

## 避免重复

- **wiki 层**：保留规则索引、claim 引用、案例简述
- **trading-rules.md**：保留完整执行步骤、条件表、失败信号
- 不要两层都写完整内容——wiki 链接到 trading-rules 即可
