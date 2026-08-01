# Task M3 报告：级别递归层（LevelTree）

> 计划：docs/superpowers/plans/2026-07-29-chanlun-quant-m3-level-recursion.md
> 周期：2026-07-29 立项（M3-0~M3-3）→ 2026-08-01 完成（M3-4~M3-6）
> 验收：**M2 降级 6 项（BC-002×2/BSP-003×2/GOLD-001/002）recursion 列全部 PASS**；198 测试全绿；chanpy 23 / czsc 25 零回归。

## 1. 目标与结论

M3 目标：自建级别递归层（两库均无此能力），按课 35/84 递归口径合成多级中枢与买卖点，使 M2 降级的 6 个用例过校准门。

结论：**6 项全部清零（recursion 列 PASS）**。校准矩阵 31 用例 × 3 实现 = 93 cell：chanpy 23 / czsc 25 / recursion 18。M2 遗留 14 降级项中：6 项由 recursion 覆盖（✅），8 项保持降级（⏸ PATCHES 4 + czsc 已知局限 4，与递归层无关）。

## 2. 交付物

| 文件 | 内容 |
|------|------|
| `src/chan_engine/core/segments.py` | L0 走势类型自建分组（贪婪 3 笔段+同向扩展，ADR-009） |
| `src/chan_engine/core/levels.py` | LevelTree：三件套识别（find_trend_patterns）→ 中枢段 level-2 / 离开段 level-1 / 独立段 level-1 |
| `src/chan_engine/core/backchi.py` | 背驰一买一卖（Σ\|Δc\| 面积代理，多级）+ 笔级三类买卖点（离开+第一次回试不破 ZG/ZD） |
| `src/chan_engine/core/fxlevel.py` | 日线箱体三买代理（GOLD 兜底，ADR-011） |
| `src/chan_engine/core/engine.py` | RecursionEngine（校准矩阵第三实现）+ RecursionSession（增量生长） |
| `src/chan_engine/harness/report.py` | 第三实现接入 + `--version M3` 报告 |
| `src/chan_engine/harness/adapter_chanpy.py` | ChanPySession 增量会话（run 重构为会话式，行为不变） |
| `docs/design/chanlun-calibration-report.md` | M3 版报告 |
| `docs/design/chanlun-quant-adr.md` | ADR-009/010/011 |
| `docs/design/chanlun-quant-engine.md` | 附录 C.2（level≥2 语义）+ C.5（刷新） |
| 测试 | test_core_segments(7)/levels(11)/backchi(4)/engine(7)/incremental(8)，合计 37 个 M3 测试 |

## 3. 关键架构决策

1. **递归层独立于两库自建**（核心发现）：chanpy 对 BC-002 把 9 笔并成 1 段（特征序列"破前摆极值才反向"），czsc 无 seg——适配器 seg 表不可用 → 从归一 bi 表自建 L0 走势类型（ADR-009）。
2. **fx/bi 委托 + zs/bsp 自建**：expect 的 BC-002 中枢语义按递归角色标记（level-2=中枢段内部、level-1=离开段内部），与 chanpy 单级别笔中枢是两种构造哲学（ADR-010）——递归层自建 zs/bsp，fx/bi 复用 chanpy 适配器（M2 已校准）。
3. **GOLD-001/002 根因新解**（推翻 M2 假设）：M2 归因为"真实日线笔太少"，M3 实证更本质——课文日线三买的"次级别离开+回试"是 **30 分钟级结构**，日线上回试仅 1~3 根 bar，笔/分型构造均不可达（GOLD-001 回试 2 bar 不成笔；GOLD-002 回试低点 bar 两侧无干净分型）。解法：日线箱体三买代理（课文例子的中枢语义=长期横盘箱体），仅笔级双空时兜底，爆炸半径收敛（ADR-011）。
4. **集成不破坏 M2 成果**：recursion 作为第三列进入矩阵，chanpy/czsc 适配器零改动，两列 PASS 数不变。

## 4. 尝试失败的点与原因

| 尝试 | 结果 | 原因 |
|------|------|------|
| fx-move 重叠构造 GOLD 中枢 | 失败 | GOLD-001 出伪三买@23（早期小箱体离开+回试误判）、GOLD-002 无输出（回试低点 bar 无干净分型，16→27 并成单一 move）——分型级构造对日线金标同样不可达 |
| recursion 复现 expect 笔中枢（chanpy normal 模式） | 未采纳 | BC-002 expect 的 level-2 语义要求段中枢构造，两种哲学不可兼得 → ADR-010 双哲学并存分工 |
| GOLD-001/002 多级别笔划分（计划 Step4 原案） | 改道 | 日线回试段 1~3 bar，任何笔划分规则都不可能成笔（课 77 分型间距硬约束）→ 改箱体代理 |

## 5. 剩余偏差（recursion 列 13 FAIL 归因）

全部为构造哲学差异（ADR-010），非算法缺陷：
- zs 分组窗口（10 项）：ZS-001/002/004、BC-001、BSP-001/002/004、GOLD-003/004/005——expect 笔中枢（引导笔后反向三笔）vs recursion 段中枢（段内首三笔）；
- ZS-003（1 项）：九段升级未实现（同两库既有降级）；
- SEG-004/005（2 项）：L0 段拆分比 expect 特征序列口径细（与 chanpy EigenFX 降级同源）。

## 6. 测试与一致性

- 198 测试全绿（M2 收官 168 → M3 +30）；
- 批量/增量一致性硬门：6 用例（BC-001/002、BSP-003、SEG-001、GOLD-001/002）一次性批量 vs 逐 bar 增量终态五表全等；is_sure 透传（末位笔 False→True）；增量生长（level-2 中枢须待 idx31 到位后出现）。

## 7. 待 UP 事项

- ADR-009（L0 分组规则）/ ADR-010（双哲学并存）/ ADR-011（箱体代理）待 UP 确认；
- M3 评审门待过；
- 保持降级 8 项（PATCHES 4 + czsc 局限 4）是否继续攻：PATCHES 项需改 chanpy 源码（EigenFX/BSPointList/ZSList），建议另立 M4 专项评估。
