# M4 降级项补丁评估报告

> 计划：docs/superpowers/plans/2026-08-02-chanlun-quant-m4-patch-assessment.md
> 范围：M3 保持降级 8 项（chanpy PATCHES 4 + czsc 局限 4），只读评估，不改源码。
> 每项结论三选一：A=改 chanpy 源码（登记 PATCHES.md）/ B=适配器层补偿 / C=永久降级（登记附录 C.5）。

## 1. SEG-004/005 × chanpy（EigenFX seg 拆段口径，P-F）
- **根因复核**：（M2-5 结论）chanpy 特征序列分型在 SEG-004/005 拆段与 expect 口径不一致；`left_seg_method=all` 修 SEG-004 但净 -2（破坏 BC-001/BSP-001/GOLD-004）；`seg_algo=break` 无效。
- **探针实证**：待填
- **爆炸半径**：待填
- **建议**：待填
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
