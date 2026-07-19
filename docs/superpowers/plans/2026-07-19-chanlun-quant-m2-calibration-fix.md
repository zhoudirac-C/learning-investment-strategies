# M2 实施计划：chanpy/czsc 口径改造 → 校准门 100% PASS

- 依据：docs/design/chanlun-calibration-report.md「M2/M3 重新估算」节（15 项改造）+ docs/design/chanlun-quant-adr.md（ADR-001~008，ADR-001 已经 UP 确认）
- 目标：**31 用例 × 2 实现 100% PASS**（26 case + 5 golden）；P-H 若根因深入 chanpy 笔算法允许降级登记，由 UP 决定是否阻塞关门
- 约束：TDD；.venv (py3.11)；`PYTHONPATH=src:third_party/chanpy`；chan.py 源码只读（配置/适配器层解决不了的补丁逐条登记 third_party/chanpy/PATCHES.md）；**M2-6 之前禁止重生成 chanlun-calibration-report.md**（会覆盖 M1 已填内容，测量用 `--out /tmp/m2-report.md`）
- 测试基线：162 全绿（M2-0 后）

## M2-0 用例翻转（已完成）

- BI-002/003 expect 由 `bi: []` 翻转为 `bi: [(1,5,down/up,False)]`（UP 2026-07-19 拍板，ADR-001 已记）

## M2-1 chanpy 配置 + 适配器归一（项 1/4/5/6）

- `bi_fx_check` strict→loss（ADR-001 连带，CChanConfig 默认快照如实记录）
- sure 约定统一（写死进适配器，规则源自 expect 语料）：fx/bi **末位 False、其余 True**；zs/seg/bsp **形成即 True**
- fx 归一从笔端点推导改为 CKLine.fx 标记直取（idx 取极值所在原始 klu）；**风险**：直取可能暴露 expect 之外的分型（探针曾见 INCLUDE-003 klu_idx=[1,2,3] fx=TOP）——必须逐case核集合一致，若超出生根因并按课文口径过滤，规则写进 docstring
- bsp dir 映射翻转：is_buy→up、否则 down（ADR-006）

## M2-2 czsc 适配器（项 7/8）

- 首分型补偿：`bi_list[0].fx_a` 补一条 FX（有笔从它出发即 sure=True；bi_list 空不补）
- zs 归一弃用 `get_zs_seq` 窗口，从归一 bi 表按课文口径重算：前三笔重叠确立（start=首笔起点、end=第三笔终点、区间=max(低)/min(高)）、延伸触及即延展 end、九段升级 level=2
- 调查 czsc 买卖点支持（bs_point_lst 或等价物）；无低成本支持则保持 N/A，结论写进 M2-4 的 SKIP 决策

## M2-3 chanpy seg/zs/bsp 配置排查（项 2/3，依赖 M2-1）

- P-F（SEG-004/005 拆段）：seg_conf 逐项实验；配置解决不了 → PATCHES.md 登记
- P-K（BC-002 合并、ZS-003 无九段升级、BSP-003 未检出）+ P-H 家族（GOLD-003/005 误一买不报三买）：zs_conf/bsp_conf 排查，one_bi_zs 已证非解
- 每项实验记录：配置值 → 矩阵变化；终值进适配器默认

## M2-4 引擎约定 + 断言增强（项 10/11/12）

- sure/level 归一约定成文（写入 docs/design/chanlun-quant-engine.md 或归一契约文档）
- ADR-008 落地：expect.meta 面积断言接入 diff 比对（BC-001/002 启用）
- level 归一规则定义（九段升级/中枢嵌套；依赖 M3 的部分登记）
- 报告渲染层：N/A 表单列 SKIP（GOLD-001/002 czsc bsp 空断言不再计 PASS）

## M2-5 专项（项 9/14/15）

- P-H：GOLD-001/002 真实数据 chanpy 笔划分根因（41 根日线仅 3 笔、zs 空）；配置/适配器层可解则解，否则 PATCHES.md 登记 + 降级结论交 UP
- P-J：BI-004 czsc 不成笔 fx 对未消解、bi_list 全空——czsc 库行为差，登记专项核对结论
- PATCHES.md 逐条登记所有补丁（如需）

## M2-6 收官

- 全量复跑校准门：100% PASS（或降级项清单）
- 重生成 docs/design/chanlun-calibration-report.md（M2 版；M1 版已在 git 历史 f959190）
- 更新 ADR 状态、progress.md、写 task-m2 报告；提交推送（另行向用户确认）

## 批次编排

| 批次 | 内容 | 并行性 | checkpoint |
|---|---|---|---|
| M2-1 | chanpy 配置+归一 | 与 M2-2 并行 2 coder | 各自测试绿 + /tmp 矩阵 PASS 增量 |
| M2-2 | czsc 适配器 | 与 M2-1 并行 | 同上 |
| M2-3 | chanpy seg/zs/bsp 配置 | 串行（依赖 M2-1） | 实验记录完整 |
| M2-4 | 约定成文+断言增强 | 串行 | meta 断言生效 |
| M2-5 | P-H/P-J 专项 | 串行 | 根因结论 |
| M2-6 | 收官 | 串行 | **UP 评审门** |

每批后主控 spec-compliance + 代码质量评审，Critical 不过夜。
