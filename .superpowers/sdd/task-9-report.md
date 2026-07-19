# Task 9 报告：全量对表 + 校准报告（M1 校准门收官）

执行：B5 批次。Step 1（全量运行）由前序完成，本 coder 执行 Step 2/3：
填齐报告 93 处占位符（31 偏差 × 3 字段）+ 追加 M2/M3 重估节 + ADR 配套仲裁落笔。
产出文件：`docs/design/chanlun-calibration-report.md`（991→1043 行）、
`.superpowers/sdd/progress.md`（追加 Task 8/9 行）、本报告。
未动任何用例 yaml、适配器、测试、third_party/chanpy 源码；零 git 操作；
**未重跑 report 生成命令**（避免模板覆盖，完整性以 grep 占位符=0 验证）。

## 1. 执行摘要

- 校准矩阵（Step 1 产出，未变）：31 用例（26 case + 5 golden），
  chanpy 0 PASS / 31 FAIL / 0 ERROR；czsc 7 PASS / 24 FAIL / 0 ERROR。
- Step 2 评审结论：**0 条用例错误**。全部偏差归因为两类：
  - 实现侧（实现偏差/实现语义差）：chanpy 24 例、czsc 24 例（FAIL 的全部）；
  - 原文歧义：chanpy 7 例（BI-002/003 的 P-B2 + BSP-003/004、GOLD-003/004/005 的 P-I），
    均归 ADR-001（已仲裁=口径 B），chanpy 为口径 A 实现、非算法缺陷。
- 8 条 ADR 全部 resolved by 主控 / 待 UP 确认；填写严格遵循仲裁结论，未推翻任何一条。
- 偏差模式全部经探针实证（/tmp 脚本，不入仓）：P-B/P-C 按任务要求实证，
  P-G/P-H/P-I/P-J/P-K 一并实证后落笔（见 §4）。

## 2. 八条仲裁结果一览

| ADR | 议题 | 结论 | 对校准报告的影响 |
|---|---|---|---|
| ADR-001 | 课77"区间"口径 | **B（分型中间 K 线自身区间）** | 偏差 4/5（BI-002/003）记"原文歧义→各代表一种读法"；P-I 五例归此；M2 chanpy `bi_fx_check` strict→loss；BI-002/003 expect 翻转待 UP 拍板 |
| ADR-002 | 新/旧笔 | A（新笔） | 无偏差归因于此；M2 核对 chanpy `bi_conf.is_strict` 对齐 |
| ADR-003 | 特征序列缺口 | A | 偏差 21（SEG-004）连带；chanpy 拆段记实现偏差（P-F） |
| ADR-004 | 古怪线段 | A | 偏差 22（SEG-005）：chanpy 拆段=被否的解释 B 行为，记 P-F |
| ADR-005 | 金标降级 | ①+②组合（Task 8 已决） | GOLD-001/002 真实日线、GOLD-003/004/005 等比 synthetic |
| ADR-006 | BSP dir 语义 | A（操作方向） | 偏差 1/2/8/9/11 + GOLD-004（修复后显现）的 dir 反=P-E，M2 适配器翻转映射 |
| ADR-007 | claim 多挂 | 允许 | 无需改动，仅记录 |
| ADR-008 | BC 面积断言 | 放 expect.meta 键 | 偏差 1/2 的面积断言 M1 不参与 diff，M2 启用 |

## 3. 31 偏差按模式归类统计

模式命中次数（一例可命中多模式；chanpy 31 例全 FAIL、czsc 24 例 FAIL）：

