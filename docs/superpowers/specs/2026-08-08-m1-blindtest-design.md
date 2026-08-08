# M1 盲测 eval 设计：历史回放 + 双对比评分 → AI 独立推理基线命中率报告

> 对应 v2.1 方案（investment-learning-project/ai-stock-investment-plan.md）第十节与第十四节 M1 里程碑。
> 前置：M0 已完成（10 框架来源中立化、术语词典、产业链知识库、回测基建、K 线缓存 2026-04-27~08-07）。

## 目标与验收

用市场走势检验 AI 独立推理能力，产出**基线命中率报告**（`logs/m1-baseline-<date>.md`）：

- 市场阶段判断与机械真值标签的一致率（71 日全量）；
- 方向判断（1-3 个方向）5 日内相对沪深300 超额为正的比率；
- 标的判断（每方向 1-2 个）5 日相对超额为正的比率；
- vs UP 抽样对照表（10 天，仅诊断，不进命中率）。

口径对齐第十节毕业标准，但**本报告是基线而非毕业判据**（单窗口 71 日）。

## 关键决策（已与用户对齐）

| 决策点 | 结论 |
|---|---|
| 推理执行方 | 新建离线 replay 脚本调 LLM API（可复跑、可审计，是 M2 影子双轨的直接前身） |
| 真值标签 | 机械规则标注（指数 K 线可计算特征），规则先定义后冻结 |
| 被测模型 | DeepSeek（生产 agent 默认 provider；知识截止大概率早于回测窗口，盲测污染最小） |
| 范围规模 | 方案 A：全量 71 交易日 + 轻量 vs UP 对照（抽 10 天） |

## 架构

新建 `src/investment_engine/blindtest/` 子包（红线不变：只 import qing_investment，不修改）：

```
blindtest/
├── dataset.py     # 测试集：缓存交易日枚举 + 每日数据包构建（K线截断、当日行情、知识库）
├── truth.py       # 真值标签：机械规则 → 每日市场阶段（主升/震荡/调整/恐慌）
├── replay.py      # 推理：prompt 组装 + DeepSeek 调用（JSON mode, temp=0）+ 断点续跑
├── score.py       # 评分：阶段一致率、方向/标的 5 日超额（vs 沪深300）
└── up_baseline.py # vs UP 对照：抽 10 天从 sources/raw 抽取 UP 当日结论 → 分歧对照表
scripts/blindtest_replay.py   # CLI：--run 推理 / --score 评分 / --report 报告（分步可单跑）
```

数据流：`dataset` 逐日产数据包 → `replay` 调 DeepSeek 逐日写 JSONL → `score` 读 JSONL + K 线算命中率 → `report` 出 md。`truth` 的真值标签在评分前全量预生成并落盘（冻结可审计）。

## 数据层

- **测试集**：缓存实际覆盖的 71 个交易日（2026-04-27 ~ 2026-08-07）。方向/标的评分需 5 日前向数据，尾部 5 日只参与阶段评分。
- **每日数据包**（prompt 唯一输入）：
  - 沪深300 与上证指数截至当日 K 线摘要（近 60 日：OHLC/涨跌幅/量能/振幅）；
  - stock_pool 标的当日量价（收盘价、涨跌幅、换手率、相对 20 日区间位置）；
  - 产业链知识库（`knowledge/industry-chains/`，现版）、术语词典、10 框架的 name+trigger 索引；
  - 方向池（`direction_pool.yaml`）+ stock_pool 的 direction→标的映射（供按池选择）。
