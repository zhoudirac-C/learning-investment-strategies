# glmv-stock-analyst 工作流

本 skill 基于 vendored `glmv-stock-analyst`，保留以下流程：

1. 先搜索确认股票代码。
2. 运行 vendored `fetch_all.py` 获取数据和图表。
3. 读取 `summary.json` 和 `data.json`。
4. 亲自查看日 K 与分时图。
5. 搜索精准相关新闻和研报。
6. 写 `report.md`。
7. 用 vendored `md2html.py` 转为 HTML。
8. 用户需要时再导出 PDF。
