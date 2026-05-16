# learning-investment-strategies

持续学习型投资方法论系统，用来长期学习财经博主的投资框架，并把学习结果沉淀成可复用的 Agent Skills 与个股分析流程。

这个项目不是自动交易系统，也不是一次性的投研报告生成器。它的核心是把原始 UP 内容保存下来，逐步抽取观点、案例和方法论，再让个股分析 skill 使用最新的框架进行分析。

## 当前状态

- 默认分支：`master`
- 保留开发分支：`feature-continuous-learning-system-build`
- 已迁移旧项目中的 UP 原始数据：当前为 `sources/raw/财经` 下 387 篇 Markdown 原稿
- 已包含三个核心 skill：`qing-learning`、`qing-methodology-review`、`qing-stock-analysis`
- 已接入 F10 基本面分析方法论，并 vendor 了 `glmv-stock-analyst` 作为个股数据分析底座

## 项目结构

```text
sources/
  raw/              原始 UP 内容，原则上不改写
  incoming/         新增内容暂存区
  processed-log.md  已学习原稿记录

knowledge/
  claims/           原子观点与证据
  wiki/             结构化知识库
  cases/            历史案例与回归样本

methodology/        长期方法论沉淀
framework/          可执行分析流程与输出契约
skills/             Agent Skills
evals/              回归验证样例
scripts/            迁移、索引、lint、扫描脚本
src/                Python 工具包
tests/              自动化测试
```

## 安装与验证

项目使用 Python 3.11+，推荐用 `uv` 创建隔离环境并运行命令。

```bash
uv run --extra dev pytest -q
```

常用脚本：

```bash
# 查看尚未学习的 Raw 原稿
uv run python scripts/find_unprocessed.py

# 重建 claims/wiki/cases 索引
uv run python scripts/build_indexes.py

# 检查知识库文档中的占位标记
uv run python scripts/lint_knowledge.py
```

如果已经创建过 `.venv`，也可以直接使用：

```bash
.venv/bin/python scripts/find_unprocessed.py
.venv/bin/python scripts/build_indexes.py
.venv/bin/python scripts/lint_knowledge.py
```

## 日常学习流程

1. 把新的 UP 原稿放入 `sources/incoming/`，确认文件名包含日期、类型和标题。
2. 使用 `qing-learning` 读取新增原稿，抽取 claim、更新 wiki、补充 methodology 和 framework。
3. 将已学习的原稿路径写入 `sources/processed-log.md`。
4. 运行索引和 lint：

```bash
uv run python scripts/build_indexes.py
uv run python scripts/lint_knowledge.py
```

5. 对关键方法论变化使用 `qing-methodology-review` 做复盘，确认是否升级、降权或修正已有规则。

## 三个核心 Skills

### qing-learning

位置：`skills/qing-learning/SKILL.md`

用途：

- 学习新增 UP 原稿
- 抽取带来源的原子观点
- 更新 `knowledge/wiki`、`knowledge/claims`、`methodology` 和 `framework`
- 维护 `sources/processed-log.md`

适合的问题：

```text
学习 sources/incoming 里的新内容，并更新方法论
检查哪些 Raw 还没有处理
把这篇早盘内容抽成 claim 和案例
```

### qing-methodology-review

位置：`skills/qing-methodology-review/SKILL.md`

用途：

- 对比近期内容和既有方法论
- 识别矛盾、过期观点、权重变化
- 决定某条规则应该进入案例、wiki、methodology 还是 framework

适合的问题：

```text
复盘最近一周博主框架是否发生变化
检查 CPO 主线判断是否和旧规则冲突
评审这条规则是否可以进入 framework
```

### qing-stock-analysis

位置：`skills/qing-stock-analysis/SKILL.md`

用途：

- 基于 GLM 个股分析底座获取行情、资金、基本面、新闻和图表
- 叠加 F10 财务分析方法论
- 使用博主框架分析个股所处主线、周期、地位、证伪条件和风险

适合的问题：

```text
按博主框架分析一只股票
结合 F10 方法论检查这家公司基本面
判断这只股票属于主线核心、补涨还是跟风
```

## 历史数据迁移

历史迁移脚本会递归发现旧项目中的 UP 原始数据目录，并迁移到 `sources/raw/<module>/...`。

```bash
uv run python scripts/migrate_legacy_up_raw.py /path/to/legacy/wiki
```

迁移结果会写入：

- `migration/legacy-manifest.json`
- `migration/legacy-source-map.md`

当前仓库已经完成一次迁移，本机旧项目中发现的原始稿目录是 `财经/Raw`，已迁移 387 篇。

## 个股分析边界

本项目输出的是学习和分析框架，不构成投资建议。`qing-stock-analysis` 的优先目标是回答：

- 博主框架下如何理解这只股票
- 所属主线是否成立
- 当前周期位置是什么
- 个股逻辑是否被证伪
- 基本面和技术面是否支持当前判断
- 哪些风险会让结论失效

它不应该直接替代个人风险约束、仓位管理或交易决策。

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

## 许可证

本项目使用 Apache-2.0 许可证。第三方 vendored 内容的来源和许可证记录在对应目录的 `VENDOR.md`、`LICENSE` 或原始 skill 文档中。
