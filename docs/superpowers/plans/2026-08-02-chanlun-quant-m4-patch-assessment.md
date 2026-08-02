# chanlun-quant M4 降级项补丁评估（Patch Assessment）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 对 M3 收官后保持降级的 8 项（chanpy PATCHES 4 + czsc 局限 4）逐项产出「改源码 / 适配器补偿 / 永久降级」三选一评估结论与爆炸半径分析，写入 `docs/design/chanlun-m4-patch-assessment.md`，供 UP 逐项拍板。

**Architecture:** M4 是**只读评估里程碑**——不改 chanpy/czsc 源码、不改生产代码。每项按统一模板评估：根因复核（引用 PATCHES.md 既有排查）→ /tmp 探针实证（复现偏差 + 定位源码判定点）→ 爆炸半径（受影响代码路径被哪些 PASS 用例共享）→ 三选一建议。探针脚本全部放 `/tmp`，不进 git。

**Tech Stack:** Python 3.11（`.venv/bin/python`）、`PYTHONPATH=src:third_party/chanpy`、pytest、harness（`chan_engine.harness.report` / `spec.case_io.load_case`）。

## Global Constraints

- **M4 全程不改 `third_party/chanpy/` 与 czsc（pip 0.10.12）源码**；任何补丁实施属后续里程碑，需 UP 逐项批准后另行立项。
- 探针脚本只放 `/tmp/m4_*.py`，不进 git、不进 tests/。
- 运行前缀统一：`PYTHONPATH=src:third_party/chanpy .venv/bin/python`（py3.11）。
- 禁止 git 提交类操作（只读 git 可用），除非用户显式授权。
- 回归基线（每个 Task 结束时复跑确认不被破坏）：**198 测试全绿；chanpy 23 PASS / czsc 25 PASS / recursion 18 PASS**。
- 评估报告：`docs/design/chanlun-m4-patch-assessment.md`，每项一节，字段固定为：根因复核 / 探针实证 / 爆炸半径 / 建议（三选一）/ UP 决策（留空待填）。

## 8 项降级清单（权威来源：`docs/design/chanlun-calibration-report.md` 第 79-91 行 + `third_party/chanpy/PATCHES.md`）

| # | 降级项 | 归因 | 涉及源码 |
|---|--------|------|----------|
| 1 | SEG-004/005 × chanpy（2 项） | EigenFX seg 算法拆段口径（P-F） | `third_party/chanpy/Seg/EigenFX.py`（`can_be_end`:82 / `find_revert_fx`:159） |
| 2 | BSP-004 × chanpy（1 项） | 三买判定不覆盖"二三类重合"（P-K） | `third_party/chanpy/BuySellPoint/BSPointList.py`（`cal_seg_bs3point`:297） |
| 3 | ZS-003 × chanpy（1 项） | 跨 seg 九段升级被拒（P-K） | `third_party/chanpy/ZS/ZS.py`（`combine`:115-118） |
| 4 | BI-004 × czsc（1 项） | rust 后端 min_bi_len=6 + 不实现课77步骤二（P-J） | czsc 库内部（pip 安装，非 vendor） |
| 5 | BSP-002/004 × czsc（2 项） | czsc 无 seg，zs 延伸受限 | czsc 库内部 |
| 6 | GOLD-005 × czsc（1 项） | czsc zs 构造口径（中枢起始笔判定，P-K） | czsc 库内部 |

---

### Task M4-0: 评估报告骨架 + PATCHES.md 补丁政策节

**Files:**
- Create: `docs/design/chanlun-m4-patch-assessment.md`
- Modify: `third_party/chanpy/PATCHES.md:1-6`（文件头政策说明区）

**Interfaces:**
- Consumes: 8 项降级清单（上文表格）；PATCHES.md 既有 M2-5 排查结论。
- Produces: 报告骨架（6 节，每项预填"根因复核"字段），后续 Task 逐节填充；PATCHES.md 头部新增"补丁前提"政策段。

- [ ] **Step 1: 写评估报告骨架**

创建 `docs/design/chanlun-m4-patch-assessment.md`，内容：

```markdown
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
```

- [ ] **Step 2: PATCHES.md 头部加补丁政策段**

在 `third_party/chanpy/PATCHES.md` 第 5 行（"以下补丁条目…补充。"）之后插入：

