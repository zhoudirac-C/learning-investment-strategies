# M7-7 递归层内部单元迁移：fx 段 + 段内笔级重释（B-2 落地）

> 设计依据：`docs/design/chanlun-quant-adr.md` ADR-012 方案 B（原"后置演进"）。
> 前置证据：B-3 影子观测 `logs/chan-fx-shadow-20260829.md`（B-1 硬切换 2 回归 0 修复）；
> B-2 单点原型 `scripts/chan_b2_prototype_bc002.py`（BC-002 区间套 7/7 重构）；
> B-2 全量影子 `scripts/chan_b2_shadow.py` + `logs/chan-b2-shadow-20260829.md`
> （31 用例 21 PASS / 10 FAIL 与基线逐格零变化，断言字段完全一致）。
> 拍板（UP 2026-08-29）：B 转入实施，走 B-2 路线；段内中枢 level 命名维持现契约
> （盘整中枢 L2 / 离开腿内 L1）；BC-001 三卖@31 不收编（留哲学差异清单）。

## 拍板口径

1. **递归层内部走势单元 = 特征序列段（课 67/71/78）**，greedy-3bi 退役出引擎
   （`core/segments.py` 函数与其单测保留为 M3-1 历史构造物档案，引擎不再消费）。
2. **段内结构 = 笔级"创/未创段方向新极值"拆分**（推动笔/修正笔），修正笔 run
   夹出中枢 span，课 17 首三笔严格重叠 + 已确认笔延伸（`_segment_zhongshu` 同口径）。
3. **产出契约不变**：BC-002 区间套（L2+L1+双一买@46）、BSP-003（L1+三买@26）、
   ZS-003（九段升级）、GOLD 兜底、SEG-001~005 等全部断言逐字段保持不变；
   校准矩阵 recursion 列 21 PASS / 10 FAIL 零变化为硬门。
4. 课文依据：课 67/71/78 的线段定义是笔→线段构造的唯一形式化标准；
   B-2 = 在形式化定义之上重构课 27 区间套分析能力（与课文"先实例后形式化"演进同向）。

## 实施拆分（TDD）

### T1 `core/intra.py` 段内重释模块（新文件）
影子脚本 M-b 逻辑产品化：
- `decompose_segment(seg, bi_list, bars)` → (pos, 中枢 span 列表, 腿列表)：
  尾部未确认笔剔除；同向笔推动/修正分类；修正 run 夹 span（缺后续反向笔确认 →
  尾部悬置不成中枢）；
- `emit_intra_zs_bsp(seg, bi_list, bars, hist, zs_context)` → (zs, bsp)：
  单中枢+进入腿≥3 笔 → 盘整（中枢 L2 + 离开腿内 L1 + 双级别背驰，MACD 主口径）；
  单中枢+进入腿<3 笔 → 段首三笔 L1（Path B）；≥2 中枢 → 趋势（各 L1 +
  趋势背驰：连接腿 vs 末离开腿）；
- 背驰标注 `backchi_type`（classify_backchi_type，G3 前提校验锚）。

测试锚：BC-002（盘整全结构）、BSP-003（Path B）、BC-001（趋势双中枢）、
SEG-004（悬置 Path B）、无修正结构段（纯推动 → 空）、sure 透传。

### T2 engine 换内部单元
- `_compose`：内部单元 ← build_fx_segments；M-a（段间三件套，`synthesize_level_zs`
  + `detect_backchi_bsp` 跑 fx 段）+ M-b（`intra.emit_intra_zs_bsp` 跑未消费段）；
  删除 `build_l0_segments` 消费；docstring/config_snapshot/`core/__init__.py` 同步。
- 硬门：`test_core_engine`（BC-002/BSP-003 全图 PASS）、`test_core_incremental`
  （增量一致）、`test_core_backchi_premise`（BC-002 consolidation_div 标注）、
  `test_core_trend`（BC-002 consolidation/extension、ZS-003）。

### T3 校准矩阵 + 报告
- 官方矩阵重生成：recursion 列 21 PASS / 10 FAIL 逐 cell 零变化；
- `harness/report.py` M3 模板叙述更新（greedy → fx+段内重释）。

### T4 验收
- 全量测试零回归（434 + 新增 intra 用例）；
- 影子等价复核：`scripts/chan_b2_shadow.py` 与新引擎输出一致（影子即规范）；
- ADR-012 状态更新 + 本文档验收记录。

## 非目标（本期不做）

- BC-001 expect 重锚收编三卖@31（拍板：留哲学差异清单）；
- 多中枢长趋势的延伸/扩展合并细化、UP 镜像独立锚补全（影子证据已登记边界）；
- `core/segments.py` greedy 函数删除（保留为档案，删除另议）。

## 实施记录与结论（2026-08-29）：**中止，负结果归档**

- **T1 完成**：`core/intra.py`（段内笔级重释）+ `tests/chan_engine/test_core_intra.py`
  9/9 通过，作为 B-2 可执行档案保留（引擎未消费）。
- **T2 尝试后回退**：引擎切 fx 段 + 段内重释后，合成校准矩阵 31 用例保持
  21 PASS / 10 FAIL，但**真数据 golden 16 例失败**（test_multi_tf_nested_golden /
  test_skill_adapter_golden / test_chan_analysis_cli，512400 spike 区间套分析）——
  60m  fx 段 bi0-18 整段合并，段内重释只产出首个中枢 [1.804,1.953]，
  spike 中枢 [1.712,1.851] 与 [1.86,1.96] 全部丢失（窗口 zs 为空）。
- **根因（鉴别冲突实证）**：真数据长 fx 段含多个盘整相位，其边界锚定的是
  greedy 相位分组；且存在不可调和的鉴别冲突——BC-002 要求"段首重叠三笔
  bi0-2 [25.3,28.0] 不发射"（它是三件套进入段），512400 60m 要求"同形的
  推动三笔 bi10-12 [1.712,1.851] 发射"（它是三件套离开段）。区分二者的唯一信息
  是相位在三件套中的角色，而相位边界 = greedy 规则本身。**任何纯段内局部规则
  都无法同时满足两组锚**；合成语料全部太短（≤12 笔、单相位）未暴露此问题。
- **结论**：双轨制是承载架构而非过渡态——greedy-3bi 的正名（ADR-009：
  课 35/84 f1(a0) 递归构造物）经真数据实证成立；fx 特征序列线段 = seg 表
  课文口径（M7-6 已落地）。engine 已回退至 greedy 内部单元，全量测试
  443 passed（含 intra 9 例）零回归。
- **若未来重启 B**：唯一剩余路线 = 段内相位分解的课文化重构（在 fx 段内以
  课文规则重现 greedy 等价相位），代价 = 重锚 16 例真数据 golden（实证锚，
  需 UP 逐条核定新输出的课文正确性），且即使完成也只是输出等价的口径统一。
