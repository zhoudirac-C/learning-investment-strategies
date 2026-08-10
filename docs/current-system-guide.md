# 系统现状与使用指南（小白版）

> 建稿：2026-08-10。面向第一次接触本仓库的读者。
> 这份文档回答三个问题：**系统现在是什么样、我平时怎么用、每份数据从哪来**。
> 更深入的总设计见 `investment-learning-project/ai-stock-investment-plan.md`（下称「总计划」），
> 运维细节见 `docs/tasks/m-series-status-and-usage.md` 和 `docs/tasks/kline-daily-fetch-ops.md`。

## 0. 一句话理解这个系统

把一套人工投资方法论变成 **AI 自动执行 + 市场自动评分** 的系统：
AI 每个交易日收盘后独立判断市场阶段和方向（不看任何 UP 主观点），系统记录下来，
5 个交易日后用真实走势结算对错。攒够 8 周数据、达标就「毕业」——
证明 AI 学会的是方法而不是模仿某个人。

**当前阶段：影子双轨积累期**（总计划 M2 完成，M3 等数据）。系统每天自动跑，
你基本不用干预，只需要知道去哪里看结果。

## 1. 总计划 vs 当前进度

总计划（v2.1）是一条 M0→M5 的路线，当前状态：

| 里程碑 | 干什么 | 状态 | 产物在哪看 |
|---|---|---|---|
| M0 蒸馏+回测基建 | 把 UP 推理模式改写成来源中立、可验证的方法论；建 K 线缓存和回测 | ✅ | `framework/reasoning-patterns.yaml`（带 validation 区块）；回测结论 `logs/m0-acceptance.md` |
| M1 盲测 eval | 历史回放 71 天，AI 盲判 vs 市场真值 | ✅ | 基线报告 `logs/m1-baseline-20260808.md`：阶段一致率 66.2%（毕业线 70% 未达）、方向超额 61.1%（过 60% 线） |
| M2 影子双轨 | 每个交易日 AI 盲判 → 到期结算 → 判错归因 | ✅ 运行中 | 每日记录 `evals/shadow/predictions/`；完整性报告 `logs/shadow-status.md` |
| M3 前置 | 模式命中率回填（提案制：机器生成→人审→应用） | ✅ | `framework/proposals/` |
| M4 预备 | 毕业判分器（8 周窗口聚合） | ✅ | `logs/graduation-2026-08-09.md`（当前 verdict=insufficient_data，正常——数据不够） |
| M3 主体 | claims 分桶、evaluate_vs_market、研报管线扩容 | ⏳ 2026-09 初 | 等影子数据攒 ~4 周 |
| M4 本体 | 毕业后拆 prompt 里的 UP 实时锚定 | ⏳ 等毕业判决 | 连续 8 周达标才动 |
| M5 | 季度校准常态化 | ⏳ 毕业后 | — |

另有 2026-08-10 新增的 **KPL（开盘啦）数据接入**：每日拉打板情绪+产业资讯，属总计划
「数据底座」的扩容（补 M1 发现的「涨停池/情绪无缓存」缺口 + 产业链推导的新闻原料）。

## 2. 当前架构（一张图）

```
                        ┌─────────── 每天自动（本机 crontab）───────────┐
                        │ 15:35 拉K线 → 17:45 拉KPL → 18:05 影子盲判  │
                        └──────────────┬────────────────────────────────┘
                                       ▼
┌───────────────────────────── 数 据 源 ─────────────────────────────┐
│ 通达信TDX(主)/腾讯行情(备)   DeepSeek API        开盘啦KPL私有API      │
│  ·个股+指数日K              ·AI盲判的大脑        ·打板情绪/连板梯队     │
│                            （deepseek-chat）   ·产业资讯全文          │
└───────┬──────────────────────┬───────────────────────┬─────────────┘
        ▼                      ▼                       ▼
┌────────────────┐   ┌──────────────────────┐   ┌─────────────────────┐
│ K线缓存         │   │ 影子双轨引擎           │   │ KPL 落盘             │
│ kline_cache.db │──▶│ investment_engine/    │   │ infra/data/kpl/     │
│ 217只个股+2指数 │   │  shadow/（每日编排）   │   │  emotion/<日期>.json │
│ 2026-04-27 起  │   │  blindtest/（回放评分）│   │  news/<日期>/       │
└────────────────┘   └──────────┬───────────┘   └─────────────────────┘
                                ▼
                ┌──────────── 产 出（都在 git 里可回看）────────────┐
                │ evals/shadow/predictions/<日期>.json  每日盲判档案   │
                │ logs/shadow-status.md                 完整性报告    │
                │ logs/graduation-*.md                  毕业进度      │
                └──────────────────────────────────────────────────┘
```

图里没画但同样存在的两大件：