```markdown
> M4 补丁前提（2026-08-02 UP 决策立 M4）：任何 chanpy 源码改动须满足——
> (1) 该项评估报告（docs/design/chanlun-m4-patch-assessment.md）建议为 A 且 UP 逐项批准；
> (2) 改动前在下表登记"原行为/改后行为/claim id/用例 id"四列；
> (3) 改动后全量回归：198+ 测试全绿且 chanpy 23 PASS 不降、czsc 25 PASS 不降、recursion 18 PASS 不降；
> (4) 补丁以最小 diff 实现，禁止顺手重构 vendor 代码。
```

- [ ] **Step 3: 验证基线未动**

Run: `PYTHONPATH=src:third_party/chanpy .venv/bin/python -m pytest tests/chan_engine/ -q 2>&1 | tail -1`
Expected: `198 passed`

- [ ] **Step 4: 提交**（需用户当场授权 git）

```bash
git add docs/design/chanlun-m4-patch-assessment.md third_party/chanpy/PATCHES.md docs/superpowers/plans/2026-08-02-chanlun-quant-m4-patch-assessment.md
git commit -m "docs(chan-engine): M4-0 补丁评估骨架 + PATCHES 政策段"
```

---

### Task M4-1: SEG-004/005 × EigenFX 评估（P-F）

**Files:**
- Create: `/tmp/m4_probe_seg.py`（探针，不进 git）
- Modify: `docs/design/chanlun-m4-patch-assessment.md`（填第 1 节）

**Interfaces:**
- Consumes: `chan_engine.spec.case_io.load_case`（签名 `load_case(path) -> Case`，`Case.bars: list[Bar]`，`Case.expect: dict`）；`ChanPyAdapter().run(bars) -> NormalizedChart`（`NormalizedChart.seg: list[Segment]`，`Segment(start_bi, end_bi, dir, sure)`，`spec/model.py:67-74`）。
- Produces: 报告第 1 节"探针实证/爆炸半径/建议"三字段。

- [ ] **Step 1: 写探针复现偏差**

写 `/tmp/m4_probe_seg.py`：

```python
"""M4-1 探针：SEG-004/005 chanpy seg 输出 vs expect。"""
from chan_engine.spec.case_io import load_case
from chan_engine.harness.adapter_chanpy import ChanPyAdapter

for cid in ("seg-004", "seg-005"):
    case = load_case(f"src/chan_engine/spec/cases/{cid}.yaml")
    chart = ChanPyAdapter().run(case.bars)
    print(f"== {cid} ==")
    print("expect seg:", case.expect.get("seg"))
    for s in chart.seg:
        print(f"  chanpy seg: start_bi={s.start_bi} end_bi={s.end_bi} dir={s.dir.name} sure={s.sure}")
    print("  bi count:", len(chart.bi))
```

Run: `PYTHONPATH=src:third_party/chanpy .venv/bin/python /tmp/m4_probe_seg.py`
Expected: 打印两用例 expect seg 与 chanpy seg 的逐段对照（偏差点肉眼可见：拆段位置/段数差异）。

- [ ] **Step 2: 定位 EigenFX 判定点**

读 `third_party/chanpy/Seg/EigenFX.py` 的 `can_be_end`（:82）与 `find_revert_fx`（:159），结合探针输出的差异段，回答：段终结判定在哪一步与 expect 特征序列口径分叉（第一/第二/第三元素处理 `treat_first_ele`/`treat_second_ele`/`treat_third_ele`，还是 `actual_break`:117 的反向确认）。把分叉点函数名+行号写入报告。

- [ ] **Step 3: 爆炸半径分析**

列出 chanpy 23 个 PASS 用例中哪些走 seg 路径（seg/zs/bsp 均依赖 seg 切分）：

Run: `grep -l '"seg"' src/chan_engine/spec/cases/*.yaml src/chan_engine/spec/golden/*.yaml | sort`
并参照 `docs/design/chanlun-calibration-report.md` 偏差明细节，数出修改 EigenFX 后需要逐一复跑的 chanpy PASS 用例数（粗粒度口径：**全部 23 个 chanpy PASS 都在半径内**，因为 seg 是 zs/bsp 的上游）。写入报告。

