# Task 7（族 1-3：包含/分型/笔 + schema 测试）实施报告

负责：Task 7 Step 1/2/3 + Step 8。产出 11 条用例（`src/chan_engine/spec/cases/`）+
`tests/chan_engine/test_cases_schema.py`（新增，未动任何既有文件）。

## 用例清单（每条：case_id / claim_refs / 走势构造思路 / expect 要点）

- **INCLUDE-001** / claim-20070630-001-b / 4 bars 上行，bar2 含于 bar1，向上合并 M=[11.6,10.6]；不合并则无任何分型（bar1 低点低于 bar2 低点，双最高不成立）/ expect：合并后序列恰成顶分型，fx=[{1,up,sure:false}]。
- **INCLUDE-002** / claim-20070630-001-b / 4 bars 下行，bar2 含于 bar1，向下合并 M=[10.2,9.2]；不合并同样无分型 / expect：底分型 fx=[{1,down,sure:false}]。
- **INCLUDE-003** / claim-20070716-001-a + claim-20070630-001-b / 5 bars 上行连续包含：bar2 含于 bar1 → M12=[11.2,10.2]；bar3=[11.15,10.25] **与 bar2 无包含但含于 M12**——只有按课65顺序原则先合并出 M12 才能发现第二次包含，是本族的顺序性判别点 / expect：顶分型 fx=[{1,up,sure:false}]。
- **FX-001** / claim-20070630-001-a / 7 bars 全程无包含，bar1 顶（h/l 双最高）、bar5 底（l/h 双最低），bar3 独立 / expect：fx=[{1,up,sure:true},{5,down,sure:false}]——顶@1 被后续有效向下笔确认，底@5 为末尾未确认结构。
- **FX-002** / claim-20070924-001-c + claim-20070630-001-a / 3 bars 数据结束于顶分型刚成形，右侧无任何 K 线，是否延伸成笔未知 / expect：fx=[{1,up,sure:false}]（sure 语义=右侧确认，model.py 注释口径）。
- **FX-003** / claim-20070630-001-b + claim-20070630-001-a / 4 bars 上行，bar2 **包含** bar1（与 INCLUDE-001 的"后根含于前根"互补），合并高 11.3 来自后一根 bar2 / expect：顶分型 fx=[{2,up,sure:false}]——同时钉住"idx=贡献极值的原始 bar"约定。
- **BI-001** / claim-20070905-001-b / 7 bars 无包含，底@1→顶@5，bar3 独立 K 线，区间条件明显满足 / expect：fx 两条 + bi=[{1,5,up,sure:false}]；底@1 sure:true。
- **BI-002** / claim-20070905-001-b / 底@1 中间 K 线为大区间 [12.0,9.0]，反弹顶@4 中间 K 线 [11.6,10.6] 整体落于其内（"顶都在底的范围内"原文情形）；A/B 两种区间口径下结论一致 / expect：bi=[]（不成笔），两分型 sure:false。
- **BI-003** / claim-20070905-001-b（ADR-001 直接证据）/ 判别样本：底@1 中间 K 线高 11.5 但右侧 K 线（bar2）高 12.0 → 底分型合并高 12.0（口径 A）vs 中间 K 线高 11.5（口径 B）；顶@5 高 11.8 居中：A 下 11.8<12.0 不成笔，B 下 11.8>11.5 成笔 / expect 按 ADR-001 暂定默认 **A**：bi=[]，两分型 sure:false（文件注释已写明若仲裁改判 B 需翻转 expect）。
- **BI-004** / claim-20070716-001-b + claim-20070905-001-b / 11 bars：底@1→顶@5 成立后浅回调（bar6/bar7 间无底分型，11.0>10.9）再创新高成顶@9；课77 步骤二"同性质顶保留更高者、划掉前者"→ 旧顶@5 废止，全段仅一笔 / expect：fx=[{1,down,sure:true},{9,up,sure:false}]，bi=[{1,9,up,sure:false}]；保留@5 的实现将 FAIL。
- **BI-005** / claim-20071217-001-a + claim-20070905-001-b / 11 bars 完整状态链 (1,1)→(1,0)→(-1,1)→(-1,0)：笔 1→5（up，被反向笔确认 sure:true）、笔 5→9（down，延伸中 sure:false）、bar10 走出底@9 右侧仍在构造 / expect：fx 三条 + bi 两条，sure 标记即四状态边界的可执行表达。

