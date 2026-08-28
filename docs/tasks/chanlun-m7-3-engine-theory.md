# M7-3 引擎理论补全实施计划

> 设计依据：`docs/design/chanlun-m7-multitimeframe-skill.md` §六（M7-3 设计）+ §7.2（G7 MACD 改判）+ §十（Gap 清单 G1–G4/G6/G7）。
> 验收（§6.5 + §十一）：既有测试零回归（环境已补齐，基线 296 passed）；
> 校准矩阵 chanpy 25 / czsc 25 / recursion 18 不回退且 ZS-003 recursion 转 PASS；
> MACD 面积函数单测数值锚定；新增 synthetic（两中枢趋势/中枢扩张/二买构造/盘整背驰 vs 趋势背驰）各 ≥2 例。

## 基线（2026-08-28 开工前）

- pyproject `pythonpath` 增 `third_party/chanpy` → **296 passed, 2 deselected(live), 0 error**。
- 校准矩阵基线：chanpy 25 PASS / czsc 25 PASS / recursion 18 PASS（ZS-003 recursion FAIL=已登记降级项）。

## 预检结论（既有代码实证）

- diff 比对字段是显式表（`_TABLE_FIELDS`），BSPoint 增字段不回退校准门；bsp 主键 (idx,bstype,dir)。
- BC-002 一买@46 后仅一根 sure=False 上行笔，无确认反向笔 → 二买生成不误触发既有用例（矩阵兜底）。
- recursion 列 ZS-003 当前产出三件套 zs（[16.5,18]L2 + [16.2,17.8]L1），与 expect
  （单条 16.5/17.0 idx5-41 L2）结构性不符——九段升级须**笔级播种**（czsc 式引导笔+反向笔配对），
  不能只在既有段合成 zs 上做延伸探测（recursion zs 表无对应 L1 种子）。
- czsc 适配器 `_apply_nine_bi_upgrade` 口径：种子=反向笔对重叠，sure 笔延伸，≥9 笔 + 3 子中枢重合门控。

## 任务拆分（TDD，逐项先红后绿）

### T1 G7：calc_macd 移植 + 背驰主口径切换
- 新增 `core/macd.py`：`calc_macd(closes, fast=12, slow=26, signal=9)` 纯函数，
  首值用首根 close 种子（逐位对齐 skill chan_analysis.py calc_macd），docstring 写明种子/预热规则。
- 单测数值锚定：固定输入快照值（EMA 递推 + hist=(dif-dea)×2）+ 性质断言（dif=ema_f-ema_s）。
- backchi.py：`_bi_area_macd/_segment_area_macd`（|hist| 求和，区间为笔/段端点 bar 闭区间）；
  `detect_backchi_bsp(..., area_mode="macd")` 默认 MACD；`"sigma"` 保留 Σ|Δc| 校准对照路径。
  校准门 expect 断言不动（BC-002 双口径同向背驰，设计 §7.2 已实证背书）。

### T2 G1/G2：`core/trend.py` 走势类型状态机
- `TrendState { walk_type: trend/consolidation/unknown, direction, zs_count, zs_list, last_event }`。
- `analyze_trend(zs_list)`（同级中枢列表，按 start_idx 排序）：
  0 中枢→unknown；1 中枢→consolidation（last_event=extension）；
  连续两中枢同向不重叠（上涨：next.zd > prev.zg；下跌：next.zg < prev.zd）→ trend，last_event=new；
  重叠 → consolidation，last_event=expansion（级别扩张，claim-20070105-001-a/b）。
- engine._compose 挂接：NormalizedChart 增 `trend: TrendState|None` 字段（diff 不比，安全），
  取 chart.zs 最高 level 的同级别中枢分析（暂定口径，写入 docstring）。

### T3 G3：背驰前提校验
- BSPoint 增 `backchi_type: str = ""`（bstype=1 时填 trend_div/consolidation_div）。
- detect_backchi_bsp 增可选 `zs_list` 参数（既有直调兼容）：三件套中枢段 L2 中枢为"当前中枢"，
  其前存在同向不重叠 L2 中枢 → trend_div，否则 consolidation_div（L15 没有趋势没有背驰）。
- engine._compose 传 chart.zs。

### T4 G4：二买/二卖生成
- `detect_second_type_bsp(bsp_list, bi_list, bars)`（backchi.py）：
  一买（bstype=1,dir=up）后第一根反向（down）笔——低点不破一买低点（bars[bsp.idx].l）
  → 二买（bstype=2,dir=up，idx=回调笔终点，level 取一买 level，sure=回调笔.sure 透传）；
  一卖镜像。首个反向笔破低 → 该一买不出二买（只取第一次回调）。
  同一回调点被多级一买命中 → 去重保最高 level。