- **需补拉指数日 K**：沪深300(000300)、上证指数(000001)，走 pre_fetch 同链路，拉 120 根（真值规则需窗口前 20 日 lookback）。
- **如实标注的缺口**：板块资金流、涨停池、涨跌家数无历史缓存，进不了数据包；知识库只有 2026-08-08 现版、无历史快照。UP 当日言论不进 prompt（盲测核心约束）。
- **真值规则（冻结版）**：对沪深300 每个交易日计算——`r20`=20 日收益、`pos20`=收盘在 20 日最高/最低区间中的位置、`r5`=5 日收益、`vol_trend`=近 5 日均量/前 20 日均量。按序匹配：
  1. `r20 ≤ -8%` 或（`r5 ≤ -4%` 且 `vol_trend ≥ 1.5`）→ **恐慌**
  2. `r20 ≤ -3%` 或 `pos20 ≤ 0.35` → **调整**
  3. `r20 ≥ +4%` 且 `pos20 ≥ 0.6` → **主升**
  4. 其余 → **震荡**
  计划含一次性校准步：规则跑全窗口若出现单一类别占比 >80% 的退化分布，按窗口分位数微调阈值一次并记录两版；校准后冻结。

## 推理层

- **Prompt 契约**：system 角色="执行已验证方法论的市场分析引擎"（要求每步声明所用数据与来源）；user=当日数据包+输出契约。强制 JSON：
  ```json
  {"market_stage": "主升|震荡|调整|恐慌",
   "stage_reason": "…",
   "directions": [{"direction_id": "从方向池选", "reason": "…", "stocks": ["002371"]}],
   "used_patterns": ["upstream_cycle", "…"]}
  ```
  directions 限 1-3 个、每方向 1-2 标的（限 stock_pool 内该 direction 成员）；`used_patterns` 记录调用的框架（服务 8 个 pending-m1 框架的回填与 M2 归因）。
- **调用参数**：OpenAI 兼容端点（api.deepseek.com），JSON mode，temperature=0；`DEEPSEEK_API_KEY` 读环境变量，缺失即明确报错；失败重试 3 次指数退避；逐日 append JSONL，重跑跳过已完成日期。
- **防泄漏机械断言**：发送前检查 prompt 不含晚于当日的日期字符串、不含 `UP|青枫浦|博主`，违例拒绝发送（有单测）。
- **模型知识截止核查**：计划任务含核查 DeepSeek 被测版本的知识截止日期；若晚于 2026-04，在报告中降级结论可信度并如实标注。

## 评分层

- **阶段一致率** = AI 阶段 == 规则标签 的比例（71 日全量）。
- **方向超额**：direction → stock_pool 内该 direction 标的等权 5 日收益 − 沪深300 同期收益 > 0 记命中；给命中率与样本数。
- **标的超额**：5 日相对沪深300 超额 > 0 的比率。
- **vs UP 对照**（up_baseline.py）：按真值标签分层抽 10 天，DeepSeek 从当日 `sources/raw/财经/` UP 文档抽取 {阶段, 方向} 标签 → AI/UP/真值三方对照表。"AI 与 UP 分歧且 AI 对"的案例单独列出（毕业信心证据）；"一致但都错"的回炉引擎⓪ 候选。
- **报告**：`logs/m1-baseline-<date>.md`，含三项命中率、分环境段（上涨/震荡/下跌段）拆分、样本量、caveat 全录。

## 错误处理

- API 失败重试 3 次后该日记 `error` 继续；JSON 解析失败重试 1 次仍败记 `invalid`；两者如实计入报告分母并单列。
- 无 key / 无网络 fail-fast；断点续跑；指数数据缺失时拒绝评分并报缺数据。

## 测试

TDD（先测后实现，测试用例在计划任务中给出）：

- `test_truth.py`：合成 K 线（已知主升/调整/恐慌走势）验证标签；
- `test_dataset.py`：数据包截断正确性（不含未来日期）、防泄漏断言；
- `test_score.py`：合成推理记录验证一致率/超额计算；
- `test_replay.py`：JSON 解析容错、断点续跑（mock API）；
- e2e：1 日 dry-run（真实调一次 DeepSeek）。
- 仓库惯例：`tests/investment_engine/` 无 `__init__.py`，`.venv/bin/pytest`。

## 红线与边界

- 不改 `src/qing_investment/` 任何文件；DeepSeek key 不落盘不进 git。
- M1 不做：prompts/ 改造（M4）、影子双轨每日流程（M2）、claims 分桶回写（M3）。
- vs UP 对照是诊断信息，不进命中率、不改任何框架内容。
