# learning-investment-strategies

持续学习型投资方法论系统，用来长期学习财经博主的投资框架，并把学习结果沉淀成可复用的 Agent Skills、知识库与实时分析能力。

这个项目**不是自动交易系统**，也**不是一次性的投研报告生成器**。它的核心是四层能力：
1. **学习层**：把原始 UP 内容保存下来，逐步抽取观点、案例和方法论
2. **知识层**：将学习结果结构化存入 Neo4j（claims 图谱）、Qdrant（文档向量）、mem0（长期记忆）
3. **推理层**：从 UP 原文抽取推理模式（\"怎么推理\"而非\"什么观点\"），116 条推理链注入 Agent prompt
4. **分析层**：Qing-Agent 基于 LangGraph 工作流，按 UP 的推理模式分析行情并输出条件化操作建议

---

## 当前状态

- 默认分支：`master`
- 保留开发分支：`feature-continuous-learning-system-build`
- 已迁移旧项目中的 UP 原始数据：`sources/raw/财经` 下 540+ 篇 Markdown 原稿
- 已包含 **4 个核心 skill**：`qing-learning`、`qing-methodology-review`、`qing-stock-analysis`、`qing-stock-monitor-update`
- 已接入 F10 基本面分析方法论，并 vendor 了 `glmv-stock-analyst` 作为个股数据分析底座
- **Qing-Agent**（`src/qing_investment/agent/`）已上线：LangGraph 7 节点工作流 + FastAPI 服务，支持每日复盘、持仓操作建议、板块维度分析
- **知识检索三阶段升级**（2026-06）：
  - Phase 1 — 打通「能读到」：framework 文件加入向量索引，Agent 显式加载方法论框架
  - Phase 2 — 升级「读得准」：ONNX Runtime + `bge-small-zh-v1.5` 本地语义嵌入（512维），替代 hash 嵌入
  - Phase 3 — 做到「说得清来源」：来源类型 boost 排序、输出强制标注引用来源、reviewer citation 检查（最多3次打回）
  - Phase 4 — 模仿「怎么推理」：从 479 篇 raw 中抽取 116 条推理模式（reasoning-patterns.yaml），IDF 加权倒排索引匹配，注入 market_analyst prompt，让 Agent 按 UP 的推理步骤思考

---

## 项目结构

```text
sources/
  raw/              原始 UP 内容，原则上不改写（540+ 篇）
  incoming/         新增内容暂存区
  processed-log.md  已学习原稿记录

knowledge/
  claims/           原子观点与证据（~505 条已入库 Neo4j）
  wiki/             结构化知识库
  cases/            历史案例与回归样本

methodology/        长期方法论沉淀（F10、板块轮动、仓位风控、技术分析等）
framework/          可执行分析流程与输出契约（8 个 playbook + reasoning-patterns.yaml）
  reasoning-patterns.yaml  推理模式库（116 条 UP 推理链，IDF 加权倒排索引匹配）

config/stock_monitor/   行情监控配置
  watchlist.yaml        观察池（公共）
  positions.yaml        当前持仓（gitignore）
  positions.example.yaml 持仓模板
  strategy_pack.yaml    监控规则包（指数纪律、板块轮动、日内时间表）

src/qing_investment/
  agent/            Qing-Agent 分析大脑（LangGraph + FastAPI）
    graph/          7 节点工作流（parse_query → retrieve_knowledge → market_analyst → stock_analyst → synthesize → style_writer → reviewer）
    tools/          外部板块数据、Neo4j/Qdrant/mem0 客户端、LLM 封装
    prompts/        System prompt（market_analyst、style_writer、reviewer 等）
  stock_monitor.py  Hermes 行情监控核心（~1945 行）

scripts/            迁移、索引、lint、扫描、Bilibili 抓取、Hermes 包装脚本、推理模式抽取
  extract_reasoning_patterns.py  从 raw 文件批量抽取推理模式（--dry-run / --single / --incremental）
skills/             4 个 Agent Skills
  qing-learning/
  qing-methodology-review/
  qing-stock-analysis/
  qing-stock-monitor-update/

evals/              回归验证样例
reports/            生成的复盘报告
tests/              pytest 自动化测试（13 个测试文件）
infra/data/         本地数据卷（local_memories.json 等）
docs/               技术设计文档、深度研报、每日复盘
```

