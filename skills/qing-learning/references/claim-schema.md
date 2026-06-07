# Claim Schema

必填字段与枚举以 `src/qing_investment/claim_schema.py` 为准。每条 claim 必须包含来源、日期、类型、主题、原文证据、LLM 解释、置信度、分析深度（intensity）、状态和 links。

**intensity 字段**（2026-06-07 新增）：区分 UP 分析深度——`high`（专题分析/视频重点推荐）、`medium`（复盘提及/方向判断/默认）、`low`（盘中随口/转发）。个股查询时 low 不进入 prompt。
