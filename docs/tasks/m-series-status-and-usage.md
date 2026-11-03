# M 系列里程碑状态与使用说明（2026-08-09 建）

> 用途：一页看清 M0~M5 的完成结论、数据资产现状、日常/按需工具用法与待触发事项。
> 详细 ops 义务见 `docs/tasks/kline-daily-fetch-ops.md`；各里程碑 spec/plan 见
> `docs/superpowers/specs|plans/2026-08-0*-*.md`。

## 里程碑结论

| 里程碑 | 状态 | 关键结论 |
|---|---|---|
| M0 蒸馏+回测基建 | ✅ 完成 | 10 框架来源中立改写 + validation 区块；K 线缓存 217 只（2026-04-27 起）；真实回测 1507 信号、5 日命中率 51.8%（`logs/m0-acceptance.md`） |
| M1 盲测 eval | ✅ 完成 | 基线：阶段一致率 66.2%（n=71，参考线 70%）、方向超额 61.1%（n=175，参考线 60%）、标的超额 56.6%（n=350）（`logs/m1-baseline-20260808.md`） |
| M2 影子双轨 | ✅ 机制完成 | 每日盲判→到期结算→归因→状态报告全链路；2026-08-07 首日 e2e 真实跑通；cron 已挂。机制完成不代表近期无缺报，运行缺口以 `logs/shadow-status.md` 为准 |
| M3 前置（patterns 回填） | ✅ 完成 | 5 个模式写入 M1 实测命中率 + 分环境段明细；technical_timing/operation_strategy 保持 M0 回测值 0.5182；3 个未使用模式保持 pending-m1；提案制机制（生成→人审→应用）落地（`framework/proposals/20260809-pattern-validation-m1.yaml`） |
| M4 预备（历史判分器） | ✅ 完成，转为可靠性参考 | 8 周窗口聚合工具保留。最近报告 `logs/graduation-2026-10-25.md` 为 `not_yet`：方向超额 40.9%（n=93），低于 60% 参考线；该历史结果不得改写为已通过。2026-11-02 起，判分结果不再是 M4 启动门禁 |
| M3 剩余 | ✅ 完成（2026-10-24） | 回写机制落地（`claim_direction` LLM 判向 1499 条 → `claim_outcome` 5 日 forward 结算 689 条 → `up_hit_profile` 画像 + evaluate_vs_market 出数）。存量口径：up 桶命中率 42.1%(n=518)；青枫浦上Q 总览 42.5%（stock-view 46.5%/market-cycle 37.3%/sector-theme 31.5%/operation 16.7%，以 logs/claims-vs-market-2026-10-24.md 为准）；鳄鱼派样本不足。109 条 pending_data 窗口到点重跑 settle 转终态。30 条判向人审错向 3.3%。这些 UP 结果此后只作历史基线 |
| M4 本体（多专家独立运行 + Qing-Agent 每日市场验证） | 🔄 2026-11-02 方向启动，工程待实施 | 不再等待连续 8 周达标；仅青枫浦上Q/qing 退出新增实时输入与每日差异对照，gator、观察池及双学派平权规则保留。实施项：prompt 拆 qing 实时锚定、专家视角与最终合成的分轨留痕、市场到期结算、每日完整性与滚动可靠性报告。设计见 `docs/superpowers/specs/2026-11-02-m4-independent-operation-design.md`；启动不等于可靠性已达标 |
| M5 校准常态化 | ⏳ M4 上线并积累样本后 | 季度分桶校准 + 产业链保鲜巡检；不再等待旧式毕业。巡检器已存在 `scripts/industry_chain_freshness_check.py`，已列入下方周五例行 |

## 数据资产现状

- **K 线缓存** `infra/data/kline_cache.db`：217 只个股 + 2 指数，覆盖 2026-04-27 起，靠每日 cron 续拉保持连续
- **涨停梯队** `infra/data/limit_pool/`：2026-07-27 起（东财涨停池历史仅保留约 1 个月，更早无法回填，2026-08-15 实测），cron 15:37 日更续接
- **研报/公告** `infra/data/research/{reports,notices}/`：东财公开源（report/list + 公告大全），2026-08-15 管线 v1 落地并回填 2026-04-27 起；研报元数据含 PDF 直链（`download_pdf` 按需下载）
- **盲测基线** `evals/blindtest/results.jsonl`：71 天（2026-04-27~08-07）历史回放，一次性产物
- **影子数据** `evals/shadow/predictions/`：历史与实验对照样本；旧判分器的数据源。新 M4 的每日验证对象是 Qing-Agent，不能把 shadow 成绩直接当作 Qing-Agent 可靠性
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
# 历史/滚动可靠性参考（不再决定 M4 能否启动；建议每周五收盘后跑一次）
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
.venv/bin/pytest tests/investment_engine -q          # 引擎测试（当前 275 passed）
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
| 每个交易日（M4 新链路上线后） | Qing-Agent 产生盘前/盘中/收盘判断 | 分轨冻结输出并核对数据时点；到期后市场结算；错误、缺失、未到期分别记录。该链路目前工程待实施，不得当作已有 cron |
| 每周五收盘后 | — | 跑 `graduation_check.py` 看历史/滚动参考指标 + `score_qing_review_vs_market.py --report` 刷新历史对比 + `industry_chain_freshness_check.py` 保鲜巡检 + `evaluate_vs_market.py --report` 分桶巡检；同时检查 `logs/shadow-status.md` 的缺报与归因。M4 上线后改看 Qing-Agent 每日完整性和滚动可靠性报告 |
| 2026-10-26 起（已到期） | 10-19~10-23 预测的 T+5 到期结算入窗 | 补跑到期结算并核对缺口；旧 `verdict` 仅作历史基线，不再作为 M4 启动条件 |
| 2026-11-02 起 | 青枫浦上Q/qing 不再提供新增动态，无需等待毕业判决 | 实施 M4：prompt 拆 qing 实时锚定，保留 gator 等多专家输入；Qing-Agent 专家视角与最终合成结果分轨留痕、市场结算接入、每日完整性与滚动可靠性报告；按新 spec 验收 |
| M4 上线并积累足够样本后 | 新链路验收通过且有可结算样本 | 启动 M5 季度校准 + 保鲜巡检；可靠性验证每日持续，不设一次性终点 |

## 当前分支与推送状态

- 全部工作在 `master`，**已与 origin 同步**（2026-08-10 推送）
- 云部署前需补：`.env`（deepseek_api_key + kpl_user_id/kpl_token/kpl_device_id）、hermes wrapper 架构、注销本机 cron
- 2026-08-10  cron EPERM 事故（疑 MDM 收回 ~/Documents 读权限）已通过「完全磁盘访问授权 /usr/sbin/cron」修复，排查顺序见 ops 文档