- [ ] **Step 4: 填报告第 1 节并给建议**

建议判据：若分叉点可用「新增配置项」隔离（默认关，仅 SEG-004/005 类语料开）→ 建议 A；若需改动默认行为且 23 个 PASS 中任何一个翻转 → 建议 C（ADR-009 的 recursion L0 已提供替代路径）。把建议与判据写入报告。

- [ ] **Step 5: 回归基线复跑**

Run: `PYTHONPATH=src:third_party/chanpy .venv/bin/python -m pytest tests/chan_engine/ -q 2>&1 | tail -1`
Expected: `198 passed`（本 Task 只写 /tmp 探针与报告，不应有任何变化）

- [ ] **Step 6: 提交**（需用户当场授权 git）

```bash
git add docs/design/chanlun-m4-patch-assessment.md
git commit -m "docs(chan-engine): M4-1 SEG-004/005 EigenFX 评估"
```

---

### Task M4-2: BSP-004 × chanpy 三买「二三类重合」评估（P-K）

**Files:**
- Create: `/tmp/m4_probe_bsp3.py`
- Modify: `docs/design/chanlun-m4-patch-assessment.md`（填第 2 节）

**Interfaces:**
- Consumes: 同 M4-1 的 load_case/ChanPyAdapter；`NormalizedChart.bsp: list[BSPoint]`、`NormalizedChart.zs: list[ZhongShu]`（`spec/model.py:78-84`，字段 `zd/zg/start_idx/end_idx`）；`BSPointList.cal_seg_bs3point`（`BuySellPoint/BSPointList.py:297`）。
- Produces: 报告第 2 节三字段。

- [ ] **Step 1: 写探针复现偏差**

写 `/tmp/m4_probe_bsp3.py`：

```python
"""M4-2 探针：BSP-004 chanpy bsp 输出 vs expect（二三类重合@36）。"""
from chan_engine.spec.case_io import load_case
from chan_engine.harness.adapter_chanpy import ChanPyAdapter

case = load_case("src/chan_engine/spec/cases/bsp-004.yaml")
chart = ChanPyAdapter().run(case.bars)
print("expect bsp:", case.expect.get("bsp"))
print("expect zs:", case.expect.get("zs"))
for b in chart.bsp:
    print(f"  chanpy bsp: {b}")
for z in chart.zs:
    print(f"  chanpy zs: zd={z.zd} zg={z.zg} start={z.start_idx} end={z.end_idx}")
```

Run: `PYTHONPATH=src:third_party/chanpy .venv/bin/python /tmp/m4_probe_bsp3.py`
Expected: 可见 chanpy 报一买@26+二买@36、缺三买@36；zs 的 ZG 与 bar36 回试低点关系可核对。

- [ ] **Step 2: 判定适配器补偿可行性**

读 `BSPointList.py:297` 起的 `cal_seg_bs3point` 与 `treat_bsp3`（同文件 297 之后），回答：三买漏报是因为「三买须晚于二买」的时序约束，还是「回试笔与二买同笔」被去重。若适配器层能以后处理补上（检测：存在二买@X 且二买回试低点 > 最近中枢 ZG → 追加三买@X），则建议 B（不动 vendor）；若判定信息在归一表之外（需要 seg 内部状态）则建议 A。参照既有先例：`adapter_chanpy.py` 的 bsp 末位笔过滤（M2-3）就是 B 类补偿。

- [ ] **Step 3: 爆炸半径分析**

三买判定路径影响的 chanpy PASS 用例：BSP-001/002/003、GOLD-003/004/005（凡 expect 含 bsp 的用例）。逐一列出并写入报告；补偿逻辑若严格限定「二三类重合」形态，理论半径=0（新形态此前无输出）。

- [ ] **Step 4: 填报告第 2 节并给建议**

- [ ] **Step 5: 回归基线复跑**

Run: `PYTHONPATH=src:third_party/chanpy .venv/bin/python -m pytest tests/chan_engine/ -q 2>&1 | tail -1`
Expected: `198 passed`

- [ ] **Step 6: 提交**（需用户当场授权 git）

```bash
git add docs/design/chanlun-m4-patch-assessment.md
git commit -m "docs(chan-engine): M4-2 BSP-004 三买二三类重合评估"
```