- engine._compose 在 bsp 合成末尾接入，排序规则不变。

### T5 G6：recursion 九段升级（core/levels.py）
- 新增 `detect_nine_bi_zs(bi_list, bars) -> list[ZhongShu]`：笔级播种
  （引导笔定方向，反向笔对重叠成种子，sure 反向笔重叠延伸——czsc 适配器同口径），
  范围内 ≥9 笔且前 9 笔分 3 组子中枢各自成立且 3 子中枢重合 → level=2 中枢
  （zd/zg=重合区间，start=种子首笔 start，end=延伸终点）。
- engine._compose：合成 zs 后调用；命中时**吞并**起点落在升级中枢 span 内的段合成 zs
  （中间产物不发射，对齐 ZS-003 expect"只列升级后 L2"），然后排序。
- 验收锚：ZS-003 recursion FAIL→PASS；其余 17 个 recursion PASS 不回退（矩阵硬门）。

### T6 M7-3 集成验收
- synthetic 引擎级用例（spec.builders.bars_from 造 zigzag）：两中枢趋势 ×2、中枢扩张 ×2、
  二买构造 ×2、盘整背驰 vs 趋势背驰 ×2（各含正/反例）。
- 全量测试 + 校准矩阵复跑 + 本计划验收记录更新。

## 验收记录（2026-08-28，全部通过）

| 验收项（§6.5/§十一） | 结果 |
|---|---|
| 既有测试零回归（开工前补齐环境） | ✅ pyproject pythonpath 增 third_party/chanpy 后基线 296 passed 0 error；M7-3 完成时 **342 passed**（+46 新增），增量一致性硬门等全部保持 |
| 校准矩阵三列不回退 | ✅ chanpy 25 / czsc 25 前后一致；recursion 18 → **19**（唯一变化=ZS-003 FAIL→PASS，/tmp 基线与终版逐行 diff 实证） |
| ZS-003 recursion 修复 | ✅ `detect_nine_bi_zs` 笔级播种+门控移植 core/levels.py，expect 精确匹配（16.5/17.0, idx5→41, L2），中间产物吞并 |
| MACD 面积函数单测数值锚定 | ✅ `test_core_macd.py` 快照值逐位锚定（与 skill calc_macd 同源复现）+ 种子规则 + 性质断言 |
| 背驰主口径切换 | ✅ `detect_backchi_bsp` 默认 area_mode="macd"，sigma 路径保留（两口径测试层隔离）；切换后矩阵逐 cell 不变（BC-002 双口径同向背驰实证成立） |
| synthetic 新增（各 ≥2 例） | ✅ 两中枢趋势 ×3 / 中枢扩张 ×3（test_core_trend.py）；二买构造 ×2+（test_core_second_bsp.py）；盘整背驰 vs 趋势背驰 ×2+（test_core_backchi_premise.py classify 纯函数 + BC-002 集成） |
| 新增字段不污染五表 | ✅ BSPoint.backchi_type / NormalizedChart.trend 均不参与 diff（_TABLE_FIELDS 显式表实证），BC-002 等 expect 逐字未动 |

交付物：`core/macd.py`、`core/trend.py`（新）；`core/backchi.py`（area_mode + classify_backchi_type + detect_second_type_bsp）、`core/levels.py`（九段升级）、`core/engine.py`（挂接）、`spec/model.py`（BSPoint.backchi_type / NormalizedChart.trend 新增字段）、`core/__init__.py` 导出、`harness/report.py` M3 模板归因更新、`docs/design/chanlun-calibration-report.md` 重生成。

已知边界（登记）：TrendState 引擎挂接用"最高 level 中枢"暂定口径；二买为反向笔代理（仲裁 ⑤，M7-4 真 60m 确认消解）；BC-001 等 12 项 recursion FAIL 为已登记哲学差异，不动。

## 风险与纪律

- 五表语义不改：trend/backchi_type 为新增字段；bsp 仅新增 bstype=2 条目（既有条目不动）。
- 背驰口径切换仅限 `detect_backchi_bsp`/`_segment_internal_backchi` 的面积函数；校准 expect 不动。
- 二买过渡期用反向笔代理（仲裁 ⑤），M7-4 真 60m 确认上线后消解。