---

## 快速启动

### 1. 依赖容器（必须提前启动）

```bash
# Neo4j（claims 图数据库）+ Qdrant（文档向量）+ Postgres（mem0）
docker-compose -f docker-compose.infra.yml up -d
```

### 2. 环境变量

```bash
export LLM_PROVIDER=deepseek           # 或 kimi
export DEEPSEEK_API_KEY=sk-xxx
export KIMI_API_KEY=sk-xxx             # 若使用 kimi

export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=qingneo4j

export QDRANT_HOST=localhost
export QDRANT_PORT=6333
```

### 3. 启动 Qing-Agent

```bash
uv run uvicorn qing_investment.agent.main:app --host 127.0.0.1 --port 8000
```

健康检查：`curl http://127.0.0.1:8000/health`

### 4. 启动行情监控

```bash
# 查看监控状态
.venv/bin/python src/qing_investment/stock_monitor.py --status

# 测试通知
.venv/bin/python src/qing_investment/stock_monitor.py --smoke

# 每日复盘上下文
.venv/bin/python src/qing_investment/stock_monitor.py --daily-review-context
```

---

## Qing-Agent 架构

Qing-Agent 是项目的**分析大脑**，基于 LangGraph 构建有向图工作流。

完整架构图：`docs/qing-agent-technical-design.md` → 第 2 章「整体架构」（内嵌 PlantUML）

**简化数据流：**
```
parse_query → retrieve_knowledge ──┬── market_analyst ──┐
                                   └── stock_analyst ───┼── synthesize → style_writer → reviewer → END
```

| 节点 | 职责 | 关键输出 |
|------|------|---------|
| `parse_query` | 意图解析（stock/market/portfolio） | `parsed_intent` JSON |
| `retrieve_knowledge` | 从 Neo4j/Qdrant/mem0 检索知识 | claims + wiki + memories |
| `market_analyst` | 大盘/板块分析（强制 JSON），显式加载 framework 文件 + 推理模式匹配（IDF 加权倒排索引） + 动态分析框架片段 | `market_context` |
| `stock_analyst` | 个股地位、多空证据 | `stock_analysis` |
| `synthesize` | 草稿合成（含持仓操作计划），注入【参考来源】 | `draft_analysis` |
| `style_writer` | UP 口吻风格化，强制保留来源标注 | `styled_output` |
| `reviewer` | 事实核查、禁用词检测、citation 缺失检查（最多3次打回） | `review_passed` |

### API 端点

| 端点 | 用途 |
|------|------|
| `GET /health` | 健康检查 |
| `POST /analyze/trigger` | **Hermes 调用** — 接收行情快照、持仓、板块数据，返回 UP 风格复盘 |
| `POST /chat` | 用户对话（带记忆检索） |
| `POST /memory/add` | 追加用户记忆（mem0 或本地 JSON fallback） |

### 板块数据双规架构

- **内部样本**（`sector_strengths`）：基于 `config/stock_monitor/strategy_pack.yaml` 中的 `sector_groups`，样本量小（10+ 只成分股），只作持仓个股参考
- **外部全量**（`external_sector_boards`）：东方财富概念/行业板块为主源，新浪板块为备源，带指数退避重试 + 级联降级
- **数据不可用守卫**：market/portfolio 分析时若外部数据失败，直接返回 `"数据不可用"`，**不让 LLM 虚空编造板块涨跌**

### 持仓操作建议

每日复盘（`market`/`portfolio` 分析）自动包含【持仓操作计划】：
- 触发条件（如"板块联动且站稳 19 元"）
- 失效条件（如"跌破 18.5 元且 30 分钟不收回应减仓"）
- 仓位控制建议（使用具体价格位）

---

## 数据基础设施

| 服务 | 端口 | 用途 | 内容规模 |
|------|------|------|---------|
| **Neo4j** | 7474/7687 | Claims 图数据库 | ~505 claims，节点：Claim/Stock/Sector/Source |
| **Qdrant** | 6333 | 文档向量检索 | `qing_knowledge`：557 文件 → 10,685 chunks；`qing_claims`：511 claims（语义搜索） |
| **Postgres** | 5432 | mem0 存储后端 | 长期记忆 |
| **Local JSON** | — | `infra/data/local_memories.json` | 63 条本地记忆 fallback |

