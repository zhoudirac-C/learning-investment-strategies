# M4 降级项补丁评估报告

> 计划：docs/superpowers/plans/2026-08-02-chanlun-quant-m4-patch-assessment.md
> 范围：M3 保持降级 8 项（chanpy PATCHES 4 + czsc 局限 4），只读评估，不改源码。
> 每项结论三选一：A=改 chanpy 源码（登记 PATCHES.md）/ B=适配器层补偿 / C=永久降级（登记附录 C.5）。

## 1. SEG-004/005 × chanpy（EigenFX seg 拆段口径，P-F）
- **根因复核**：（M2-5 结论）chanpy 特征序列分型在 SEG-004/005 拆段与 expect 口径不一致；`left_seg_method=all` 修 SEG-004 但净 -2（破坏 BC-001/BSP-001/GOLD-004）；`seg_algo=break` 无效。
- **探针实证**：（M4-1，探针 `/tmp/m4_probe_seg.py` + 追踪探针 `/tmp/m4_probe_seg_trace.py`，运行时 monkeypatch 未改源码）
  - 输出对照（bi 表两用例均与 expect 一致，差异纯在 seg 层）：
    - SEG-004：expect 1 段 `bi0..bi4 up sure=false`；chanpy 拆 2 段 `bi0..bi0 up` + `bi1..bi3 down`。
    - SEG-005：expect 2 段 `bi0..bi8 down sure=true` + `bi9..bi11 up sure=false`；chanpy 拆 4 段 `bi0..bi0 down / bi1..bi3 up / bi4..bi8 down / bi9..bi11 up`。
  - 分叉点定位（函数+行号，追踪实证）：
    - **SEG-004**：EigenFX 主流程与 expect 口径一致——`treat_second_ele`（EigenFX.py:33-35）正确判定 X2=bi3[11,15] 高点 < X1=bi1[12,16] 高点 → reset，无顶分型；`can_be_end`(:82)/`find_revert_fx`(:159)/`actual_break`(:117) 全程零调用。真正分叉点在 EigenFX **之外**的尾部兜底：`SegListComm.collect_first_seg` PEAK 分支（SegListComm.py:55-66，reason=`0seg_find_high`）把首段钉在峰值 bi0，`collect_left_as_seg`（SegListComm.py:121-129，reason=`collect_left_0/1`）把余下 bi1..bi3 硬补成向下段——兜底路径不检查"线段必须被线段破坏"（claim-20070702-002-a）。
    - **SEG-005**：EigenFX 本体最终在 bi11 确认底分型（`treat_third_ele`:38 → `actual_break`:117=True → `can_be_end`:82 gap=False → True），段终结于 bi8 sure=true，**与 expect 一致**；真正分叉点在 `try_add_new_seg` 的 `split_first_seg` 分支（SegListComm.py:132-138，reason=`split_first_1st/2nd`）：首段内部峰值 bi3（21）超过起点 bi0（20）即把首段劈成 `bi0..bi0 + bi1..bi3`，而 expect 按课78"古怪线段标准化"保留单段 bi0..bi8（区间 [12,21]，不拆）。`find_revert_fx`(:159) 缺口分支在两用例均未触发（无缺口语料）。
  - 结论：M2-5 归因"EigenFX 拆段口径"需细化——两个真正分叉点都在 **SegListComm.py 的首段/兜底启发式**，不在 EigenFX 的 can_be_end/find_revert_fx/actual_break。
- **爆炸半径**：
  - 直接：expect 含 seg 表的用例共 5 个（`grep -l 'seg:' src/chan_engine/spec/cases/*.yaml` → seg-001..005；brief 给定的 `grep -l '"seg"'` 因 YAML 键不带引号返回空，已用等价命令佐证），其中 chanpy PASS 3 个（seg-001/002/003）。
  - 间接：seg 是 zs/bsp 上游（chanpy 同一 KLU 产出 seg_list/zs_list/bs_point_lst，adapter_chanpy.py:235-275 同源读取），且 trace 显示兜底路径（`0seg_find_*`/`collect_left_*`/`split_first_*`）在常规增量运行中高频触发 → 粗粒度口径：**全部 23 个 chanpy PASS 都在半径内**，任一兜底/首段行为修改需 23 个逐一复跑。
  - 半径实证：M2-5 已实测 `left_seg_method=all`（全局切兜底）修 SEG-004 但净 -2（BC-001/BSP-001/GOLD-004 翻转）。
