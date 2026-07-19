# Task 6 报告：diff 引擎与报告生成

日期：2026-07-18 ｜ 状态：DONE

## 文件清单

| 文件 | 说明 |
| --- | --- |
| `src/chan_engine/harness/diff.py` | 新建：expect 归一（`expect_to_chart`）+ 逐字段对表（`diff_expect`/`diff_charts`/`diff_table`），机读结果 `ChartDiff`/`TableDiff`/`FieldMismatch` |
| `src/chan_engine/harness/report.py` | 新建：校准矩阵渲染（`render_report`）、用例执行（`run_case`）、CLI `main`（`python -m chan_engine.harness.report`） |
| `tests/chan_engine/test_diff.py` | 新建：19 条测试，先红（collection ERROR）后绿 |
| `tests/chan_engine/test_report.py` | 新建：7 条测试，同上 |
| `.superpowers/sdd/task-6-report.md` | 本报告 |

未触碰 `spec/cases/`（并行 subagent 作业中）、`tests/chan_engine/` 既有文件、`third_party/chanpy/`、两个适配器。全程无 git 操作。

## diff 对齐策略与主键选择

- **比对范围**：只比对 expect 中实际出现的表（子键可选，缺表 = 用例不断言 → `skipped/no-expect`）；`actual.na_fields` 中的表整体跳过（czsc 的 seg/bsp → `skipped/na`）。
- **主键集合对齐**（`TABLE_KEYS`，机读化 Direction → value 字符串）：
  - fx：`(idx, type)` —— 同 idx 不同类型是不同分型；
  - bi：`(start_idx, end_idx, dir)`；seg：`(start_bi, end_bi, dir)`；bsp：`(idx, bstype, dir)`；
  - zs：`(start_idx, end_idx)` —— 按计划，区间值 zd/zg 作为比对字段而非主键（同跨度不同区间值 → 字段不一致，而非缺/多）。
- **对齐语义**：按主键分组（defaultdict），同键多条按组内顺序配对；expect 有 actual 无 → `missing`（缺），反之 → `extra`（多）；命中对逐字段比对（fx/bi/seg 比 `sure`；zs 比 `zd/zg/level/sure`；bsp 比 `level/sure`）。
- **容差**：`tolerance` 参数只作用于 float 字段（zd/zg，`abs(diff) > tolerance` 判异），默认 0 严格；索引/方向/sure/level 永远严格（测试钉住：容差 100 也不掩盖 sure 不一致）。
- **端点差 1 的表现形式**：主键含端点，故"一笔端点差 1"呈现为 `missing (0,5,up)` + `extra (0,6,up)`，偏差定位到表与端点值——这是主键对齐的自然结果，不做位置近似配对（避免 diff 引擎引入口径判断）。

## 测试命令与结果

- `PYTHONPATH=src:third_party/chanpy .venv/bin/python -m pytest tests/chan_engine/test_diff.py tests/chan_engine/test_report.py -q` → **26 passed**
- 回归：`PYTHONPATH=src:third_party/chanpy .venv/bin/python -m pytest tests/chan_engine/ -q` → **126 passed**（含并行的用例 schema 测试，无破坏）

## CLI 用法与自测结果

Task 9 Step 1 原样可用：

```
PYTHONPATH=src:third_party/chanpy .venv/bin/python -m chan_engine.harness.report \
    --cases src/chan_engine/spec/cases --golden src/chan_engine/spec/golden \
    --out docs/design/chanlun-calibration-report.md
```

- `--golden` 可选；`--tolerance` 默认 0。退出码：0 正常 / 1 目录或用例问题 / 2 适配器不可用。
- 自测（临时目录 `/tmp/chan_toy`，未污染正式 cases）：2 条 toy 用例（expect 空 → PASS；expect 虚构笔 → FAIL）+ 1 条 golden → 两真实适配器各 `PASS 2 / FAIL 1 / ERROR 0`，报告含矩阵（来源列区分 case/golden）、统计、偏差明细（缺/多元素全字段列出）、偏差条目模板（chan.py 行为 / czsc 行为 + 三项占位）。
- 错误路径：`PYTHONPATH=src`（无 third_party/chanpy）→ stderr 打印「无法导入 chan_engine.harness.adapter_chanpy（No module named 'Chan'）+ 正确运行姿势」，退出码 2，无栈 trace、不写出文件。
- 适配器 `run()` 抛异常 → 该 cell 记 ERROR（`类型: 消息`）并继续整批（单测用爆炸假适配器钉住）。

## 设计决策

1. **expect 归一放在 diff 层**（`expect_to_chart`）：case_io 按计划只保原始 dict；diff 层校验表名/字段名/方向值，非法输入抛 `ValueError` 带 `expect.bi[i]` 定位，CLI 在跑适配器前预检（用例错误 → 退出码 1 清晰报错，不伪装成实现偏差）。
2. **`main(argv, *, adapters=None)` 依赖注入**：单测用内存假适配器覆盖 PASS/FAIL/ERROR 全路径，真实适配器懒加载（`_default_adapters`/`_load_adapter`），故 report 单测不需要 czsc/Chan 可导入。
3. **偏差条目按 case 聚合**（非按 cell）：一条 case 任一 impl 非 PASS 即生成条目，chan.py/czsc 行为并列一行摘要（PASS 一致 / FAIL 缺多统计 / ERROR 消息），【原文依据/仲裁结论/M2 改造点】留 `【待 Task 9 人工填写】` 占位。
4. **矩阵列为动态 impl 顺序**（按首次出现），不止 chanpy/czsc 两个名字也能渲染；`—` 表示该 case 缺此 impl 的 cell。
5. **同主键多条配对**：ZS 主键 (start_idx,end_idx) 理论上可撞（不同 level 同跨度），按组内顺序配对、余者入缺/多，不静默覆盖。

## 疑虑点

1. **BSP 主键 `(idx, bstype, dir)` 系自行决定**（计划只给了 bi/FX/ZS 的主键）：同位置同类买卖点方向不同视为两个点；若 Task 9 评审认为方向应作比对字段，改 `TABLE_KEYS`/`_TABLE_FIELDS` 一行即可。
2. **expect 缺表 = 跳过**（而非视为空表）：若某用例想断言"无笔"，需显式写 `bi: []`；该语义已写进 diff.py docstring 与测试。
3. `expect` 里 `bi:`（YAML 空值 → None）按空列表处理，属宽容解析，已在代码注释说明。