### 知识库同步（增量）

新增 raw 文档或 claim 后，**不需要全量重跑**：

```bash
# 增量同步文档到 Qdrant（只处理新/修改的文件）
.venv/bin/python scripts/index_documents_to_qdrant.py

# 增量同步 claims 到 Neo4j（图关系）
.venv/bin/python scripts/migrate_claims_to_neo4j.py

# 增量同步 claims embedding 到 Qdrant（语义搜索）
.venv/bin/python scripts/index_claims_to_qdrant.py
```

状态文件自动创建：`.index_state.json`、`.migrate_state.json`

强制全量重跑：`--force-full`

### 知识库时效性机制（2026-06 新增）

Agent 不是简单地"全读本地知识"，而是有多层时效性过滤：

| 机制 | 实现位置 | 效果 |
|------|----------|------|
| **Claims 时效衰减** | `retrieve_knowledge` | ≤7 天标 `[最新]`，31-90 天标 `[近期]` 并降权，>90 天或 superseded **直接过滤** |
| **Prompt 时效自检** | `market_analyst.txt` | Agent 被强制要求：标注 claim 时效、处理 framework 与实时数据矛盾、列出同一主题相反观点 |
| **同一主题矛盾检测** | `retrieve_knowledge` | 按 `subject` 分组，用方向词表检测同一主题下的相反 active claims，注入 `potential_conflicts` |
| **Wiki 时间戳** | `index_documents_to_qdrant.py` | 每个 wiki chunk 携带 `source_date`，Agent 知道知识是哪天的 |
| **外部标的校验** | `stock_analyst` | DuckDuckGo 搜索个股主营业务，与 claims 描述对比，不一致时标注 |

### 每日 Freshness Check

```bash
# 检查未处理 raw 文档、陈旧 short-term claims、最新 claim 日期
.venv/bin/python scripts/freshness_check.py

# 或集成到 stock_monitor
.venv/bin/python src/qing_investment/stock_monitor.py --freshness-check
```

输出示例：
```
=== Freshness Check 2026-06-05 ===
✅ 最新 claims: 2026-06-05 (今天)
✅ 最近 3 天的 raw 已全部处理
✅ 无超过 7 天的 stale short-term claims
```

---

## 行情监控（Hermes 集成）

`src/qing_investment/stock_monitor.py` 负责 A 股日内监控，Python 做机械工作，Agent 只在触发时介入。

### 监控阶段

1. **规则引擎**：指数纪律（4033/4130）、持仓减仓区/风控线、板块轮动阈值
2. **板块强度计算**：进攻 vs 防御风格切换观察
3. **状态持久化**：JSON state（alert 指纹去重、板块连续信号、最后市场状态）
4. **Agent 触发分析**：7 个固定时间点（09:26 集合竞价后、09:45 开盘确认、…、14:50 尾盘条件单）+ 新规则信号触发
5. **收盘复盘**：从 `state.json` 生成当日监控质量回顾

### 配置说明

见 `config/stock_monitor/README.md`，包含：
- YAML 字段契约
- Hermes cron 配置示例
- 每日复盘接入说明

---

## 四个核心 Skills

### qing-learning

- **用途**：学习新增 UP 原稿，抽取 claims，更新 wiki/methodology/framework
- **位置**：`skills/qing-learning/SKILL.md`
- **适合问题**：`学习 sources/incoming 里的新内容`、`把这篇早盘抽成 claim 和案例`

### qing-methodology-review

- **用途**：对比近期内容与既有方法论，识别矛盾、过期观点、权重变化
- **位置**：`skills/qing-methodology-review/SKILL.md`
- **适合问题**：`复盘最近一周博主框架是否发生变化`、`检查 CPO 主线判断是否和旧规则冲突`

### qing-stock-analysis

- **用途**：基于 GLM 数据底座 + F10 财务分析 + 博主框架，分析个股
- **位置**：`skills/qing-stock-analysis/SKILL.md`
- **适合问题**：`按博主框架分析一只股票`、`结合 F10 方法论检查基本面`

### qing-stock-monitor-update

