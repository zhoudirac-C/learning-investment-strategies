# M3 级别递归层（LevelTree）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 自建级别递归层，消费单级别层归一表（bi），按课 35/84 递归口径合成多级中枢与买卖点，使 M2 降级的 6 个用例（BC-002×2、BSP-003×2、GOLD-001/002）通过校准门。

**Architecture:** 递归层独立于两库自建（两库均无此物）。核心发现：**不能依赖适配器的 seg 表**——chanpy 对 BC-002 把 9 笔并成 1 段（seg=[(0,8,down)]），破坏了 A2/B2/C2 三段结构；czsc 干脆无 seg。因此递归层自己从归一 bi 表分组 L0 走势类型（线段），再逐级上推：L0 → 进入段/中枢段/离开段 → level-2 中枢（复用附录 C.4 三笔重叠口径）→ 3×L_N 重叠 → L_{N+1}。f1(a0)=a1 启始规则可配（默认 a0=线段），f2 生长规则不变。

**Tech Stack:** Python 3.13（.venv）、pytest、`PYTHONPATH=src:third_party/chanpy`；纯自建，无新依赖。

---

## 约束与基线

- TDD：先写失败测试（Red）→ 实现（Green）→ 重构；禁止先实现后补测
- `.venv`（py3.13）；`PYTHONPATH=src:third_party/chanpy`
- chan.py 源码只读（third_party/chanpy/ 不动；递归层全部落在 `src/chan_engine/core/`）
- 测试基线：**168 全绿**（M2 收官态，0717b59）
- 校准门现状：**48/62 PASS (77%)**；6 个 M3 降级项见下
- M3-6 之前禁止重生成 chanlun-calibration-report.md（测量用 `--out /tmp/m3-report.md`）

## M3 降级项（验收目标）

| 用例 | 实现 | 现状 | 根因 | M3 目标 |
|------|------|------|------|---------|
| BC-002 | chanpy | FAIL | 无 level=2 zs；seg 九并一 | level=2 zs + 双一买 |
| BC-002 | czsc | FAIL | 无 seg，无法 level=2 | 自建 L0 → level=2 |
| BSP-003 | chanpy | FAIL | 三买未检出（中枢构造不含引导笔） | 走势类型判定 → 三买 |
| BSP-003 | czsc | FAIL | 同上 + 无 seg | 同上 |
| GOLD-001 | 两实现 | FAIL | 真实日线笔太少（1-3 笔）无 zs | 多级别笔划分 / 降级结论 |
| GOLD-002 | 两实现 | FAIL | 同上 | 同上 |

## 递归口径（课 35/84 + BC-002 expect 实证）

**LevelTree**：
```
归一 bi 表（level-1 原子）
  → [segments.py] L0 走势类型（线段，A2/B2/C2）
  → [levels.py] 进入段+中枢段+离开段 → level-2 中枢 → level-2 走势类型
  → [levels.py 递归] 3×L_2 走势类型重叠 → level-3 中枢 → …
```

**BC-002 实证（算法口径来源）**：
- L0 分组：A2=bi0-2（下-上-下）、B2=bi3-5（上-下-上）、C2=bi6-8（下-上-下），段方向交替
- level-2 zs = **中枢段 B2 内 3 笔重叠** = overlap(bi3,bi4,bi5) = [23.9, 26.2], idx 16→31
- level-1 zs = 离开段 C2 内次级别重叠 = overlap(bi6,bi7,bi8) ≈ [22.9, 24.4], idx 31→46
- 背驰（面积代理 Σ|Δc|）：A2=10.84 > C2=6.04 → level-2 一买@46；C2 内 a1=2.88 > c1=2.08 → level-1 一买@46
- **关键**：level 字段标记的是中枢在递归中扮演的角色（level-2=大级别走势类型的中枢），不只是构造它的笔的层级

**sure 透传**：末位 L0 段（含未确认笔）sure=False；中枢/买卖点形成即 sure=True（附录 C.1）

---

## 文件结构

