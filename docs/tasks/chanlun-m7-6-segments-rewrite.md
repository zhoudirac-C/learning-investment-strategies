# M7-6 线段口径升级实施计划

> 设计依据：`docs/design/chanlun-m7-multitimeframe-skill.md` §九（M7-6 设计）+
> `docs/design/chanlun-quant-adr.md` ADR-012（2026-08-29 UP 拍板：方案 C，泛化捆绑）。
> 验收（§十一）：ADR-012 已评审 ✅；SEG-004/005 偏差消除；全量校准矩阵复验不回退。

## 拍板口径（ADR-012 方案 C）

1. **双轨制**：seg 表 = 特征序列严格口径（课 67 两情况 + 缺口，ADR-003 口径 A；
   古怪线段课 78 / ADR-004）；递归层内部走势单元保留 greedy-3bi
   （core/segments.py，课 35/84 f1(a0) 递归构造物，正名——从来不是课 67 线段）。
2. **段内多中枢泛化捆绑**（§9.2-3）：`_segment_zhongshu` 解除"最小 3 笔段"限制——
   种子=段内首三笔重叠，后续笔严格重叠则延伸 end（zd/zg 不变，对齐 chanpy
   try_add_to_end 与 czsc M2-3 口径）。
3. B（递归层迁移到特征序列段本体）后置演进，不在本期。

## 实施拆分（TDD）

### T1 `core/segments_fx.py` 特征序列构造器（新文件）
算法（课 67/71/78 第一性原理，chanpy EigenFX 语义参照）：
- 特征序列 = 反向笔序列；包含处理只对同一序列元素（课 71）：末元素包含新笔→
  吸收（升序取 max/max，降序取 min/min）；末元素被新笔包含→不合并、新开元素
  （excluded）；不相交→新开元素。
- 分型判定（三元素）：顶分型=中元素高低点均最高；底分型=中元素高低点均最低。
- 缺口：顶分型 e1.high < e2.low / 底分型 e1.low > e2.high（合并后元素间）。
- 情况 1（无缺口）→ 段终结于中元素极值边界（end_bi = peak_bi- 1），新段自此起。
- 情况 2（有缺口）→ 反向三笔确认（claim-20070816-001-b：转折后延伸出三笔、
  第三笔破第一笔结束位 → 确认）；期间原方向再创极值 → 古怪（课 78）取消候选、
  原段延续；数据末尾未确认 → 段收于候选点 sure=False。
- sure 透传：段内任一末位笔 sure=False → 段 sure=False（五表纪律一致）。

测试锚：SEG-001/002（情况 1 双向）、SEG-003（情况 2 缺口确认）、
SEG-004（单笔不破坏）、SEG-005（古怪线段）+ 合并/分型单元用例。

### T2 engine 双轨接线
- `_compose`：chart.seg ← build_fx_segments；zs/bsp/trend 继续吃 greedy 段。
- 校准矩阵硬门：SEG-004/005 FAIL→PASS；其余 cell 全不变。

### T3 levels.py 段内多中枢泛化
- `_segment_zhongshu` 延伸泛化；矩阵硬门同上。

### T4 验收
- 全量测试零回归 + 校准矩阵（目标 recursion 21/31：+SEG-004/005）+ 计划文档收尾。

## 验收记录（2026-08-29，全部通过）

| 验收项（§十一 M7-6） | 结果 |
|---|---|
| ADR-012 已评审 | ✅ UP 拍板方案 C（ADR-012 状态 resolved，2026-08-29） |
| SEG-004/005 偏差消除 | ✅ recursion 列 FAIL→PASS（特征序列两情况+缺口+古怪延续全链验证）；校准矩阵 recursion 19→21 |
| 全量校准矩阵不回退 | ✅ 逐 cell diff：chanpy 25 / czsc 25 不变，recursion 仅 SEG-004/005 两格变化，其余 29 行 × 3 列逐格一致 |
| 全量测试零回归 | ✅ 434 passed（=420 + segments_fx 11 + levels 延伸 3），2 deselected（live 触网用例）。另对 tests/ 根全套件做逐文件扫描：除 2 个与本改动零依赖的预存问题外全过——test_phase7_scenarios.py（urllib 实网场景，未标 live，挂起）与 test_discover_judge_relation_retry.py（qing_investment 重试逻辑 1 例失败），两者均不 import chan_engine |
| T1 特征序列构造器 | ✅ `core/segments_fx.py`：课 67/71/78 第一性原理实现（包含处理=末元素包含吸收 max/max·min/min、被包含 excluded；三元素分型；缺口=合并后 e1/e2 无交；情况 1 即终；情况 2 候选→课 71 观察（反向破 r1 结束位确认 / 原方向破转折点古怪取消 / 末尾悬置 sure=False）；课 78 区间取实际极值包络）。锚：SEG-001~005 逐字段 + 机制单测 6 例（吸收/excluded/悬置/古怪取消/尾巴 sure=False/课78 区间钉住） |
| T2 双轨接线 | ✅ `_compose`：chart.seg ← build_fx_segments（对外课文口径）；zs/bsp/trend 继续消费 greedy-3bi（课 35/84 f1(a0)，正名保留）。docstring/config_snapshot/`core/__init__.py` 同步 |
| T3 段内中枢泛化 | ✅ `_segment_zhongshu` 解除最小 3 笔段限制：种子=首三笔重叠，后续已确认笔严格重叠则延伸 end（zd/zg 不变，对齐 chanpy try_add_to_end / czsc M2-3）。单测 3 例（延伸/不重叠停/未确认不延伸）；矩阵逐 cell 不变（10 个 >3 笔段用例零误伤） |
| 报告收尾 | ✅ `harness/report.py` M3 模板三处叙述更新（降级项去向 / recursion 归因 12→10 FAIL / 结论计数 25/25/21 + M7-6 解决项），官方报告重生成 |

