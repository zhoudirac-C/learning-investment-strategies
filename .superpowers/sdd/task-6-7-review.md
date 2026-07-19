# Task 6/7（B3 批次）评审：spec 合规 + 代码质量

> 评审对象：diff 引擎与报告生成（Task 6）、26 条 synthetic 用例 + schema 测试（Task 7）。
> 方法：对照 task-6-brief / task-7-brief 逐 Step 核对；直接 Read 交付文件（无 git diff 基线）；
> claims 原文抽查 3 条；26 用例全量机械校验；真实适配器 CLI 冒烟。

## 运行验证（评审人复跑）

```
$ PYTHONPATH=src:third_party/chanpy .venv/bin/python -m pytest tests/chan_engine/ -q
146 passed in 1.33s        # 与 task-7-report 一致 ✅

$ python -m chan_engine.harness.report --cases src/chan_engine/spec/cases --out /tmp/.../calibration.md
退出码 0；chanpy: PASS 0 / FAIL 26 / ERROR 0；czsc: PASS 5 / FAIL 21 / ERROR 0   # CLI 端到端可用 ✅
```

冒烟报告含校准矩阵（用例/来源/impl 状态）、统计、偏差明细（缺/多元素全字段 + 主键定位
字段不一致）、口径偏差清单六要素模板（规则源 claim / chan.py 行为 / czsc 行为 /
原文依据 / 仲裁结论 / M2 改造点，后三项占位【待 Task 9 人工填写】）——与 Step 3 模板一致。

## 一、Spec 合规

### Task 6（4 Step）：✅ 全部交付，无缺漏、无超范围

| Step | 结论 | 证据 |
|---|---|---|
| 1 先写测试（全一致 PASS / 端点差 1 FAIL 指字段 / N/A 跳过） | ✅ | test_diff.py `test_full_consistent_passes`、`test_bi_endpoint_off_by_one`（缺 (0,5,up)+多 (0,6,up) 定位到表与端点）、`test_na_fields_tables_skipped`；test_report.py 覆盖 PASS/FAIL/ERROR 三态 |
| 2 diff.py（主键对齐、缺/多单列、容差=0 留参数） | ✅ | `TABLE_KEYS`：bi/seg/bsp 按端点+方向，fx 按 (idx,type)，zs 按 (start_idx,end_idx)；`diff_table` 缺/多单列；`tolerance` 默认 0 且只作用于 zd/zg（非 float 字段容差 100 也不放水，有测试钉住） |
| 3 report.py（校准矩阵 + diff 详情 + 六要素偏差模板） | ✅ | `render_report` 矩阵 case_id × impl × PASS/FAIL/ERROR + 偏差明细 + 偏差条目模板；`_IMPL_LABEL` 把 chanpy 渲染为"chan.py 行为" |
| 4 全绿 | ✅ | 146 passed（见上） |

说明（非偏差）：brief 只给了 (start_idx,end_idx,dir) 一个主键示例，fx/seg/zs/bsp 的主键是
实现方合理推广并在 task-6-report"疑虑点"声明（BSP 主键含 dir 系自行决定，可一行改）；
`--golden` 参数出自实施计划 Task 9 Step 1 的 CLI 引用，非镀金。

### Task 7（8 Step）：✅ 数量/指派/测试齐全；用例数据有 2 类实质缺陷（见质量问题）

- Step 1–7：26 条齐全，族分布 include 3 / fx 3 / bi 5 / seg 5 / zs 4 / bsp 4 / bc 2，
  与 brief 一致。claim_refs 全量核对：**26 条全部覆盖 brief 指派的 claim id**；
  多处为超集（bi-004/005、bsp-001..003、bc-001、include-002/003、fx-003 补挂语义 id），
  补挂理由已在 task-7c-report 歧义节声明，可追溯性满足全局约束。
- Step 8：test_cases_schema.py 对 26 文件参数化（schema + claim_refs 存在性 + 文件名
  约定 + case_id 唯一），全绿 ✅。
