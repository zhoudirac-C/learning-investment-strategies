---
name: qing-stock-analysis
description: Use when the user asks to analyze an individual stock through the blogger framework, F10 fundamentals, GLM stock data workflow, stock reports, K-line review, or 个股分析.
---

# qing-stock-analysis

## 目标

基于 vendored `glmv-stock-analyst` 的真实数据采集和图表流程，叠加博主投资框架、历史 claims/cases 和 F10 基本面方法论，输出个股分析报告。

## 必读参考

1. `framework/stock-analysis-playbook.md`
2. `skills/qing-stock-analysis/references/glmv-stock-analyst-workflow.md`
3. `skills/qing-stock-analysis/references/f10-financial-analysis.md`
4. `skills/qing-stock-analysis/references/qing-stock-framework.md`
5. `skills/qing-stock-analysis/references/report-contract.md`

## 流程

1. 搜索确认股票代码和上市市场。
2. 调用 `skills/qing-stock-analysis/scripts/run_glm_fetch.py` 获取真实数据。
3. 读取 `summary.json`、`data.json` 并查看 K 线和分时图。
4. 搜索精准新闻、公告和研报。
5. 检索本地 `knowledge/claims`、`knowledge/wiki`、`knowledge/cases`。
6. 按博主框架判断市场、板块、个股地位。
7. 按 F10 方法论执行公司类型识别、报表质量、ROE/杜邦、现金流和估值方法选择。
8. 生成 `report.md`、`report.html` 和聊天窗口精简总结。

## 禁止事项

- 不编造价格、财务、新闻或博主观点。
- 不跳过看图步骤。
- 不把“买/卖”作为无条件结论。
- 缺字段时必须输出分析降级说明。