## schema 测试结果

- `PYTHONPATH=src .venv/bin/python -m pytest tests/chan_engine/test_cases_schema.py -q` → **30 passed**（11 条本组用例 ×2 参数化测试 + 目录非空 + id 唯一 + 并行组已写入的 BSP-001/002/003 同样全绿，扫描全部、校验全部的目标成立）。
- 逐条 `load_case` 11 个文件全部通过（case_id/bars/expect/claim_refs 打印核对无误）。
- 全仓回归：`PYTHONPATH=src:third_party/chanpy .venv/bin/python -m pytest tests/chan_engine/ -q` → **122 passed**（注：`test_adapter_chanpy.py` 需 `third_party/chanpy` 在 PYTHONPATH 上，为既有环境要求，与本任务无关）。
- 测试文件含命名约定断言（文件名=case_id 小写）与 case_id 全局唯一断言，对后续批次写入同样生效。

## 构造中发现的口径问题与歧义

1. **BI-003 的 ADR-001 处理**：expect 取暂定默认 A（整个分型合并区间比对）。构造时刻意让 A/B 结论相反（顶高 11.8 介于底分型中间 K 线高 11.5 与合并高 12.0 之间），使本用例成为仲裁后的直接证据：若 ADR-001 改判 B，expect.bi 需翻转为 `[{start_idx:1,end_idx:5,dir:up}]`（已在用例注释中注明）。BI-002 则设计为 A/B 下结论一致（均不成笔），保证负例用例不随仲裁翻案。
2. **BI-004 的 claim 锚点偏松**：计划指定 claim-20070716-001-b，其原文实为"线段被笔破坏+线段分解定理"（线段级），"新笔成立旧笔废止"的笔级直接依据是 claim-20070905-001-b 步骤二（同性质分型保留更极端者、划掉前者）。用例挂了两者，以 20070905-001-b 为主要判据；若后续补提取到笔级"破坏充要条件"原文，建议换锚。
3. **分型 idx 约定需归一文档化**：含包含的分型，expect 的 idx 采用"贡献分型极值的原始输入 bar 下标"（INCLUDE-001 极值在前根=1、FX-003 极值在后根=2，两个方向都钉了用例）。chan.py 内部以合并 K 线末端原始下标记分型位置，口径不同——属 Task 9 对表时的预期偏差点，建议在 diff 引擎或适配器归一时统一，而非改 spec。
4. **sure 语义分层**：FX 的 sure 取"是否已被后续结构确认（延伸成笔/走出反向笔）"，Bi 的 sure 取"是否已被反向笔确认"；末尾结构一律 sure:false。BI-005 用两条笔把这层语义写成可执行形式，供对表时核对 chan.py 的 `is_sure` 映射。
5. **构造教训**：初稿 6 处 o（开盘价）越出 [l,h] 被 builders 校验拦下——显式 [o,h,l,c] 记法下 o/c 虽不参与缠论逻辑仍须合法；已全部修正（只动 o，h/l 不变，推导不变）。

## 文件清单

- 新增用例：`src/chan_engine/spec/cases/{include-001,include-002,include-003,fx-001,fx-002,fx-003,bi-001,bi-002,bi-003,bi-004,bi-005}.yaml`
- 新增测试：`tests/chan_engine/test_cases_schema.py`
- 未触碰：`src/chan_engine/` 既有代码、`tests/chan_engine/` 既有测试、`third_party/`；无 git 操作；零外部数据依赖。