---

### Task M4-3: ZS-003 × chanpy 跨 seg 九段升级评估（P-K）

**Files:**
- Create: `/tmp/m4_probe_zs9.py`
- Modify: `docs/design/chanlun-m4-patch-assessment.md`（填第 3 节）

**Interfaces:**
- Consumes: `ZS.combine`（`third_party/chanpy/ZS/ZS.py:115-118`）；参照实现 `adapter_czsc.py` 的 `_apply_nine_bi_upgrade()`（M2-3 已落地，czsc ZS-003 PASS）；`NormalizedChart.zs`。
- Produces: 报告第 3 节三字段。

- [ ] **Step 1: 写探针复现偏差**

写 `/tmp/m4_probe_zs9.py`：

```python
"""M4-3 探针：ZS-003 chanpy zs/seg 输出 vs expect（九段升级 level=2）。"""
from chan_engine.spec.case_io import load_case
from chan_engine.harness.adapter_chanpy import ChanPyAdapter

case = load_case("src/chan_engine/spec/cases/zs-003.yaml")
chart = ChanPyAdapter().run(case.bars)
print("expect zs:", case.expect.get("zs"))
for s in chart.seg:
    print(f"  seg: start_bi={s.start_bi} end_bi={s.end_bi} dir={s.dir.name}")
for z in chart.zs:
    print(f"  zs: zd={z.zd} zg={z.zg} start={z.start_idx} end={z.end_idx}")
print("  bi count:", len(chart.bi))
```

Run: `PYTHONPATH=src:third_party/chanpy .venv/bin/python /tmp/m4_probe_zs9.py`
Expected: 可见 chanpy zs end=17 受 seg 切分限制，未升级 level=2。

- [ ] **Step 2: 对比两条改法**

- 改法 1（A，改 vendor）：放宽 `ZS.combine` 的 seg 一致性检查（ZS.py:118）或新增跨 seg 合并模式——评估该检查在 `ZSList` 更新循环中被多少路径依赖。
- 改法 2（B，适配器后处理）：把 czsc 适配器的 `_apply_nine_bi_upgrade()` 移植到 `adapter_chanpy.py`（中枢范围笔数≥9 → 分 3 组子中枢 → 重合区间升级 level=2）。该改法不动 vendor，先例已成功（czsc ZS-003 +1 PASS 零回归）。
- 默认倾向 B；仅当 B 因 chanpy zs 表信息不足（缺 seg 内笔归属）不可行时才评 A。

- [ ] **Step 3: 爆炸半径分析**

B 类后处理仅在「zs 内笔数≥9」触发——统计全量 31 用例中 chanpy zs 内笔数≥9 的用例数（预期仅 ZS-003），半径=触发用例集合。把统计命令与结果写入报告：

Run: `PYTHONPATH=src:third_party/chanpy .venv/bin/python -c "from chan_engine.spec.case_io import load_case; from chan_engine.harness.adapter_chanpy import ChanPyAdapter; import glob; [print(p, [ (z.start_idx,z.end_idx) for z in ChanPyAdapter().run(load_case(p).bars).zs]) for p in sorted(glob.glob('src/chan_engine/spec/cases/*.yaml'))]" 2>&1 | grep -v "zs: \[\]" | head -40`

- [ ] **Step 4: 填报告第 3 节并给建议**

- [ ] **Step 5: 回归基线复跑**

Run: `PYTHONPATH=src:third_party/chanpy .venv/bin/python -m pytest tests/chan_engine/ -q 2>&1 | tail -1`
Expected: `198 passed`

- [ ] **Step 6: 提交**（需用户当场授权 git）

```bash
git add docs/design/chanlun-m4-patch-assessment.md
git commit -m "docs(chan-engine): M4-3 ZS-003 九段升级评估"
```

---

### Task M4-4: czsc 局限 4 项评估（BI-004 / BSP-002/004 / GOLD-005）

**Files:**
- Create: `/tmp/m4_probe_czsc.py`
- Modify: `docs/design/chanlun-m4-patch-assessment.md`（填第 4/5/6 节）

