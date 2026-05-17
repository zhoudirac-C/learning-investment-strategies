---
name: qing-stock-analysis
description: Use when the user asks to analyze an individual stock through the blogger framework, F10 fundamentals, GLM stock data workflow, stock reports, K-line review, or 个股分析.
---

# qing-stock-analysis

## 目标

基于 vendored `glmv-stock-analyst` 的真实数据采集和图表流程，叠加博主投资框架、历史 claims/cases 和 F10 基本面方法论，输出个股分析报告。

## 必读参考

1. `framework/stock-analysis-playbook.md`
2. `skills/qing-stock-analysis/references/data-source-strategy.md`
3. `skills/qing-stock-analysis/references/glmv-stock-analyst-workflow.md`
4. `skills/qing-stock-analysis/references/f10-financial-analysis.md`
5. `skills/qing-stock-analysis/references/qing-stock-framework.md`
6. `skills/qing-stock-analysis/references/report-contract.md`

## 流程

1. 搜索确认股票代码和上市市场。
2. 按 `data-source-strategy.md` 选择数据源：优先使用当前运行环境原生金融/股票/经济数据库能力；若不可用或数据不完整，再调用 `skills/qing-stock-analysis/scripts/run_glm_fetch.py`。
3. 统一记录数据来源、查询时间、数据日期、缺失字段和可信度；不能把模型记忆当作行情数据。
4. 读取结构化数据，并查看 K 线和分时图；若原生工具未提供可视化图表，使用本地脚本补图。
5. 搜索精准新闻、公告和研报。
6. 检索本地 `knowledge/claims`、`knowledge/wiki`、`knowledge/cases`。
7. 按博主框架判断市场、板块、个股地位。
8. 按 F10 方法论执行公司类型识别、报表质量、ROE/杜邦、现金流和估值方法选择。
9. 生成 `report.md`、`report.html` 和聊天窗口精简总结。

## 禁止事项

- 不编造价格、财务、新闻或博主观点。
- 不假设任何运行环境的金融数据工具名称固定；由当前模型自行识别可用原生工具。
- 不跳过看图步骤。
- 不把“买/卖”作为无条件结论。
- 缺字段时必须输出分析降级说明。
