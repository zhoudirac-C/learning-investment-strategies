# M2 影子双轨设计：每日盲判 + 收盘差异归因 + 归因四型回写

> 对应 v2.1 方案第十节 10.3 与第十四节 M2 里程碑。前置：M0（方法论底座）、M1（盲测回放基建与基线报告）已合入 master。
> 验收口径：连续 4 周归因记录完整，数据缺/步骤缺类问题有闭环。**本 spec 交付管线与机制；4 周记录靠 cron 每日累积。**

## 关键决策（已与用户对齐）

| 决策点 | 结论 |
|---|---|
| 每日节奏 | 收盘后（15:40，K 线落库后）判当日 + 前瞻 5 日：阶段项当日评分，方向/标的项 T+5 交易日回填 |
| 归因执行方 | DeepSeek 归因分类器（仅判错日触发），人工定期抽查 |
| 回写形态 | 提案制：处置建议落盘 `framework/proposals/`，人工确认后回写，status 流转闭环 |
| 运行环境 | 本机 cron 先跑（云部署后迁移，注销义务见 `docs/tasks/kline-daily-fetch-ops.md`） |
| 代码形态 | 新建 `investment_engine/shadow/` 子包，薄封装复用 M1 `blindtest`（dataset/replay/score/truth） |

## 架构

```
src/investment_engine/shadow/
├── __init__.py
├── daily.py      # 每日编排：判→评→归因（cron 入口调它，也可手动补跑某日）
├── predict.py    # 盲判：build_daily_pack → DeepSeek → 当日 prediction 落盘
├── maturity.py   # 到期回填：T+5 交易日后给方向/标的补超额评分
├── attribute.py  # 归因分类器：判错日 → 四型分类 + 处置建议 → proposals/
└── status.py     # 完整性报告：4 周日历 + 提案 open/closed 统计
scripts/shadow_daily.py   # cron 入口（自含指数新鲜度检查）
```

与生产 monitor 完全隔离：独立目录、零共享状态、不改 `src/qing_investment/`。

## 每日流程（15:40 cron）

1. **自检**：今日无新 K 线（节假日/拉取失败）→ 记日志退出 0；今日已有 prediction → 跳过（幂等）；
2. **盲判**：`blindtest.dataset.build_daily_pack(today)`（防泄漏断言照旧）→ DeepSeek（M1 同一 JSON 契约：market_stage/directions/used_patterns）→ `evals/shadow/predictions/<date>.json`；
3. **当日评分**：阶段判定 vs 当日真值标签（`blindtest.truth`，指数日 K 当日已落库）→ `stage_hit` 写入当日记录；
4. **到期回填**：取 5 个交易日前的 prediction，用 `blindtest.score` 补方向/标的超额评分，写回该日记录 `due_scores`；
5. **归因**：阶段判错（stage_hit=False）或到期后方向超额 ≤0 的日子 → DeepSeek 归因分类器 → 归因记录 + 处置提案。

## 产物与格式

```
evals/shadow/predictions/2026-08-10.json
  {"date", "result": {...}, "stage_hit": true/false,
   "due_scores": {"directions": {...}, "stocks": {...}} | null, "status": "scored|pending_maturity"}
evals/shadow/attributions/2026-08-10.json
  {"date", "trigger": "stage_miss|direction_miss", "types": [...], "analysis": "...",
   "proposal_refs": ["framework/proposals/...md"]}
framework/proposals/<date>-<type>-<slug>.md
  front-matter: {date, type: data-channel|pattern-patch|glossary-patch|capability-boundary,
                 status: open|applied|rejected, source: <attribution 路径>}
logs/shadow-status.md   # status.py 重新生成：4 周日历 + 提案统计
```

## 归因分类器

输入：AI 结论（阶段/方向/used_patterns/stage_reason）+ 真值与到期超额结果 + 当日数据在场/缺席清单（已知缺口：板块资金流/涨停池/涨跌家数）。强制 JSON 输出：

```json
{"types": ["数据缺", "步骤缺", "概念误用", "信息差"],
 "analysis": "错因分析（引用具体数据项）",
 "proposals": [{"type": "data-channel|pattern-patch|glossary-patch|capability-boundary",
                "title": "…", "action": "…"}]}
```

四型 → 提案类型映射：数据缺→data-channel；步骤缺→pattern-patch；概念误用→glossary-patch；信息差→capability-boundary。全对日记"无归因"，不产生 attribution 文件（status 日历记绿）。

**闭环定义**：提案 status 从 open → applied/rejected 流转；status 报告把数据缺/步骤缺类 open 提案置顶。人工确认后由 agent 在会话内执行回写并改 status。

## cron 与运行

本机 crontab 追加（注销义务延续 ops 文档）：

```
40 15 * * 1-5  cd <repo> && set -a && source .env && set +a && .venv/bin/python scripts/shadow_daily.py >> log/shadow_daily.log 2>&1
```

`shadow_daily.py` 自含：先调 `fetch_index_klines.fetch_index_tencent` 补当日指数 K → `shadow.daily.run(today)`。手动补跑：`python scripts/shadow_daily.py --date 2026-08-07`。

运营节奏：每周五由 agent 会话跑 `status.py` 出完整性小结；open 提案人工过一遍。

## 错误处理

- DeepSeek 失败：prediction 记 `status: error`，次日重跑（幂等跳过已完成日）；
- K 线/指数未就绪（如 15:40 时 15:35 的拉取尚未完成）：每 2 分钟重查一次、最多 3 次，仍无新数据则记日志退出 0（节假日由此自然跳过；连续缺失会在 status 周报暴露）；
- 归因分类器 JSON 非法：记 `attribute_error`，当日归因留待手动补；
- API key 缺失 fail-fast（读 `.env` 小写 `deepseek_api_key` 兼容，同 M1）。

## 测试

TDD（先测后实现，测试代码在计划任务中给出）：

- `test_predict.py`：mock DeepSeek，落盘格式 + 同日幂等跳过；
- `test_maturity.py`：合成 K 线 + 合成 prediction，T+5 回填与未到期跳过；
- `test_attribute.py`：mock 分类器输出 → 归因记录 + proposal 文件 + front-matter 正确；
- `test_status.py`：合成目录 → 完整性矩阵与提案统计正确；
- `test_daily.py`：编排（节假日退出/幂等/正常流转，全 mock）；
- e2e：对缓存最近交易日手动跑一次 `shadow_daily.py`（真实 API）。
- 惯例：tests 无 `__init__.py`，`.venv/bin/pytest`。

## 边界（M2 不做）

- UP 每日对照（M1 已建诊断口径，毕业判分 M4 再扩展）；
- `prompts/` 改造（M4）；自动回写（提案制人工确认）；
- 盘前预测（本期只要收盘后节奏）；
- 4 周记录属运行期产出，不在本次代码交付内。
