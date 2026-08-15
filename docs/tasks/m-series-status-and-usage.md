# M 系列里程碑状态与使用说明（2026-08-09 建）

> 用途：一页看清 M0~M5 的完成结论、数据资产现状、日常/按需工具用法与待触发事项。
> 详细 ops 义务见 `docs/tasks/kline-daily-fetch-ops.md`；各里程碑 spec/plan 见
> `docs/superpowers/specs|plans/2026-08-0*-*.md`。

## 里程碑结论

| 里程碑 | 状态 | 关键结论 |
|---|---|---|
| M0 蒸馏+回测基建 | ✅ 完成 | 10 框架来源中立改写 + validation 区块；K 线缓存 217 只（2026-04-27 起）；真实回测 1507 信号、5 日命中率 51.8%（`logs/m0-acceptance.md`） |
| M1 盲测 eval | ✅ 完成 | 基线：阶段一致率 66.2%（n=71，毕业线 70% 未达）、方向超额 61.1%（n=175，达标线 60%）、标的超额 56.6%（n=350）（`logs/m1-baseline-20260808.md`） |
| M2 影子双轨 | ✅ 完成 | 每日盲判→到期结算→归因→状态报告全链路；2026-08-07 首日 e2e 真实跑通；cron 已挂 |
| M3 前置（patterns 回填） | ✅ 完成 | 5 个模式写入 M1 实测命中率 + 分环境段明细；technical_timing/operation_strategy 保持 M0 回测值 0.5182；3 个未使用模式保持 pending-m1；提案制机制（生成→人审→应用）落地（`framework/proposals/20260809-pattern-validation-m1.yaml`） |
| M4 预备（毕业判分器） | ✅ 完成 | 8 周窗口聚合判定可用；首期报告 verdict=insufficient_data（`logs/graduation-2026-08-09.md`） |
| M3 剩余（claims 分桶/evaluate_vs_market/UP 画像/研报管线） | ⏳ 等影子 ~4 周数据 | 预计 2026-09 初启动 |
| M4 本体（prompt 拆锚定） | ⏳ 等毕业判决 | 连续 8 周达标后才允许动 `src/qing_investment/agent/prompts/` |
| M5 校准常态化 | ⏳ 毕业后 | 季度分桶校准 + 产业链保鲜巡检（巡检器未写，可随时提前补） |

## 数据资产现状

- **K 线缓存** `infra/data/kline_cache.db`：217 只个股 + 2 指数，覆盖 2026-04-27 起，靠每日 cron 续拉保持连续
- **涨停梯队** `infra/data/limit_pool/`：2026-07-27 起（东财涨停池历史仅保留约 1 个月，更早无法回填，2026-08-15 实测），cron 15:37 日更续接
- **研报/公告** `infra/data/research/{reports,notices}/`：东财公开源（report/list + 公告大全），2026-08-15 管线 v1 落地并回填 2026-04-27 起；研报元数据含 PDF 直链（`download_pdf` 按需下载）
- **盲测基线** `evals/blindtest/results.jsonl`：71 天（2026-04-27~08-07）历史回放，一次性产物
- **影子数据** `evals/shadow/predictions/`：每日新增，毕业判定的数据源（当前 2 天）
- **推理模式库** `framework/reasoning-patterns.yaml`：validation 区块回填状态见上表 M3 前置

## 日常使用说明

### 自动运转（cron 已挂，无需干预）

```
35 15 * * 1-5  pre_fetch_klines   # K 线续拉
40 15 * * 1-5  shadow_daily       # 影子双轨日更（需 .env 里 deepseek_api_key）
45 15 * * 1-5  kpl_daily_fetch    # KPL 情绪+资讯（需 .env 里 kpl_user_id/kpl_token/kpl_device_id）
55 17 * * 1-5  kpl_news_digest    # KPL 资讯初调摘要（产业词+股票池过滤，公开无凭证）
10 18 * * 1-5  fetch_research_reports  # 东财研报/公告日更（公开源，无需凭证）
```

- 日志：`log/pre_fetch_klines.log`、`log/shadow_daily.log`、`log/kpl_daily_fetch.log`
- 运行态报告：`logs/shadow-status.md`（每日刷新，已入 git）
- **这三条是本机测试用，云部署后必须注销**——注销命令与义务见 `docs/tasks/kline-daily-fetch-ops.md`
- 小白向总览（架构/用法/数据源）：`docs/current-system-guide.md`

### 按需手动

```bash
# 毕业进度查询（建议每周五收盘后跑一次；数据满 8 周才出有效判决）
.venv/bin/python scripts/graduation_check.py

# 模式命中率回填（有新证据源时）：先生成提案 → 人工评审 → 应用
.venv/bin/python scripts/propose_pattern_validation.py
.venv/bin/python scripts/apply_pattern_proposal.py framework/proposals/<file>.yaml --dry-run   # 预览
.venv/bin/python scripts/apply_pattern_proposal.py framework/proposals/<file>.yaml           # 落库（幂等，重复跑全 SKIP）

# 手动补跑影子某日
.venv/bin/python scripts/shadow_daily.py --date 2026-08-07
```

### 测试与回归

```bash
.venv/bin/pytest tests/investment_engine -q          # 引擎测试（当前 153 passed）
PYTHONPATH=third_party/chanpy .venv/bin/pytest tests/ -q   # 全仓（当前 601 passed + 3 个已存在环境型失败）
```

已存在的环境型失败（基线，非回归）：`test_evaluate_agent_vs_up×2`、
`test_kimi_code_cli_short_output`。

### 操作纪律（本系列实证过的坑）

- pytest 退出码判断不要接管道后 `&&`（`| tail` 会吃掉退出码），用 `${PIPESTATUS[0]}` 或单独跑
- 提交前 `git status --short` 确认无 gitignored 文件；不用 `git add -f`
- 改 yaml 用 ruamel 且 `width=4096`（否则长行折叠污染 diff）

## 待触发事项时间表

| 时点 | 触发条件 | 动作 |
|---|---|---|
| 每周五收盘后 | — | 跑 `graduation_check.py` 看毕业进度 + `score_qing_review_vs_market.py --report` 刷新 qing 对比臂（logs/qing-vs-shadow-*.md） |
| 2026-09 初 | 影子满 ~4 周 | 启动主计划 M3 剩余项（claims 分桶、`evaluate_vs_market.py`、UP 命中率画像、研报管线扩容） |
| 2026-10 初 | 影子满 8 周 | 毕业判分首次有效判决；`graduated` 才进入 M4 |
| 毕业后 | verdict=graduated | M4 prompt 改造（拆 UP 实时锚定），evals 全绿才可合入 |
| M4 后 | — | M5 校准常态化（季度校准 + 保鲜巡检） |

## 当前分支与推送状态

- 全部工作在 `master`，**已与 origin 同步**（2026-08-10 推送）
- 云部署前需补：`.env`（deepseek_api_key + kpl_user_id/kpl_token/kpl_device_id）、hermes wrapper 架构、注销本机 cron
- 2026-08-10  cron EPERM 事故（疑 MDM 收回 ~/Documents 读权限）已通过「完全磁盘访问授权 /usr/sbin/cron」修复，排查顺序见 ops 文档