| 文件 | 职责 |
|------|------|
| `src/chan_engine/core/__init__.py` | 包导出 |
| `src/chan_engine/core/model.py` | L0 走势类型（SegType）、LevelZhongShu、LevelBSPoint 数据容器 |
| `src/chan_engine/core/segments.py` | bi 表 → L0 走势类型分组（自建线段划分） |
| `src/chan_engine/core/levels.py` | L0 → 多级中枢/走势类型合成（LevelTree 递归） |
| `src/chan_engine/core/backchi.py` | 背驰判断（Σ\|Δc\| 面积代理）+ 买卖点生成 |
| `src/chan_engine/core/engine.py` | 顶层：归一 bi 表 → 多级 zs/bsp，供适配器/校准门调用 |
| `tests/chan_engine/test_core_segments.py` | L0 分组测试 |
| `tests/chan_engine/test_core_levels.py` | 多级中枢测试（BC-002 为锚） |
| `tests/chan_engine/test_core_backchi.py` | 背驰/买卖点测试 |
| `tests/chan_engine/test_core_engine.py` | 引擎集成 + 6 降级用例 |

---

## 任务分解

### Task M3-1：core/model.py + segments.py（L0 走势类型构造）

**Files:**
- Create: `src/chan_engine/core/__init__.py`
- Create: `src/chan_engine/core/model.py`
- Create: `src/chan_engine/core/segments.py`
- Test: `tests/chan_engine/test_core_segments.py`

**算法（L0 分组规则 v1，以 BC-002 为锚）**：笔序列按方向交替的自然摆动分组——一段由"同向趋势 + 反向调整"构成，当反向幅度足以逆转趋势方向时切分新段。最小段 = 3 笔（下-上-下 或 上-下-上）。段方向 = 首笔方向。具体切分判据在实现时以 BC-002（0-2/3-5/6-8）+ seg-001~005 校准，登记 ADR。

- [ ] **Step 1: 写失败测试**（BC-002 L0 分组断言）

```python
# tests/chan_engine/test_core_segments.py
from chan_engine.spec.case_io import load_case
from chan_engine.core.segments import build_l0_segments

def test_bc002_l0_segments():
    case = load_case("src/chan_engine/spec/cases/bc-002.yaml")
    segs = build_l0_segments(case.expect_bi_as_bi_list())  # 见注
    # A2=bi0-2 down, B2=bi3-5 up, C2=bi6-8 down, 余 bi9 unsure
    assert [(s.start_bi, s.end_bi, s.dir.value) for s in segs] == [
        (0, 2, "down"), (3, 5, "up"), (6, 8, "down"),
    ]
```

注：测试输入用 expect 的 bi 表（已校准正确），经 `spec.model.Bi` 构造；helper 由 case_io 或测试内联实现。

- [ ] **Step 2: 跑测试确认失败** `pytest tests/chan_engine/test_core_segments.py -v` → ImportError
- [ ] **Step 3: 实现 model.py（SegType 容器）+ segments.py（分组）**
- [ ] **Step 4: 跑测试确认通过**
- [ ] **Step 5: Commit** `feat(chan-engine): M3-1 L0 走势类型构造（bi→seg 自建分组）`

### Task M3-2：levels.py（LevelTree 多级中枢合成）

**Files:**
- Create: `src/chan_engine/core/levels.py`
- Test: `tests/chan_engine/test_core_levels.py`

**算法**：识别 进入段+中枢段+离开段 三件套；中枢段内 3 笔重叠（复用 C.4：引导笔定向+反向笔配对+严格重叠）→ level-2 中枢；递归：3 个连续 L_N 走势类型重叠 → L_{N+1} 中枢。

- [ ] **Step 1: 写失败测试**（BC-002 level-2 zs 断言）

```python
def test_bc002_level2_zs():
    case = load_case("src/chan_engine/spec/cases/bc-002.yaml")
    chart = run_recursion(case.expect_bi_as_bi_list())  # engine 入口
    lv2 = [z for z in chart.zs if z.level == 2]
    assert len(lv2) == 1
    assert (lv2[0].zd, lv2[0].zg, lv2[0].start_idx, lv2[0].end_idx) == (23.9, 26.2, 16, 31)
```

- [ ] **Step 2~5**: Red → Green → Refactor → Commit `feat(chan-engine): M3-2 LevelTree 多级中枢合成`

### Task M3-3：backchi.py（背驰 + 多级买卖点）

**Files:**
- Create: `src/chan_engine/core/backchi.py`
- Test: `tests/chan_engine/test_core_backchi.py`

**算法**：面积代理 Σ|Δc|（进入段 vs 离开段，同向比较）；离开段面积 < 进入段 → 背驰 → 一买/一卖；区间套：大级别背驰段内再找次级别背驰 → 双 level 买卖点同 idx。

- [ ] **Step 1: 写失败测试**（BC-002 双一买断言）