- **Qing-Agent 个股/市场分析体系**（`src/qing_investment/`，总计划的 v2.0 底子）：
  9 节点 LangGraph 工作流、监控规则引擎、复盘通道。它是「按需使用」的分析能力
  （通过 Hermes/技能触发），本机没有挂定时任务。M4 毕业改造的对象就是它的 prompt。
- **知识底座**：`knowledge/claims`（451 张观点卡）、`knowledge/industry-chains/`
  （产业链知识库）、`sources/raw/财经`（550 篇 UP 语料，现降级为教材/对照）、
  Neo4j + Qdrant（观点演化图与向量检索，同步流程见 `docs/neo4j-relation-pipeline.md`）。

## 3. 日常使用

### 每天（什么都不用做）

三条 cron 工作日自动跑（本机，详见 ops 文档）：

| 时刻 | 任务 | 日志 |
|---|---|---|
| 15:35 | 续拉 217 只个股 + 指数的日 K 线 | `log/pre_fetch_klines.log` |
| 17:45 | KPL：拉打板情绪快照 + 当日资讯全文 + 龙虎榜 | `log/kpl_daily_fetch.log` |
| 18:05 | 影子双轨：AI 盲判当日市场（数据包含 KPL 情绪/资讯标题/龙虎榜）→ 到期结算 → 归因 → 刷新报告 | `log/shadow_daily.log` |

### 收盘后想看结果（按这个顺序）

1. **`logs/shadow-status.md`** —— 总览：记录了几天、每天判对没有、有没有缺归因。
2. **`evals/shadow/predictions/<今天>.json`** —— 今天的盲判档案：
   - `result.market_stage` / `stage_reason`：AI 判的市场阶段和理由；
   - `result.scenarios[]` / `watch_next[]` / `invalidation[]`：情景分支、明日验证变量、
     失效条件（v2 契约新增，v1 老记录无此字段）；
   - `result.directions[]`：看好的 1-3 个方向（含标的代码、理由、`posture` 操作定性）；
   - `prompt_version`：`v1`/`v2`（2026-08-11 起 v2）；
   - `raw`：DeepSeek 返回的原文（未加工）；
   - `stage_hit`：阶段判对没有（次日真值出来后回填）；
   - `status`：`pending_maturity`=等 5 个交易日结算方向超额；`scored`=已结算。
3. **`infra/data/kpl/emotion/<今天>.json`** —— 打板情绪：涨停数、封板率、
   连板梯队、风口异动、板块榜（字段含义见 `docs/design/kpl-api-inventory.md` 第 1 节）。
4. **`infra/data/kpl/news/<今天>/`** —— 当日资讯：`index.json` 是目录，
   每篇一个 `.md`（frontmatter 带标题/时间/关联股票，正文纯文本）。
5. **`infra/data/kpl/lhb/<今天>.json`** —— 龙虎榜游资榜：披露日、分类席位、
   当日上榜明细（披露未出时 list 为空、note 有标注，属正常）。

注意：`infra/data/` 不进 git（数据文件太大），换机器看不到；想看历史趋势以
`evals/` 和 `logs/` 下的 git 记录为准。

### 每周五收盘后

```bash
.venv/bin/python scripts/graduation_check.py   # 看毕业进度（满 8 周才出有效判决）
```

### 出问题了怎么手动补跑

```bash
# 影子双轨补跑某天（幂等：当天已有有效记录就跳过，不会重复调 DeepSeek）
set -a && source .env && set +a && .venv/bin/python scripts/shadow_daily.py --date 2026-08-10

# KPL 补跑（幂等同理；--force 强制重拉）
set -a && source .env && set +a && .venv/bin/python scripts/kpl_daily_fetch.py --date 2026-08-10

# K线补拉
.venv/bin/python scripts/pre_fetch_klines.py
```

## 4. 数据源逐个说

### 4.1 行情 K 线 —— 通达信 TDX 为主，腾讯行情兜底

- **是什么**：217 只个股（watchlist+stock_pool）+ 沪深300/上证指数的日 K 线。
- **从哪来**：主通道是**通达信行情协议**（Python 库 `pytdx`，连券商公共行情服务器，
  免费）；连不上（如腾讯云机房常连不上 TDX）自动降级到**腾讯行情接口**
  （`web.ifzq.gtimg.cn`，免费公开接口）；指数只走腾讯接口。
- **存哪**：`infra/data/kline_cache.db`（SQLite，不进 git）。
- **谁维护**：cron 15:35 `scripts/pre_fetch_klines.py`；指数由 `shadow_daily.py` 自补。
- **断供征兆**：`log/pre_fetch_klines.log` 里失败率升高；两个通道都挂会明确报错，不会编数据。

### 4.2 AI 大脑 —— DeepSeek API

- **干什么用**：影子双轨每日盲判（`deepseek-chat`），以及 M1 历史回放（同款调用）。
- **怎么接**：`.env` 里的 `deepseek_api_key`（付费 API，按 token 计费；每天 1 次盲判，
  成本可忽略）。cron 通过 `source .env` 注入。
