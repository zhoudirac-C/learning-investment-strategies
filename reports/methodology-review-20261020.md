# 方法论复盘 2026-10-20（窗口：2026-10-07 ~ 2026-10-20，14天）

## 核心结论

1. **窗口共 410 条 claim**（active 406 / superseded 4），claim_type 分布：sector-theme 141、market-cycle 96、methodology 92、operation 41、macro 20。本窗口主题高度集中在「调整市中的量能质量判断 + 承接验证」，与既有 18 框架大部分重合，但出现 **3 组值得更新框架的信号**（见下）。
2. **A类 durable rule 达标（多次重复）**：「科技仓位以大盘量能为总开关：量能不到 2.2 万亿不开科技新仓，旧仓滚动做T」在 10-08 与 10-12 两次独立出现（claim-20261008-002、claim-20261012-002），且直接回答"现在怎么办"——建议写入 `framework/trading-rules.md`（操作纪律类，走 Review→Write 管道）。
3. **推理模式提名候选 1：股票/信用双市场验证框架**（10-18，claim-20261018-002）：「海外科技股企稳须同时看股价反弹 + 高资本开支企业（CoreWeave 类）债券价格/信用利差——真企稳 vs 假反弹」。这是现有 18 框架装不下的新维度（宏观/海外观察框架均无信用市场观察项），且自带可证伪判据。**属 B 类推理模式：走 `framework/proposals/` 提案制**。提名门槛之一（≥2 种市场阶段）尚不满足（仅本窗口调整期出现），建议先建提案文件挂 pending-review，待后续 regime 复现再补证据。
4. **推理模式提名候选 2：ETF 放量≠净流入判别**（10-11、10-12、10-16、10-19 共 4 次）：「ETF 成交放大只证明交易活跃；净流入须结合份额变化与申赎数据；新增开户数≠入市资金」。现有 `volume_source_qualify`（量能源头判断）部分覆盖但不含 ETF 份额/申赎这一验证通道——建议作为该框架的 example 增补（Step 5.5 语义）或并入 volume-quality-assessment.md，不必新开框架。
5. **情绪验证次序已被既有框架覆盖**（跌停收敛→首板恢复→连板晋级扩散、修复扩散三条件=权重稳/双创止跌/上涨家数回升、承接=放量回升+回落缩量），与 sentiment_cycle、volume_source_qualify、market-breadth-framework 一致，属 no-change/clarification。
6. **Step 5.5 批量提取已执行**：窗口内 75 个新 raw 文件，实际处理 20 个候选，新增 6 个 examples（technical_timing +1、mainline_identification +1、operation_strategy +1 等），无新框架信号（无 others 落袋告警）。reasoning-patterns.yaml +361 行。
7. **矛盾分类**：本窗口无 true-conflict。supersedes 关系大量存在（多为断言迭代），机械回填 dry-run 显示 29 条待翻 superseded、199 条 contradicts 待人工裁决（存量任务，非本窗口新增问题）。4 条窗口内 claim 已标 superseded，无悬空。
8. **方法论层新观点（留 wiki 观察，未达提名门槛）**：①「底部永远分化：普涨只是打底，超额来自先走完下跌周期、结构先稳住的抗跌品种」（10-18，单次出现）；②「负乖离抄底 vs 右侧追高两模式各有代价、不左右互博」（10-13，心法层）；③「救市三板斧：大金融中字头→宽基ETF→开会发利好」（10-15，与 crash_loop_attribution 框架部分重叠，可作其 example）。

## 变化类型分布（methodology/operation 类抽样）

| 类型 | 数量级 | 代表 |
|------|--------|------|
| no-change | ~40% | 承接验证次序、放量/缩量判别（与既有框架一致，持续确认） |
| clarification | ~30% | ETF放量≠净流入（4次细化）、量能分时段比较口径 |
| extension | ~15% | 外盘映射分支化（美科技 vs 韩存储链）、信用市场维度 |
| new（提名候选） | 2 | 股债双市场验证、量能总开关仓位纪律（A类） |
| contradiction | 0 | 无 true-conflict |

## 建议后续动作（按序）

1. A类写入：`trading-rules.md` 增加「科技仓位量能总开关（2.2万亿门槛）」条目，引用 claim-20261008-002 / claim-20261012-002。
2. B类提案：创建 `framework/proposals/20261020-pattern-nomination-equity-credit-dual-verify.yaml`（status: pending-review，附 10-18 证据）。
3. example 增补：ETF 份额/申赎验证口径并入 volume_source_qualify（走 proposals patch 或下一轮提取）。
4. 运行 `backfill_claim_status.py`（去 --dry-run）落地 29 条 superseded 翻转（contradicts 199 条仍人工裁决）。
5. 同步管线：本次 reasoning-patterns.yaml 变更后按 qing-learning-sync 流程重建 Qdrant 并重启 Agent。