| 模式 | 定义 | 性质 | chanpy 命中 | czsc 命中 |
|---|---|---|---|---|
| P-A | 末位 fx/bi sure=True vs expect False（is_sure=笔已成立 vs 引擎右侧确认） | 实现语义差 | 22 | — |
| P-B1 | 孤立分型被适配器"fx 从笔端点推导"丢失 | 实现偏差（归一层） | 5（FX-002/003、INCLUDE-001/002/003） | — |
| P-B2 | strict 区间拒掉唯一候选笔→无笔→fx 空 | 原文歧义（ADR-001） | 2（BI-002/003） | — |
| P-C | `CZSC.fx_list`=Σbi.fxs[1:] 恒丢首分型 | 实现语义差 | — | 23（24 例 FAIL 中除 BI-004 外全部） |
| P-D | get_zs_seq 窗口/端点/延伸口径差（非 P-C 下游） | 实现偏差 | — | 13（BC×2、BSP×4、ZS×4、GOLD-003/004/005） |
| P-E | bsp dir 取"所在笔方向"反（ADR-006） | 实现偏差（归一层映射） | 5（BC-001/002、BSP-001/002/004）+ GOLD-004 修复后显现 | — |
| P-F | seg 拆分（单笔破坏当线段破坏/古怪线段重起算） | 实现偏差 | 2（SEG-004/005） | — |
| P-G | zs/seg sure=False vs expect True（数值全对） | 实现语义差 | 9（BC-001、BSP-001/004、SEG-003、ZS-001/002/004、GOLD-003/005） | — |
| P-H | 真实数据上游笔/zs 崩塌（GOLD-001/002）；bi/zs 正确下三买误报一买（GOLD-003/005） | 实现偏差 | 4 | — |
| P-I | strict 吞中间笔（3 笔并 1 笔） | 原文歧义（ADR-001） | 5（BSP-003/004、GOLD-003/004/005） | — |
| P-J | 不成笔 fx 对未消解、笔构造停滞（bi_list 全空） | 实现偏差 | — | 1（BI-004） |
| P-K | zs 构造/合并/升级口径差（BC-002 合并、ZS-003 无九段升级、BSP-003 未检出） | 实现偏差 | 3 | — |

三分类汇总：**用例错误 0 条**；原文歧义 7 例（chanpy 侧，ADR-001 已仲裁）；
其余全部为实现偏差/实现语义差。czsc 7 条 PASS 中 GOLD-001/002 系空断言产物
（bsp 表 N/A skip → 无 diff），非真正命中，M2 启用 bsp 断言后需重验。

## 4. 探针实证记录（/tmp 脚本，不入仓；PYTHONPATH=src:third_party/chanpy）

**P-B（任务必做）** — 脚本 /tmp/probe_pb.py、/tmp/probe_pb2.py：
- FX-002/003、INCLUDE-001/002/003：chan.py 原始合并 K 线上**分型标记存在**
  （如 FX-002 `klu_idx=[1] fx=TOP`、INCLUDE-003 `klu_idx=[1,2,3] fx=TOP`），
  但 strict/loss 下 bi_list 均空（仅单分型，根本不构成候选笔）。
  → **推翻主控原假设**（strict 拒唯一候选笔）：根因是适配器"fx 从笔端点推导"
  归一盲区（P-B1），非区间口径。M2 改 fx 归一从 CKLine.fx 标记直取。
- BI-002/003：strict 下 bi_list=[]、loss 下出 (1,5,down)/(1,5,up)
  → 原假设对这两条成立（P-B2），归 ADR-001。
- GOLD-003/BSP-003：loss 下中间笔全部恢复且与 expect 一致 → P-I 机制实证。

**P-C（任务必做）** — 脚本 /tmp/probe_pc.py：
- ZS-001/GOLD-003：fx@1 在 czsc 原始输出中完整存在
  （`finished_bis[0].fxs[0]`/`bi_list[0].fx_a`=(1,底分型)），
  但 `CZSC.fx_list` 从 (5,顶) 起——坐实 fx_list=Σbi.fxs[1:] 恒丢首分型，
  非适配器 dt 匹配漏。M2 适配器补偿 bi_list[0].fx_a（sure=True）。
- BI-001/FX-001：finished_bis 空、fx_list 仅含末位分型——同一机理
  （首笔未完成时 fx@1 同样被 fxs[1:] 规则丢弃）。

**补充实证**：
- P-G：ZS-001/BSP-001/BC-001 的 chanpy 原生 zs 数值与 expect 完全一致、
  仅 is_sure=False → 纯 sure 语义差；SEG-003 原生 seg 起止方向全对、is_sure=False。
