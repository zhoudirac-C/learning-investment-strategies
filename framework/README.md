# Framework 可执行框架

本目录保存 skills 直接读取的 playbook。它比 `methodology/` 更短、更流程化。

**Agent 集成**：Qing-Agent 的 `market_analyst` 节点会根据 `analysis_type` 从本目录**显式加载**对应的 playbook 文件（如 `market` 分析加载 `market-cycle-framework.md` + `sector-diffusion-framework.md` + `trading-rules.md`），截断到 4000 字符注入 LLM prompt。修改本目录文件会直接影响 Agent 输出的方法论依据。

**Prompt 同步纪律**：若修改的 playbook 涉及大盘分析的输出格式规范（如 11 项分析框架、周期判断标准、板块映射模板），需同步检查 `src/qing_investment/agent/prompts/system/market_analysis_framework.txt`——该文件控制 Agent 的 JSON 输出结构，是输出格式的单一来源。

## Playbook 索引

| 文件 | 说明 | 轨道 |
|------|------|------|
| [stock-analysis-playbook.md](stock-analysis-playbook.md) | 个股分析八步法 | A |
| [ai-investment-cycle.md](ai-investment-cycle.md) | AI 算力全产业链四阶段炒作路径 | A |
| [sector-diffusion-framework.md](sector-diffusion-framework.md) | 板块扩散三阶段框架 | A |
| [livestock-classification.md](livestock-classification.md) | 活口分类方法论（退潮活口 vs 复苏活口） | A |
| [market-participant-framework.md](market-participant-framework.md) | 市场参与者分析框架（三类资金结构） | A |
| [market-cycle-framework.md](market-cycle-framework.md) | 市场周期与调整修复方法论 | A |
| [market-breadth-framework.md](market-breadth-framework.md) | 市场广度分析框架（多级别顶底+全A+微盘+情绪） | A |
| [technical-analysis-framework.md](technical-analysis-framework.md) | 技术分析可执行框架（K线/指标/量价/纪律） | B |
| [trading-rules.md](trading-rules.md) | 交易规则手册（接力方法论、尾盘套利法等操作纪律） | A/B |
| [volume-quality-assessment.md](volume-quality-assessment.md) | 量能质量判断框架（三步判断法） | A |
| [ai-business-model-falsification.md](ai-business-model-falsification.md) | AI商业模式证伪条件框架（控制变量法） | A |

## 更新记录

| 日期 | 更新内容 |
|------|----------|
| 2026-08-22 | 泛化改造：market-cycle / market-breadth / trading-rules 中写死"科技"主线的判据改为"当前主线 + 当期实例"写法（具体板块名移至实例说明，数值阈值与历史案例不动）；已同步 `src/qing_investment/agent/prompts/system/market_analysis_framework.txt` 板块结构地图模板 |
| 2026-08-22 | 复盘写入（methodology-review-20260822）：trading-rules 新增 5 章——急跌不接飞刀与买阴不买阳、量能档位与整数量能位、离场标准后移（右侧慢离场）、周末持仓成本、减仓节奏大涨大减；B 类新信号走提案制落 `proposals/` ×5 |
| 2026-07-29 | 方法论复盘新增4个框架：量能质量判断、AI商业模式证伪条件、避险三件套模式识别、国产链vs海外链分野选股框架 |
| 2026-07-09 | 根据 `reports/methodology-review-20260708.md` 更新：补充右侧确认量化条件、外盘开盘定价与承接纪律、均线缺口减仓、不追情绪一致、事件催化右侧应对、上游扩散风险识别、外力扰动与内生量能、位置决定意义、7 月跟踪三维度、科技主线高低切、分散配置、业绩筛选纪律、预期差评估、资金结构切换信号、非科技方向重个股轻板块。 |

## 辅助文件

| 文件 | 说明 |
|------|------|
| [contradiction-policy.md](contradiction-policy.md) | 矛盾处理规则 |
| [learning-update-protocol.md](learning-update-protocol.md) | Learning Update 协议 |
| [methodology-review-protocol.md](methodology-review-protocol.md) | 方法论 Review 协议 |
| [output-contracts.md](output-contracts.md) | 输出契约 |
