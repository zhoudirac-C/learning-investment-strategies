## Task 7: 用例族编写（26 条，可并行）

**Files:**
- Create: `src/chan_engine/spec/cases/*.yaml`
- Test: `tests/chan_engine/test_cases_schema.py`（全部用例过 schema+claim_refs 校验）

> 每条用例：bars 用 builders 紧凑记法人工设计，expect 按 claims 原文推出。**先读对应 claim 原文再写**（`knowledge/claims/` 按课号检索）。

- [ ] **Step 1: 包含族（3 条）** — INCLUDE-001 向上合并（`claim-20070630-001-b`）；INCLUDE-002 向下合并；INCLUDE-003 连续包含顺序处理（`claim-20070716-001-a`）
- [ ] **Step 2: 分型族（3 条）** — FX-001 顶/底分型识别（`claim-20070630-001-a`）；FX-002 右侧确认前 sure=False（`claim-20070924-001-c`）；FX-003 含包含处理后的分型
- [ ] **Step 3: 笔族（5 条）** — BI-001 基本成笔（`claim-20070905-001-b`）；BI-002 区间条件不满足不成笔；BI-003 77 课"区间"口径边界（ADR-001 直接证据，`claim-20070905-001-b`）；BI-004 新笔成立旧笔废止（`claim-20070716-001-b`）；BI-005 笔定理四状态迁移（`claim-20071217-001-a`）
- [ ] **Step 4: 线段族（5 条）** — SEG-001 三笔重叠成段（`claim-20070905-001-c`）；SEG-002 特征序列无缺口即确认（`claim-20070801-001-a`）；SEG-003 有缺口需反向分型确认（`claim-20070816-001-b`）；SEG-004 一笔不破坏线段（`claim-20070702-002-a`）；SEG-005 古怪线段标准化（`claim-20070906-001-c`）
- [ ] **Step 5: 中枢族（4 条）** — ZS-001 三段重叠区间公式（`claim-20061218-001-b`+`claim-20061226-001-a`）；ZS-002 中枢延伸（`claim-20061226-001-b`）；ZS-003 九段升级（`claim-20070302-001-b`）；ZS-004 趋势两中枢不重叠（`claim-20061226-001-c`）
- [ ] **Step 6: 买卖点族（4 条）** — BSP-001 一类（背驰点，`claim-20070105-001-b`+`claim-20070109-001-a`）；BSP-002 二类（`claim-20071024-001-b` 介入程序）；BSP-003 三类 ZG/ZD 回试（`claim-20070109-001-b`）；BSP-004 二三类重合（`claim-20070109-001-b`）
- [ ] **Step 7: 背驰族（2 条）** — BC-001 MACD 面积背驰（`claim-20070118-001-a`）；BC-002 区间套多级定位（`claim-20070202-001-c`，synthetic 两层）
- [ ] **Step 8: `pytest tests/chan_engine/test_cases_schema.py` 全绿**（只验格式，不验实现对错）