- P-H：GOLD-001 41 根真实日线 chanpy 仅 3 笔、zs 空（strict/loss 同）；
  GOLD-002 仅 1 笔（strict 5→27/loss 2→27）→ 根因在上游 bi/zs 层，非 bsp_conf。
- P-H（家族）：GOLD-003/005 在 loss 下 bi/zs 已正确，bsp 仍误报一买
  （(29,1,up)/(33,1,up)）不报三买（(25,3,up)/(29,3,up)）→ bsp 检出条件差，
  M2 排查 bsp_conf。GOLD-004 loss 下检出 (37,1,up) vs expect (37,1,down)
  → 一卖 dir 反（P-E 修复后显现）。
- P-J：BI-004 czsc `fx_list` 多出 (5,顶)/(6,底)（间距 1 根、共用 K 线的不成笔
  fx 对）、`bi_list` 全空 → 未执行课77 步骤二同性质分型保留，笔构造停滞。
- P-K：BC-002 同 bi 序列下 chanpy 原生 zs 仅 (25.3,26.5,6,31) 一条 5 笔合并中枢；
  ZS-003 仅 (16,17,5,17) 无九段升级；BSP-003 在 loss+bi 全对下 zs_list 仍空
  （one_bi_zs=True 出错误窗口 (11.4,14.3,11,16)/(14.4,15.8,21,26)，非解）。
- P-D 非 P-C 下游：ZS-001 的 czsc bi 表与 expect 完全一致（5 笔），
  zs 仍出 (17,19,1,21) vs expect (18,19,5,17) → get_zs_seq 窗口/端点口径差独立成立。

## 5. M2 估算（详见校准报告"M2/M3 重新估算"节）

- 改造项 15 项：chanpy 配置层 3（bi_fx_check→loss 路径已验证；seg_conf/zs_conf/bsp_conf 排查）、
  chanpy 适配器归一层 3（sure 统一 / fx 直取 / bsp dir 翻转）、
  czsc 适配器层 2+1 专项（首分型补偿 / zs 重算 / BI-004 型专项）、
  引擎约定/用例层 4（sure 成文 / level 归一 / ADR-008 meta 启用 / BI-002/003 翻转待 UP）、
  PATCHES.md 补丁项至多 2（P-F/P-K 配置解决不掉部分 + P-H 真实数据专项）。
- 校准门目标：M2 后 31 用例 × 2 实现 100% PASS（前提：BI-002/003 拍板、
  GOLD-001/002 czsc 空断言重验、P-H 过深时允许降级登记由 UP 决定）。
- 工作量定性：**中（约 2~3 倍 M1 适配器层工作量）**；最大不确定项=P-H 根因深度。
- M3 占位说明不变（levels/ 递归层，M2 报告后另立 plan）。

## 6. 遗留事项（UP 评审门输入）

1. **BI-002/003 expect 翻转待 UP 拍板**：(a) 翻转 bi:[(1,5)]（推荐）/
   (b) 保留 A/B 对照样本且 meta 标注不参与 PASS 统计。
2. **全部 ADR（001~008）待 UP 确认**。
3. **UP 评审门（Task 9 Step 4）待过**——本报告+校准报告+ADR 三件套齐备。
4. GOLD-001/002 的 czsc PASS 系空断言产物（task-8 疑虑 4），M2 启用 bsp 断言后重验；
   GOLD-002 课文指认日 vs 严格包含的 idx 对齐（task-8 疑虑 1）留 UP 一并裁定
   （当前 chanpy 笔层已崩、尚未走到该摩擦点）。
5. BI-004 用例注释"bar6/bar7 间无底分型"表述不严谨（bar6 按课62 双条件实为底分型），
   不影响 expect 正确性，记录备查。
6. czsc 空断言 PASS 是否在报告渲染层单列 SKIP（report.py 行为变更），留 M2 决定。

## 7. 验证

- `grep -c "待 Task 9 人工填写" docs/design/chanlun-calibration-report.md` → **0**。
- `PYTHONPATH=src:third_party/chanpy .venv/bin/python -m pytest tests/chan_engine/ -q`
  → **162 passed**（复跑确认，未动任何代码/用例）。
- 未重跑 `python -m chan_engine.harness.report`（模板会覆盖填写内容）。