- **用途**：根据实时数据和博主观点，更新 watchlist/strategy_pack/positions
- **位置**：`skills/qing-stock-monitor-update/SKILL.md`
- **包含**：全市场技术扫描脚本 `scripts/scan_all_stocks.py`

---

## 日常学习流程

1. 把新的 UP 原稿放入 `sources/incoming/`，确认文件名包含日期、类型和标题。
2. 使用 `qing-learning` 读取新增原稿，抽取 claim、更新 wiki、补充 methodology 和 framework。
3. 将已学习的原稿路径写入 `sources/processed-log.md`。
4. 同步知识库（三个脚本缺一不可）：
   ```bash
   .venv/bin/python scripts/index_documents_to_qdrant.py
   .venv/bin/python scripts/migrate_claims_to_neo4j.py
   .venv/bin/python scripts/index_claims_to_qdrant.py
   ```
5. 运行索引和 lint：
   ```bash
   uv run python scripts/build_indexes.py
   uv run python scripts/lint_knowledge.py
   ```
6. 对关键方法论变化使用 `qing-methodology-review` 做复盘。

---

## Bilibili 内容管道

用于抓取博主 B 站动态和视频：

```bash
# QR 登录（保存 SESSDATA）
.venv/bin/python scripts/bilibili_qr_login.py

# 抓取动态/视频/专栏（含图片 OCR、评论提取）
.venv/bin/python scripts/fetch_bilibili_up_v2.py

# 检查新内容并通知
.venv/bin/python scripts/bilibili_notify.py
```

---

## 历史数据迁移

递归发现旧项目中的 UP 原始数据目录，迁移到 `sources/raw/<module>/...`：

```bash
.venv/bin/python scripts/migrate_legacy_up_raw.py /path/to/legacy/wiki
```

迁移结果写入 `migration/legacy-manifest.json` 和 `migration/legacy-source-map.md`。

当前仓库已完成一次迁移，本机旧项目中发现的原始稿目录是 `财经/Raw`，已迁移 540 篇。

---

## 测试

```bash
# 运行全部测试
uv run --extra dev pytest -q

# 行情监控专项测试
uv run --extra dev pytest tests/test_stock_monitor.py -q
```

---

## 开发约定

提交前建议运行：

```bash
uv run --extra dev pytest -q
uv run python scripts/build_indexes.py
uv run python scripts/lint_knowledge.py
```

文档约定：

- 技术方案、任务文档、技能说明优先使用中文
- 架构图和流程图使用 PlantUML
- 原始稿保存在 `sources/raw`，学习后不改写原文
- 方法论变更需要能追溯到具体来源或案例
- 修改 Qing-Agent 节点后，需重启 uvicorn（Python 模块缓存）

---

## 个股分析边界

本项目输出的是学习和分析框架，不构成投资建议。`qing-stock-analysis` 的优先目标是回答：

- 博主框架下如何理解这只股票
- 所属主线是否成立
- 当前周期位置是什么
- 个股逻辑是否被证伪
- 基本面和技术面是否支持当前判断
- 哪些风险会让结论失效

它不应该直接替代个人风险约束、仓位管理或交易决策。

---

## 相关文档

| 文档 | 说明 |
|------|------|
| `AGENTS.md` | 项目根级 Required Workflow，所有 agent 必须遵守 |
| `src/qing_investment/agent/AGENTS.md` | Qing-Agent 模块维护指南（节点维护、prompt 维护、调试方法） |
| `docs/qing-agent-technical-design.md` | Qing-Agent 技术设计文档（架构图、数据流、API 字段） |
| `docs/hermes-stock-monitor-technical-design.md` | 行情监控技术设计文档 |
| `framework/reasoning-patterns.yaml` | 推理模式库（116 条 UP 推理链） |
| `skills/qing-learning/references/reasoning-pattern-architecture.md` | 推理模式三层架构设计 |
| `skills/qing-learning/references/reasoning-pattern-extraction-workflow.md` | 推理模式抽取、集成、调优完整工作流 |
| `config/stock_monitor/README.md` | 监控配置 YAML 字段契约 |

---

## 许可证

本项目使用 Apache-2.0 许可证。第三方 vendored 内容的来源和许可证记录在对应目录的 `VENDOR.md`、`LICENSE` 或原始 skill 文档中。