**遗留（不阻塞）**：B 演进（递归层内部走势单元迁移到特征序列段本体）按 ADR-012 后置，
不在本期；chanpy/czsc 列 SEG-004/005 保持降级（PATCHES 归属，与 recursion 无关）。

**B 演进前置证据（B-3 影子观测，2026-08-29）**：`scripts/chan_fx_shadow_evidence.py`
（不改生产代码，模块属性替换跑双链），证据落盘 `logs/chan-fx-shadow-20260829.md`。
结论：影子 fx 链路 19 PASS / 12 FAIL，判定变化仅 **2 例回归、0 例修复**——

1. **BC-002 区间套断供**（实证 ADR-012 预判）：fx 九并一后 zs/bsp **零产出**
   （缺 L2+L1 中枢、双一买@46），是结构消失而非错位；
2. **BSP-003 虚通过陷阱**：L1 中枢丢失，三买@26 看似保留，实为 zs/bsp 双空
   **误触 GOLD 日线箱体兜底**重建（机制已从课 20/21 路径换掉）——ADR-012 未预见
   的附带风险：fx 切换会结构性掏空"zs/bsp 双空"兜底条件；
3. 既有 10 例 FAIL（中枢哲学差异，ADR-010）与段口径正交，fx 切换不修复也不恶化；
   ZS-003 九段升级为笔级播种、不受影响。

含义：B-1 硬切换纯成本零收益；**B-2（fx 段 + 段内笔级中枢重释）是唯一可能重构
区间套的路线**。

**B-2 单点原型（2026-08-29，BC-002，验证通过）**：`scripts/chan_b2_prototype_bc002.py`
——不拆 fx 段，段内按"同向笔创/未创段方向新极值"分推动笔/修正笔，修正笔 run
夹出中枢 span，课 17 首三笔重叠+延伸出中枢。BC-002（fx 九并一 bi0-9）精确重构出
进入腿 bi0-2 / 中枢 bi3-5=[23.9,26.2]@16→31 / 离开腿 bi6-8=[22.9,24.4]@31→46，
σ 与 MACD 双口径段级背驰（10.84>6.04 / 5.38>2.36）与次级别背驰（2.88>2.08 /
1.33>0.43）同出，双级别一买@46 全部命中 expect（7/7 检查通过）。
注：该"新极值"规则即 greedy-3bi 扩展规则的笔级重述，二者在 BC-002 上同构。

**B-2 全量影子验证（2026-08-29，通过）**：`scripts/chan_b2_shadow.py`
（证据 `logs/chan-b2-shadow-20260829.md`）——原型泛化为全管线影子引擎
（M-a 段间三件套 + M-b 段内重释：单中枢盘整/段首三笔/多中枢趋势三分支，
九段升级与 GOLD 兜底不动），全量 31 用例 **21 PASS / 10 FAIL 与 greedy 基线
逐格判定 0 变化**，PASS 例断言字段与基线完全一致；既有测试 434 passed。
关键复核：BC-002 区间套逐字段命中、BSP-003 走课 20/21 正路径（非兜底虚通过）、
SEG-005 未断言表也全同、GOLD 兜底正常；**附带发现 BC-001 接近修复**
（双中枢+一买@46 全重建，仅多一条课文口径成立的三卖@31，expect 重锚可修复）。
迁移期遗留：增量一致性（沿用逐 bar 重算架构，test_core_incremental 硬门）、
M-b 背驰的 backchi_type 标注（test_core_backchi_premise 锚）、
段内中枢 level 命名（现为对齐 BC-002 的契约保留）需 UP 拍板。
**后续（同日）：M7-7 立项实施，T2 真数据 golden 16 例实证失败（长 fx 段
多相位边界=greedy 相位分组，段内局部规则鉴别冲突）→ 回退归档，双轨制
确认为最终架构**——详见 `docs/tasks/chanlun-m7-7-b2-recursion-fx.md` 结论段。
