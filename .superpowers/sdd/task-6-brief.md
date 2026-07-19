## Task 6: diff 引擎与报告生成

**Files:**
- Create: `src/chan_engine/harness/diff.py`、`src/chan_engine/harness/report.py`
- Test: `tests/chan_engine/test_diff.py`、`tests/chan_engine/test_report.py`

- [ ] **Step 1: 先写测试** — 构造 expect 与两份人工输出：全一致→PASS；一笔端点差 1→FAIL 且 diff 指明字段；N/A 字段跳过比对。
- [ ] **Step 2: 实现 diff.py** — 序列对齐策略：按 `(start_idx,end_idx,dir)` 主键对齐，缺/多元素单列；容差=0（严格），容差设计留参数。
- [ ] **Step 3: 实现 report.py** — 校准矩阵（case_id × impl × PASS/FAIL + diff 详情）渲染 markdown；汇总偏差条目模板：【规则源 claim / chan.py 行为 / czsc 行为 / 原文依据 / 仲裁结论 / M2 改造点】。
- [ ] **Step 4: 全绿**