- **调用记录**：每次判断的原文存在预测 JSON 的 `raw` 字段；没有 token 用量统计（想加可以提）。
- **失效表现**：当天记录 `status=error`，次日重跑会自动覆盖重试；归因/报告照常。

### 4.3 打板情绪 + 产业资讯 —— 开盘啦 KPL（私有 API，2026-08-10 接入）

- **是什么**：`Index.GetInfo` 全量（涨停/封板率/连板梯队/二板/风口异动/板块榜/风向标）
  + 资讯列表与全文（产业新闻 → 产业链推导原料）。
- **从哪来**：**抓包自有账号的 App 流量得到的私有 HTTP API**（ mitmproxy/Reqable，
  协议与接口清单见 `docs/design/kpl-api-inventory.md`）。
- **凭据**：`.env` 的 `kpl_user_id` / `kpl_token` / `kpl_device_id`。
  token 寿命实测 ≥30h、上限未知；失效时脚本退出码 3、日志给重抓指引
  （按接口清单的 Reqable 流程重新抓包）。
- **风险**：私有 API 违反 App 用户协议，理论有封号风险；每天每类一次调用、频率等同
  正常用户，仅限个人研究。**token 与抓包文件永不进 git**（`temp/kpl_capture/` 已忽略）。
- **已知边界**：板块详情/题材库/异动提醒走证书固定的直连通道，用户级抓包拿不到
  （清单「第二条通道」节）；付费专栏条目全文返回 1130 无权限，自动跳过留痕。

### 4.4 实时行情/监控 —— 东财→新浪→缓存降级链

- **是什么**：Qing-Agent 监控与分析用的实时报价、板块数据。
- **从哪来**：东方财富接口为主，失败降级新浪，再失败用本地缓存，全挂则明确报错
  （链路与纪律见 `AGENTS.md` 第 4 条与 `skills/qing-stock-monitor-update.deprecated/references/data-source-fallback-chain.md`）。
- **本机状态**：按需使用（Hermes/技能触发分析时），本机无定时任务。

### 4.5 财报数据 —— akshare（东财源）

- **是什么**：个股财报/营收数据，产业链知识库的事实层供给之一。
- **从哪来**：`akshare` 库（聚合东财等公开财报数据，免费），脚本
  `scripts/fetch_financial_reports_cron.py`（带 0.3s/只 的限流间隔）。
- **本机状态**：**未挂 cron**（ops 文档有记录），需要时手动跑。

### 4.6 知识底座 —— 自有积累 + 公开语料

- `knowledge/claims/`（451 张观点卡）：早期从 UP 主内容逐字摘录，v2.1 起按来源分桶
  （up=教材 / agent=AI 自产 / research=研报 / announcement=公告 / data=量价回写）；
  同步进 Neo4j（观点演化图）+ Qdrant（向量检索），流程见 `docs/neo4j-relation-pipeline.md`。
- `knowledge/industry-chains/`：产业链知识库（环节/价值量/壁垒/格局/标的映射，
  schema 见 `src/investment_engine/industry_chain/schema.py`），由存量深度研究迁移 +
  事件驱动维护。
- `sources/raw/财经/`（550 篇 UP 视频转写稿）：现定位为**教材与对照标签**，不再当事实源。

## 5. 常见问题

- **cron 没跑/日志没更新**：先看 `log/` 对应日志；没有日志文件就看 `cat /var/mail/$USER`
  （cron 的错误进邮件）。2026-08-10 出过一次 macOS 收回 cron 读权限的事故（疑公司 MDM
  推送策略），修复与排查顺序写在 `docs/tasks/kline-daily-fetch-ops.md`「相关变更」。
- **KPL 报鉴权失败（退出码 3）**：token 过期，按
  `docs/design/kpl-api-inventory.md` 的 Reqable 流程重抓，更新 `.env` 三个 `kpl_*` 值。
- **换电脑/云部署**：需要 `.env`（deepseek_api_key、kpl_*）、`.venv`、
  以及按 ops 文档重建调度并注销本机 cron。
- **跑测试**：`.venv/bin/pytest tests/investment_engine -q`（引擎测试，当前 168 全绿）。
- **哪些东西不进 git**：`.env`（密钥）、`config/stock_monitor/positions.yaml`（持仓）、
  `infra/data/`（K线/KPL 数据）、`temp/kpl_capture/`（抓包，含 token）。
  提交前 `git status --short` 确认没误加。

## 6. 红线（任何时候有效）

- 系统**不接交易接口、不自动下单**；一切产出仅供研究，**不是投资建议**。
- 报告中不允许出现无条件买卖指令——必须带触发条件、失效条件和数据时间戳。
- 数据源全挂时的底线行为是明确报错，**禁止编造数据**（宁可没建议，不给错建议）。
