# 早盘分析链路修复与信息源扩容 spec

日期：2026-08-11
状态：done（2026-08-11 实施完毕，验收见 plan 执行记录；云端 agent 重启由同步管线负责）
归因来源：2026-08-11 早盘三方对照（UP 09:06 早盘文 vs qing-agent 5 次输出 vs 上午实际盘面）

## 背景与归因摘要

2026-08-11 早盘，qing-agent 跑了 5 次分析（09:26/09:50/10:21/10:38/11:21），其中 3 次
因 `market_summary` 节点 LLM 子调用失败（fallback 返回 `market_phase="未配置"`）而整体
摆烂成"数据缺失"——但 sentiment/外部板块榜等原始数据**明明在请求体里**，失败时下游
完全用不上。同时对照 UP 早盘文，系统缺隔夜外盘、竞价、涨停梯队等信息源，以及
外盘映射、量能结构读法等推理模式。

## 范围与顺序

### P0-1 market_summary 可靠性（`src/qing_investment/agent/graph/nodes.py`）

1. fallback 区分真实原因：`llm_empty`（LLM 空返回/超时/限流）/ `json_parse_error` /
   `prompt_too_large`（已有），写入 `result["_fallback_reason"]` 和 reasoning_steps。
2. **降级数据填充**：fallback 时用纯规则拼装 `market_summary` 文本（指数涨跌、量能、
   sentiment 涨停/跌停/连板/炸板率/涨跌家数、外部板块榜 concept/industry 各 top5），
   `emotion_signals` 填 sentiment 原值。**约束**：`market_phase` 保持 `"未配置"`
   （daily_state 持久化守卫 `nodes.py:373` 不动）、`main_themes` 保持 `[]`
   （避免污染 direction_priority）。
3. `_render_market_summary_text` 的 summary 截断 200→500 字符（让降级摘要完整下传）。
4. LLM 空返回时**重试一次**（仅 market_summary 节点，不动 `_safe_llm_invoke` 公共行为）。
5. 不做：prompt 瘦身（先观察重试+降级后的失败率，一周后复盘再定）。

### P0-2 日期硬约束

1. market_summary context 注入 `today`（YYYY-MM-DD 星期X）。
2. style_writer prompt 注入当前日期（消除"分析时间：2025年5月16日"类幻觉）。
3. `prompts/system/reviewer.txt` 加日期一致性检查规则。

### P1-1 隔夜外盘映射

- 新 config `config/stock_monitor/us_map.yaml`：板块→美股映射股清单
  （光模块 COHR/LITE/FNVR、算力 NVDA/AMD/AVGO、医药 LLY/NVO、网安 PANW/CRWD 等，
  含 hand-maintained `earnings_note` 财报备注字段）。
- 新模块 `src/investment_engine/overnight_us.py`：东财 push2 美股行情
  （secid 105/106/107 前缀，实现时实测验证），盘前拉取落盘
  `infra/data/overnight_us/<date>.json`。
- 新脚本 `scripts/overnight_us_fetch.py`，cron 工作日 08:20。
- 接入：`hermes_stock_monitor_agent.py::_build_market_snapshot` 读当日文件 →
  `market_snapshot["overnight_us"]`（块内标注数据日期=昨夜美股收盘日）。

### P1-3 涨停梯队明细

- 新模块 `src/investment_engine/limit_pool.py`：东财 push2ex 涨停池/炸板池
  （`getTopicZTPool`/`getTopicZBPool`，date 参数支持历史），落盘
  `infra/data/limit_pool/<date>.json`：涨停名单（连板数/封单额/炸板次数）+ 炸板名单 +
  衍生指标（梯队分布、晋级率=今连板÷昨首板、反包=昨炸板∩今涨停）。
- 新脚本 `scripts/limit_pool_fetch.py`，cron 工作日 15:37（收盘后，随 pre_fetch 档）。
- 接入：① 盲判包 `dataset.py` 加 `limit_pool` 块（昨日梯队，18:05 用）；
  ② `_build_market_snapshot` 加 `limit_pool_yesterday`（早盘用昨日数据）。

### P1-2 集合竞价（v1 收敛）

不加新接口。09:26 快照 quotes 已含竞价成交价/额；v1 用纯规则从快照标记
一字/准一字（open≈涨停价）与竞价额 top 名单，接入 `_build_market_snapshot`
产出 `auction_digest`。预估全天成交额算法（KPL 式）留 v2。

### P2-1 模式库补齐（提案制，走 framework/proposals/）

6 个模式各写一份提案（证据引 `sources/raw/财经/` 历史复盘 + 2026-08-11 早盘文）：
外盘映射定价权、量能结构读法、预期打满→只剩兑现、分歧-缩量-再放量三段式、
一字定方向、尾盘抢筹分支选择。遵守模式治理 v2.1（≥4 周窗口+跨 regime 证据）。

### P2-2 停牌/盘后公告要点

v1 不加公告接口：`_build_market_snapshot` 从昨日 KPL 资讯
（`infra/data/kpl/news/<昨>/index.json`）按关键词（停牌/核查/立案/处罚/复牌）
过滤产出 `post_close_alerts`。爱丽家居二进宫类事件盘后出，正好覆盖。

### P3 早盘归因固化

- `evals/morning/` 目录约定 + 今日归因存档 `evals/morning/attributions/2026-08-11.md`。
- 流程写入文档：每日傍晚对照（UP 早盘框架 vs 系统输出 vs 实际盘面）。

## 工程约束

- 改 `nodes.py` 后重启本地 uvicorn（`log/agent.pid`），按
  `src/qing_investment/agent/AGENTS.md` checklist 跑 `pytest tests/test_stock_monitor.py`。
- 本轮已获用户授权修改 `src/qing_investment/`（仅限本 spec 列出的点）。
- 新模块测试全 fake HTTP；cron 改动前备份 crontab。
- 逐任务 commit，不 push（等用户指令）。

## 验收

1. P0：构造 LLM 失败/错 JSON 场景单测，fallback 带 `_fallback_reason` 且
   market_summary 含真实情绪/板块数据；14:00 实盘 cron 输出不再整体摆烂。
2. P0-2：输出不再出现错误日期；reviewer 规则生效。
3. P1-1：08:20 拉取落盘，09:26 请求体含 `overnight_us`。
4. P1-3：15:37 落盘含梯队/晋级率/反包；盲判包与早盘快照可见。
5. P1-2/P2-2：09:26 请求体含 `auction_digest` / `post_close_alerts`。
6. 全量 pytest 绿。
