---
date: 2026-10-13
type: pattern-nomination
status: adjudicated
adjudicated_at: 2026-10-31
outcome: 入库 pattern earnings_catalyst_test（仅语义召回，不挂 _CORE_PATTERN_IDS）。source_claims 已修正为 claim-20261011-002-f/002-g（10-11 周复盘业绩验证）；004-h/001-h/001-l 需具体日期待溯源；验证窗口标记 pending
see: framework/reasoning-patterns.yaml earnings_catalyst_test
source: 盲判vsUP对比 2026-10-13（10-09~10-12窗口）
gap_class: ②推理模式未入库
---

# 提名推理框架：earnings_catalyst_test（业绩催化检验）

## 差距事实

2026-10-09~10-12 对比窗口中，UP 连续三天把「业绩预告后的价格反应」当作板块转折的核心信号跟踪：

- 10-11 周五复盘（011-l）：景旺电子业绩预告 → 周一优先观察换手承接及能否带动 PCB/AI硬件核心
- 10-12 复盘（004-h）：联讯仪器预告 → 能否带动测试设备/光器件/光模块共同止跌，盈利增长端重新发挥定价作用
- 10-13 盘前（001-h）：源杰科技/联讯仪器落地检验三重观察——有无新持续卖盘、下探能否被接住、能否带动同类；并明确「比增速数字更值得观察的是价格反应」「单股稳定是情绪引导，板块跟随决定持续性」

同期盲判 watch_next 只有情绪股（新华传媒监管阈值/二板晋级率），**业绩线零覆盖**。

## UP 框架还原（从 claim 提取）

检验对象：业绩预告/财报落地的高辨识度标的（通常连接产业景气+机构持仓+短线情绪）。
检验三问（均为价格反应，不是增速数字）：
1. 利好落地后有无新的持续卖盘？
2. 下探能否被接住（承接）？
3. 能否带动同类公司（板块跟随）？
判定规则：
- 三问皆正 → 盈利增长端重新发挥定价作用，可作转折信号
- 只有单股脉冲、同类不跟 → 情绪引导价值有限，资金与估值压力未解除
- 高开低走/利好兑现走弱 → 情形B证据
元纪律：「机构卖压接近尾声」这类判断只是待价格验证的假设，预告本身不能终结机构重估（001-l）。

## 处置建议

1. **pack 增强**：`build_daily_pack` 从 `catalysts_since_prev_day`（research/notices 公告快照已有）中筛出「业绩预告/业绩快报」类公告，标注标的+预增幅度+所属方向，作为独立块 `earnings_catalysts` 注入（回放安全：公告日 ≤ target_day，assert_no_leakage 已有机制覆盖）。
2. **prompt 规则**（候选 v21 规则42）：当 pack 含 earnings_catalysts 且对应方向处于退潮/磨底状态时，watch_next 必须包含该标的的「承接+带动同类」检验项；stage_reason 在业绩利好落地日须区分「价格反应 vs 增速数字」。
3. **框架入库**：按 pattern schema 新增 `earnings_catalyst_test`（steps=检验三问+判定规则，falsification=高开低走/同类不跟/次日低开），source_claims 溯源 011-l / 004-h / 001-h / 001-l。是否挂入 `_CORE_PATTERN_IDS` 待验证窗口后拍板（默认先不挂，仅语义召回）。
4. **验证窗口**：当前正是天然验证期——源杰/联讯预告已落地，10-13~10-15 三日盲判输出与 UP 跟踪结果可直接对照命中率。

## 风险

- catalysts 公告分类若漏标业绩预告，注入块为空 → 规则须有「无数据豁免」分支
- 预防固化：框架是「检验方法」不是「看多业绩股」，prompt 措辞须保持状态依赖