- **建议**：**C（永久降级，登记附录 C.5）**。判据对照：
  - 两个分叉点（`collect_first_seg`:55-66 / `collect_left_as_seg`:121-129 / `try_add_new_seg` split_first:132-138）均为全库共享的默认行为路径，非可旁路的边角分支；
  - 唯一已知配置通道 `left_seg_method`（枚举仅 ALL/PEAK，SegConfig.py:6-13）全局切换已实测净 -2 → 满足判据"需改动默认行为且任一 PASS 翻转"；
  - 形式上可走 A（新增配置项默认关）——评审指正：harness 侧**已有** per-case 配置通道 `ChanPyAdapter.__init__(config_overrides)`（adapter_chanpy.py:162-173），A 的实际门槛低于原论证字面所述；维持 C 的真正依据是收益/成本与门控脆弱性：①新增"默认关"配置仍需改 vendor 源码（新 LEFT_SEG_METHOD 成员 + split_first 开关，SEG-005 另需源码补丁），违反最小 diff 原则，且 M2-5 已实证该路径相关参数组合（`left_seg_method=all`）净 -2；②收益仅 chanpy +2 PASS（2 个单级别 seg cell，expect 仅比 fx/bi/seg 三表、无 zs/bsp 牵连），而配置项触碰 seg 上游共享路径、影响全量 23 个 PASS 用例，门控脆弱需逐一复跑；③演进方向由 ADR-009 recursion L0 承担；
  - B（适配器补偿）亦否：改写 seg 表会与 chanpy 内部 zs/bsp 口径脱节，且 reason 模式门控脆弱（seg-001..003 同样走兜底路径，易误伤 PASS）；
  - 替代路径由 ADR-009 recursion L0 演进承担（当前 recursion 列对此二用例同源 FAIL，属已知待演进项）。
- **UP 决策**：待填

## 2. BSP-004 × chanpy（三买"二三类重合"缺失，P-K）
- **根因复核**：（M2-3 结论）BSP-004 expect 三买@36 与二买@36 重合（课21）；chanpy `cal_seg_bs3point` 不覆盖该场景；`strict_bsp3`/`bsp3_peak`/`bsp3a_max_zs_cnt` 实验均无效。
- **探针实证**：待填
- **爆炸半径**：待填
- **建议**：待填
- **UP 决策**：待填

## 3. ZS-003 × chanpy（跨 seg 九段升级，P-K）
- **根因复核**：（M2-5 结论）ZS-003 的 chanpy zs 受 seg 切分限制（end=17，不够 9 段）；`ZS.combine` 拒绝 one_bi_zs（ZS.py:116）和跨 seg（ZS.py:118）；`one_bi_zs=T` 实验回归 BSP-002/GOLD-003/005（-3）。czsc 适配器已有参照实现 `_apply_nine_bi_upgrade()`。
- **探针实证**：待填
- **爆炸半径**：待填
- **建议**：待填
- **UP 决策**：待填

## 4. BI-004 × czsc（min_bi_len + 课77步骤二，P-J）
- **根因复核**：（M2-5 结论）czsc 0.10.12 rust 后端内置 min_bi_len=6（忽略环境变量）→ BI-004 bi_list 空；切 python 后端 min_bi_len=4 出 3 笔，但因无课77步骤二"同性质相邻分型保留更极值者"消解，与 expect 1 笔 (1,9,u) 不一致。
- **探针实证**：待填
- **爆炸半径**：待填
- **建议**：待填
- **UP 决策**：待填

## 5. BSP-002/004 × czsc（无 seg 限制 zs 延伸）
- **根因复核**：czsc 不产出线段，中枢延伸缺 seg 约束口径，BSP-002/004 的 expect bsp 依赖延伸后中枢。
- **探针实证**：待填
- **爆炸半径**：待填
- **建议**：待填
- **UP 决策**：待填

## 6. GOLD-005 × czsc（zs 构造口径，P-K）
- **根因复核**：（M2-3 结论）GOLD-005 expect 中枢从 bi2 开始（跳过 bi0 引导笔+bi1 离开笔）；czsc 适配器 `_recompute_zs`"反向笔配对"无法复现，涉及走势类型判定。
- **探针实证**：待填
- **爆炸半径**：待填
- **建议**：待填
- **UP 决策**：待填

## 7. 汇总与 UP 决策门
- 待填（8 项建议汇总表 + 基线复跑结果）