- 机械校验（评审人脚本，26 条全量）：bars 全部满足 h≥max(o,c)、l≤min(o,c)；bi 端点均在
  fx 表内；seg end_bi 不越界。除下述缺陷外无其他数据非法。

**抽查 1 — seg-005（古怪线段，claim-20070906-001-c）✅**：claim 原文"最高/最低点不是
端点的线段可标准化为端点即高低点"。用例构造 B=bi0..bi8（20→…→12，内部 bi3 高 21>起点
20）钉住古怪结构；13 个 pivot 极值与 bar 位置逐一复核相符；特征序列 X1..X6、X4/X5 重合
[13,15.5] 无缺口→第一种情况、seg0 终于 bi8 底（bar37=12.0）的推导与课 78 口径自洽；
seg1（bi9..bi11）首三笔重合 [14,15.5] 成段未破坏 sure=false ✅。expect 推导方向与
claims 原文一致；Segment 模型无区间字段、标准化区间不入 expect 的处理已在头注说明，合理。

**抽查 2 — zs-003（九段升级，claim-20070302-001-b）✅**：claim"延伸不超过 5 段，6 段
延伸+3 段共 9 段构成更大级别中枢"。zs1=[16,17]、zs2=[16.5,18]、zs3=[16.2,17.8] 的
max/min 公式逐一复核相符；三中枢重合 [16.5,17]、level=2、start=5/end=41 与头注及
claim 的 interpretation（每 3 段一个本级别中枢、3 个重合升级、归属唯一）方向一致；
expect 只列升级后结果、中间产物在注释给出，合理。

**抽查 3 — bi-003（77 课区间口径边界，claim-20070905-001-b）⚠️ 推导方向对、样本失效**：
expect 按 ADR-001 暂定默认 A（整个分型区间）写 bi=[]、两分型 sure=false，与 ADR 文档
一致 ✅；但 bars 存在未处理包含（见 Critical-1），判别功能实证失效。

### 全局约束

- 不写引擎实现代码 ✅（交付仅 diff/report/用例/测试；chan.py 完整性见 ⚠️-1，无法独立证实）。
- 每条用例挂真实 claim id ✅（schema 测试强校验 knowledge/claims 全集）。
- 口径仲裁权在原文 ✅（bi-003 按 ADR-001 暂定默认 A 并注明改判 B 需翻转；7c 批次把
  自取约定写入歧义节待裁决——但其中 sure 口径与在先裁定冲突，见 Important-1）。
- 禁止 git 操作 ✅（评审中未见任何提交痕迹，交付物均为未跟踪文件）。
- 数据零外泄 ✅（全部 synthetic 显式 [o,h,l,c]，无外部依赖）。

## 二、质量问题

### Critical

**C-1 BI-002 / BI-003 bars 含未处理相邻包含，A/B 判别样本实证失效。**

- 事实：bi-002 bar2 [9.2,12.3] 包含 bar3 [10.4,11.2]，且向上合并后吞并 bar4 [10.6,11.6]；
  bi-003 bar2 [10.7,12.0] 包含 bar3/bar4（链式），顺序合并后吞并 bar5 [11.2,11.8]。
  按项目自身口径（include/fx 族：分型在包含处理后的序列上确定），bars 2–5/2–4 向上
  合并为一个元素，设计的"顶@4 / 顶@5"不存在，合并元素极值落在 bar2。
- 实证（真实适配器对表）：czsc 在 BI-002/BI-003 均产出 `fx idx=2 up`（expect 无）且缺
  expect 的 `idx=4/5 up`；chanpy 连底分型 idx=1 都不确认。两实现根本遇不到头注设计的
  "区间条件 A/B 判别"（11.8 vs 12.0/11.5）；`bi: []` 虽与实现对表一致，但成因是
  "两分型共用 K 线、无独立 K 线不成笔"，而非头注的"区间条件不满足"。
- 后果：**BI-003 作为 ADR-001"直接证据"的核心用途失效**；BI-002"两口径结论一致"的
  论证路径同样不成立（结论侥幸一致）。