```python
def test_bc002_dual_level_bsp1():
    chart = run_recursion(bc002_bi_list)
    bsp1 = [(b.idx, b.level) for b in chart.bsp if b.bstype == 1]
    assert (46, 1) in bsp1 and (46, 2) in bsp1
```

- [ ] **Step 2~5**: Red → Green → Refactor → Commit `feat(chan-engine): M3-3 背驰判断+多级买卖点`

### Task M3-4：engine.py + 校准门接入 + 6 降级用例重验

**Files:**
- Create: `src/chan_engine/core/engine.py`
- Modify: `src/chan_engine/harness/report.py`（递归层接入校准矩阵；或新增 `--engine recursion` 路径）
- Test: `tests/chan_engine/test_core_engine.py`

**接入方式**：递归层作为**第三实现**（name="recursion"）进入校准矩阵，输入 bars → 内部调用单级别构造（复用 chanpy 适配器的 bi 或直接 spec 层笔构造）→ 递归合成多级 zs/bsp → 归一五表。BC-002×2、BSP-003×2、GOLD-001/002 重验。

- [ ] **Step 1: 引擎集成测试**（6 降级用例逐个断言）
- [ ] **Step 2: 全量校准矩阵测量** `--out /tmp/m3-report.md`，对比 48→? PASS
- [ ] **Step 3: BSP-003 三买判定**（走势类型+回试不破 ZG）
- [ ] **Step 4: GOLD-001/002 多级别笔划分探索**（不成则登记降级结论）
- [ ] **Step 5: Commit** `feat(chan-engine): M3-4 递归层引擎集成+6 降级用例重验`

### Task M3-5：增量生长 + 批量/增量一致性

**Files:**
- Modify: `src/chan_engine/core/engine.py`（增量入口）
- Test: `tests/chan_engine/test_core_incremental.py`

**口径**：新 bar 只触发最低层重算，变化向上层传播；is_sure 透传。批量/增量终态一致性为验收硬项（设计文档风险表）。

- [ ] **Step 1: 一致性测试**（同一 bars 序列：一次性批量 vs 逐 bar 增量，终态五表全等）
- [ ] **Step 2~4**: 实现 → 绿 → Commit `feat(chan-engine): M3-5 递归层增量生长+一致性`

### Task M3-6：收官

- [ ] 全量复跑校准门（目标 6 降级项清零或重新归因）
- [ ] 重生成 `docs/design/chanlun-calibration-report.md`（M3 版；M2 版在 git 历史 0717b59）
- [ ] 新增/更新 ADR（递归口径仲裁：L0 分组规则、level 语义、GOLD 多级别结论）落 `docs/design/chanlun-quant-adr.md`
- [ ] 更新附录 C.2（level 约定补 level≥2 递归层语义）、progress.md、写 `.superpowers/sdd/task-m3-report.md`
- [ ] 更新 `.workbuddy/memory/`
- [ ] 提交推送（另行向用户确认）

## 批次编排

| 批次 | 内容 | 依赖 | checkpoint |
|---|---|---|---|
| M3-1 | L0 分组 | 无 | seg 分组测试绿 |
| M3-2 | 多级中枢 | M3-1 | BC-002 level-2 zs 绿 |
| M3-3 | 背驰买卖点 | M3-2 | BC-002 双一买绿 |
| M3-4 | 引擎集成+重验 | M3-3 | 6 降级项矩阵增量 |
| M3-5 | 增量+一致性 | M3-4 | 批量/增量终态一致 |
| M3-6 | 收官 | M3-5 | **UP 评审门** |

每批后主控 spec-compliance + 代码质量评审，Critical 不过夜。M3-1~M3-3 为纯算法层（可 subagent 并行探索），M3-4 起串行集成。

## 风险与对策

| 风险 | 等级 | 对策 |
|------|------|------|
| L0 分组规则在 seg-001~005 上与既有 seg 口径冲突 | 高 | 分组规则以 expect 语料校准，冲突登记 ADR；递归层 L0 独立于适配器 seg，不破坏 M2 成果 |
| GOLD-001/002 真实日线笔太少无可解 | 中 | 多级别笔划分探索（M3-4 Step4）；不成则明确降级结论交 UP，不阻塞关门 |
| level 语义理论歧义（中枢层级 vs 角色） | 中 | 以 BC-002 expect 为实证锚，ADR 记录选定口径 |
| 增量生长复杂度高 | 中 | 先批量正确性后增量（M3-5 独立批次）；一致性测试为硬门 |
