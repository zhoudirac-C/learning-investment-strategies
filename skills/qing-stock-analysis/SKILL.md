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
7. `skills/qing-stock-analysis/references/qing-stock-framework.md`
8. `skills/qing-stock-analysis/references/report-contract.md`
9. `skills/qing-stock-analysis/references/prompt-persona-engineering.md` — **Prompt 人格工程与反保守改造**：从风控机器人到AI交易助手的完整改造方案。含独立人格文件模式、反保守自检指令、赔率思维强制框架、Context Builder claims注入架构、实施顺序与验收标准。当系统被诊断为\"太保守\"或\"只减仓不提醒买入\"时必读。
20. `skills/qing-stock-analysis/references/prompt-engineering-patterns.md` — **Prompt 工程模式库**：三步共振法（多指标整合结论）、数据使用边界声明（MACD仅用于大盘）、动作绑定价格、Markdown输出格式、Reviewer格式兼容、关键节点日志、价格区间偏离度保护。修改 prompt 前必读。
10. `src/qing_investment/stock_monitor.py` — 监控脚本源码，包含 CLI flag、去重逻辑、板块轮动计算、大模型分析上下文格式。** cron 极简微信提醒的模板定义在源码中（搜索 `format_agent_analysis_context` 和 `请按本项目 AGENTS.md`），无独立参考文件。**
8. `skills/qing-stock-analysis/references/realtime-quote-fetch.md` — **实时行情 curl 兜底**：当 Python 包不可用时，用 curl + 腾讯财经 API 获取 A 股实时行情
9. `skills/qing-stock-analysis/references/tencent-api-field-guide.md` — **腾讯财经 API 字段解析参考**：`qt.gtimg.cn` 返回字段的索引会随买卖盘深度漂移，必须用手动计算（最新-昨收）/昨收 或动态定位时间戳，禁止硬编码索引
10. `skills/qing-stock-analysis/references/watchlist-theme-recovery.md` — **观察池 themes 恢复操作手册**：当用户要求恢复历史上被替换/移除的 themes 时，按此手册执行 Git 历史溯源、字段精简和验证
10. `skills/qing-stock-analysis/references/watchlist-bulk-update-from-raw.md` — **从复盘文档批量更新观察池**：提取 raw 文档中的标的提及，去重后按主题分组追加到 watchlist.yaml 的完整流程
11. `skills/qing-stock-analysis/references/stock-monitor-internals.md` — **监控脚本内部机制与状态文件结构**：收盘监控复盘时排查提醒来源、去重逻辑、漏报原因的参考手册
12. `skills/qing-stock-analysis/references/stock-monitor-cli-behavior.md` — **监控脚本 CLI 行为与状态文件**：`--status`、`--daily-review-context`、`--live-analysis-context` 等命令的输出格式和用途
12. `skills/qing-stock-analysis/references/stock-monitor-source-internals.md` — **监控脚本源码级技术参考**：通过直接阅读 `stock_monitor.py` ~1800行源码提取的完整数据流
15. `skills/qing-stock-analysis/references/daily-review-cases.md` — **收盘监控复盘案例库**
16. `skills/qing-stock-analysis/references/morning-cron-observation-guide.md` — **早盘监控观察指南（2026-06-10 新增）**：当预运行脚本输出 `qing-agent fallback` 且需要执行早盘开盘定性分析时，本文件提供完整的数据流、关键验证点、板块联动交叉验证方法和典型案例。
16. `skills/qing-stock-analysis/references/index-etf-analysis-guide.md` — **指数/ETF买入分析指南**：当用户询问指数或ETF（如恒生科技、科创50）时使用，含时间窗口分析、ETF代码推荐、与个股分析的区别
17. `skills/qing-stock-analysis/references/qing-agent-lightweight.md` — **Qing-Agent零基础设施运行模式 + 索引故障排查手册**：LangGraph多智能体系统可在无Docker容器的情况下运行，含 Qdrant 本地文件模式实战部署（config/代码/UUID兼容）。覆盖架构概览、降级机制、启动流程、同步脚本。⚠️ **三大陷阱**：①fallback模型的 `.encode().tolist()` 返回1D list，不是2D batch；②ONNX Runtime 多线程在2核VM上 futex spin-lock 死锁（修：`intra_op_num_threads=1`）；③Qdrant 本地模式独占锁→索引前必须关 Agent。
18. `skills/qing-stock-analysis/references/holdings-direction-alignment-check.md` — **持仓方向与 UP 近期内容核对手册**：当用户问\"UP 是否提到我的持仓\"\"核对我的持仓方向\"时触发。扫描最近 2-3 天 UP 内容（视频/复盘/早盘/动态），逐只核对持仓是否被提及、UP 态度如何、语言强度评级。与\"持仓更新\"子任务区分：本流程不做盈亏计算，只做方向一致性评估。
19. `skills/qing-stock-analysis/references/claim-leakage-architecture-analysis.md` — **Claims 泄漏路径架构分析**：`/chat` 和 `/analyze/trigger` 两条路径中 claim 从 Neo4j/Qdrant 到 LLM prompt 的完整数据流。识别两处剩余泄漏风险（Neo4j 图遍历个股 claims、stock_analyst 全量传入），评估方案C（intensity 字段）的加固效果。修改检索链路或做 claims 质量评估前必读。
20. `skills/qing-stock-analysis/references/claim-intensity-system.md` — **Claim Intensity 系统完整文档**
21. 21. `skills/qing-stock-analysis/references/market-breadth-framework.md` — **UP四层大盘方法论 + 神奇九转 + 斐波那契时间窗口**：UP大盘分析四层结构 + 九转序列有效性规则 + 斐波那契时间窗口。Agent分析浮于表面时必读。：从UP源文档提取的大盘分析四层结构（全A趋势→三指数共振→多级别顶底→情绪验证）。Agent分析浮于表面时必读。：方案C实现。covering schema 层（VALID_INTENSITY）、数据回填规则（8条）、检索链路三层防护（Neo4j min_intensity / _apply_intensity_weight / prompt 分级标签）、验收方法。新增或修改 intensity 相关代码前必读。
21. `skills/qing-stock-analysis/references/claim-relation-discovery.md` — **Claim 关系发现（方案1+3）**：图遍历检索增强 + LLM 自动判断 claim 间 supersedes/contradicts/supplements 关系。covering `discover_claim_relations.py` 脚本用法。
22. `skills/qing-stock-analysis/references/knowledge-base-direct-query.md` — **对话 Agent 直连 Qdrant + Neo4j**：从对话中语义搜索 claims/wiki（Qdrant 本地模式 BGE-small-zh-v1.5 ONNX）和图遍历查询（Neo4j Cypher）。当需要超越 grep 的语义检索时使用。
22. `references/index-multi-tf-kline.md` — **指数多级别K线 + MACD/九转/斐波那契 数据层**：含数据管线架构（东方财富→SQLite→kline_cache.py→nodes.py注入→prompt）、⚠️ **MACD使用边界**（仅用于大盘全A/上证顶底判断，个股禁用，不独立成段）、各函数用法、Cron配置、Prompt文件链接。Agent 做顶底结构判断前必读。
23. `skills/qing-stock-analysis/references/reading-up-fables-and-analogies.md` — **UP寓言/比喻类动态解读方法**：核心信息在「第一句」不在寓言细节。