**Interfaces:**
- Consumes: `chan_engine.harness.adapter_czsc.CzscAdapter`（`adapter_czsc.py:250`，已验证 `CzscAdapter().run(case.bars)` 可用）；czsc 0.10.12（pip 安装，非 vendor——**补丁策略与 chanpy 不同**：改 site-packages 不可持续，选项为 B=适配器补偿 / C=永久降级 / D=pin 版本+fork，D 需 UP 单独拍板）。
- Produces: 报告第 4/5/6 节三字段。

- [ ] **Step 1: 写探针复现 4 项偏差**

写 `/tmp/m4_probe_czsc.py`：

```python
"""M4-4 探针：BI-004 / BSP-002 / BSP-004 / GOLD-005 czsc 输出 vs expect。"""
from chan_engine.spec.case_io import load_case
from chan_engine.harness.adapter_czsc import CzscAdapter

for path in ("src/chan_engine/spec/cases/bi-004.yaml",
             "src/chan_engine/spec/cases/bsp-002.yaml",
             "src/chan_engine/spec/cases/bsp-004.yaml",
             "src/chan_engine/spec/golden/gold-005.yaml"):
    case = load_case(path)
    chart = CzscAdapter().run(case.bars)
    print(f"== {case.case_id} ==")
    for key in ("bi", "zs", "bsp"):
        print(f"  expect {key}:", case.expect.get(key))
    print("  czsc bi:", [(b.start_idx, b.end_idx, b.dir.name) for b in chart.bi])
    print("  czsc zs:", [(z.zd, z.zg, z.start_idx, z.end_idx) for z in chart.zs])
    print("  czsc bsp:", list(chart.bsp))
    print("  na_fields:", chart.na_fields)
```

Run: `PYTHONPATH=src:third_party/chanpy .venv/bin/python /tmp/m4_probe_czsc.py`
Expected: 4 用例偏差逐项可见（BI-004 bi 空或 3 笔；BSP-002/004 zs 延伸/bsp 缺口；GOLD-005 zs 起始笔差异）。
（路径已验证：`src/chan_engine/spec/golden/gold-005.yaml` 存在；bi-004 探针冒烟通过，czsc bi 输出为空，与 P-J 根因一致。）

- [ ] **Step 2: 逐项判定补偿可行性**

- BI-004：课77步骤二消解属**分型/笔构造层**补偿——评估在 `adapter_czsc.py` 自建成笔逻辑的成本（≈重写 czsc 核心）vs 永久降级。参照 ADR-010：recursion 列 BI-004 已 PASS（笔构造复用 chanpy 适配器），czsc 列该项的边际价值=单级别库对表完整性。
- BSP-002/004：无 seg 延伸是 czsc 架构性缺失，适配器层已在 M2-3 做过"末位不延伸"修正；继续补偿=在适配器自建 seg——与 recursion 层职责重叠，评估是否值得。
- GOLD-005：中枢起始笔判定（P-K）涉及走势类型判定算法，czsc 适配器 `_recompute_zs` 无法表达；评估"按用例配置起始笔"是否违反校准门公平性（语料专属 if=作弊，不可接受）。

- [ ] **Step 3: 爆炸半径分析**

czsc 25 个 PASS 用例中，凡走 `_recompute_zs` 的都在半径内。统计 czsc PASS 中含 zs expect 的用例数写入报告（参照 `docs/design/chanlun-calibration-report.md` 矩阵）。

- [ ] **Step 4: 填报告第 4/5/6 节并给建议**

每项明确三选一（含 D 选项时的理由）。czsc 项默认倾向 C（永久降级，登记附录 C.5），除非补偿逻辑可严格限定形态且半径=0。

- [ ] **Step 5: 回归基线复跑**

Run: `PYTHONPATH=src:third_party/chanpy .venv/bin/python -m pytest tests/chan_engine/ -q 2>&1 | tail -1`
Expected: `198 passed`

- [ ] **Step 6: 提交**（需用户当场授权 git）

```bash
git add docs/design/chanlun-m4-patch-assessment.md
git commit -m "docs(chan-engine): M4-4 czsc 局限 4 项评估"
```

---

### Task M4-5: 汇总 + 基线复跑 + UP 决策门

**Files:**
- Modify: `docs/design/chanlun-m4-patch-assessment.md`（填第 7 节）
- Modify: `.superpowers/sdd/progress.md`（追加 M4 状态行）
- Modify: `docs/design/chanlun-quant-engine.md` 附录 C.5（仅对建议为 C 的项，登记"经 M4 评估永久降级"）