- 修复建议：重推这两条 bars——保留"底分型右肩 K 线抬高合并高"的设计，但让右肩 K 线的
  高不吞并后续反弹各 bar（压缩 bar2 振幅或抬高反弹腿各 bar 低点），使顶分型在包含处理后
  仍落在设计 idx；重推后按 task-7-report 的口径 A/B 双真校验模板复核。

### Important

**I-1 bsp-001..004 / bc-001..002 共 6 条末位 fx/bi `sure: true`，与已裁定口径冲突。**

- 事实：7c 批次自取约定"两端分型第三根 K 线出现即 sure=true"（task-7c-report 构造方法），
  与 model.py 注释（sure=右侧确认，未确认 False）、7a 批次约定（"末尾结构一律
  sure:false"）、以及主 agent 对 seg 族同类问题的在先裁定（task-7-report 追加节：
  未延伸出反向笔 → sure:false）直接冲突。6 条用例的末位 fx 与末位 bi 之后均无反向笔。
- 实证：BSP-001 × czsc 偏差明细正是 `fx idx=31 sure 期望 True 实际 False`、
  `bi (26,31) sure 期望 True 实际 False`——czsc 与既定口径一致，这 6 条 × 2 实现
  的末位 sure 不一致是系统性噪声，会污染 Task 9 校准矩阵。
- 修复建议：同 seg 族修复方式，6 条末位 fx/bi 改 `sure: false`（共 12 处），
  并在 task-7c-report 歧义节#3 标注已按裁定统一。

### Minor

- M-1 bi-002 头注"底分型合并高 12.3（bar2）"按"三根合并最高高"应为 12.5（bar0 h=12.5）；
  结论方向（11.6 < 合并高）不受影响，仅注释数值口径不严谨。
- M-2 task-7c 批次在用例 YAML 加了 expect 白名单外的顶层 `description` 键（schema 宽容
  忽略）。已声明，但建议后续统一：要么纳入 schema 文档说明，要么移除，避免批次间格式漂移。

## 三、⚠️ 项（无法从 B3 材料核实 / 需主控裁决）

1. **chan.py vendor 完整性无法独立证实**：third_party/chanpy 整体为未跟踪目录，无 diff
   基线；全局约束"chan.py 一字不改"本次无法从仓库材料校验（需与上游 vendor 源比对，
   超 B3 评审范围）。
2. **BSP-001/002/003 计划指派 claim 语义错位**（task-7c-report 歧义节#1）：一买挂了
   三买定理 claim-20070105-001-b 等三处，已"保留计划 id + 补挂语义 id"双挂，待主控
   确认维持双挂还是改派并同步修订 brief Step 6。
3. **BSPoint.dir 语义未定**：7c 取"买点=up"，chanpy 输出 dir=down（BSP-001 对表已表现为
   缺/多各 1 条），需 Task 9 仲裁并回写 model.py 注释。
4. **BC 族 MACD 面积断言降级**：expect 五表无法表达面积，bc-001/002 只断言结构结论，
   面积推导在头注；7c 建议加 `meta:` 自由键，待主控裁决（不改 schema 则注释即文档）。
5. 冒烟报告中 chanpy 26 FAIL / czsc 21 FAIL 的逐条明细属 Task 9 校准素材，本评审只
   抽查了与上述缺陷相关的 cell，未逐条核对实现行为。

## 四、结论

- **Spec 合规：✅（交付齐全）** —— Task 6 四 Step、Task 7 八 Step 全部交付，26 条用例
  与 claim 指派、schema 测试、报告模板无缺漏；但随附 C-1/I-1 两处用例数据缺陷需修复。
- **代码质量：Not approved（待两处修复）** —— diff.py/report.py 本身质量合格（真断言、
  容差设计、错误路径、风格与周边一致，可 Approved）；用例数据存在 1 Critical（BI-002/003
  包含污染致判别样本失效）+ 1 Important（6 条末位 sure 口径与在先裁定冲突）+ 2 Minor。
  修复量小（重推 2 条 bars、翻 12 个 sure 标志），修复后复核即可转 Approved。