**Interfaces:**
- Consumes: M4-1~M4-4 填好的 6 节。
- Produces: 第 7 节汇总表（8 项 × 建议/半径/预期收益）；UP 决策门问题清单。

- [ ] **Step 1: 全量校准矩阵复跑**

Run: `PYTHONPATH=src:third_party/chanpy .venv/bin/python -m chan_engine.harness.report --cases src/chan_engine/spec/cases --golden src/chan_engine/spec/golden --out /tmp/m4-final-report.md 2>&1 | tail -4`
Expected: `chanpy: PASS 23` / `czsc: PASS 25` / `recursion: PASS 18`，ERROR 0。

Run: `PYTHONPATH=src:third_party/chanpy .venv/bin/python -m pytest tests/chan_engine/ -q 2>&1 | tail -1`
Expected: `198 passed`

- [ ] **Step 2: 填报告第 7 节汇总表**

格式：

```markdown
| 降级项 | 建议 | 爆炸半径 | 预期收益 | UP 决策 |
|--------|------|----------|----------|---------|
| SEG-004/005 × chanpy | ? | ? | chanpy +2 PASS | 待填 |
| BSP-004 × chanpy | ? | ? | chanpy +1 PASS | 待填 |
| ZS-003 × chanpy | ? | ? | chanpy +1 PASS | 待填 |
| BI-004 × czsc | ? | ? | czsc +1 PASS | 待填 |
| BSP-002/004 × czsc | ? | ? | czsc +2 PASS | 待填 |
| GOLD-005 × czsc | ? | ? | czsc +1 PASS | 待填 |
```

- [ ] **Step 3: 附录 C.5 登记永久降级项**

仅对建议 C 的项，在 `docs/design/chanlun-quant-engine.md` 附录 C.5 追加一行："经 M4 评估（chanlun-m4-patch-assessment.md 第 N 节）定为永久降级，理由：…"。建议 A/B 的项不动附录。

- [ ] **Step 4: progress.md 追加 M4 状态**

在 `.superpowers/sdd/progress.md` 末尾追加：

```markdown
M4 补丁评估 (plan: docs/superpowers/plans/2026-08-02-chanlun-quant-m4-patch-assessment.md): done YYYY-MM-DD
  - 8 项评估结论见 docs/design/chanlun-m4-patch-assessment.md 第 7 节汇总表
  - 基线复跑: 198 测试全绿; chanpy 23 / czsc 25 / recursion 18 不变
  - 待 UP: 汇总表逐项拍板（A 项另立补丁实施里程碑）
```

- [ ] **Step 5: 向 UP 呈决策门**

用 AskUserQuestion 逐项（或按 A/B/C 分组）呈汇总表请 UP 拍板；A 项批准后才另立补丁实施计划（新 plan 文档，不在本计划范围）。

- [ ] **Step 6: 提交**（需用户当场授权 git）

```bash
git add docs/design/chanlun-m4-patch-assessment.md .superpowers/sdd/progress.md docs/design/chanlun-quant-engine.md
git commit -m "docs(chan-engine): M4-5 补丁评估收官——汇总表+决策门"
```

---

## Self-Review 记录

- **Spec 覆盖**：8 项降级 ↔ Task M4-1（2 项 SEG）/ M4-2（BSP-004）/ M4-3（ZS-003）/ M4-4（4 项 czsc），第 7 节汇总全覆盖；UP 决策门 = M4-5 Step 5。
- **占位符扫描**：报告中"待填"是评估任务的交付物本身（由对应 Task 填充），非计划缺陷；所有探针脚本含完整可运行代码。
- **类型一致性**：探针统一使用 `load_case(path) -> Case{bars, expect, case_id}`、`ChanPyAdapter().run(bars) -> NormalizedChart{fx, bi, seg, zs, bsp, na_fields}`，字段名与 `src/chan_engine/spec/model.py`（Bar:34 / Segment:67 / ZhongShu:78 / NormalizedChart:111）逐一核对一致；`CzscAdapter`（`adapter_czsc.py:250`）与 golden 路径已冒烟验证（bi-004 探针实跑通过）。
