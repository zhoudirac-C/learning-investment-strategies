# 缠论量化引擎 M1：校准测试门 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 337 条缠论 claims 中的定义/定理编译为可执行测试门，驱动 chan.py 与 czsc 在同一输入上对表，产出《口径偏差清单》（`docs/design/chanlun-calibration-report.md`），作为 M2 fork 改造的工作订单。

**Architecture:** 见 `docs/design/chanlun-quant-engine.md` §三。M1 只建 spec 层（rules/cases/golden）+ harness（归一模型、两个适配器、diff 引擎、报告生成），不碰 chan.py 源码、不建引擎层。

**Tech Stack:** Python 3.11（仓内 `.venv`）、pytest、PyYAML、numpy/pandas（已有）、chan.py（vendor 至 `third_party/chanpy/`，MIT）、czsc（pip 钉版本，仅作对照）。

**设计源：** `docs/design/chanlun-quant-engine.md`（v1.0 已签认）

---

## Global Constraints

- **不写引擎实现代码**：M1 只产出规格、用例、适配器、diff 工具与报告。chan.py 一字不改（vendor 原样，改造属 M2）。
- **每条用例必须挂 claim id**：`claim_refs` 指向 `knowledge/claims/` 中真实存在的 id，可追溯、可校验。
- **TDD**：harness 各组件先写失败测试再实现；用例族本身就是测试（harness 跑 FAIL 即发现偏差，这是预期产出，不是失败）。
- **口径仲裁权在原文**：任何歧义不擅自拍板，记录到 ADR 候选（`docs/design/chanlun-quant-adr.md`），默认取 claims 直译。
- **禁止 git 操作**：实现完成后由主控统一提交（仓规：不用 `git add -f`）。
- **数据零外泄**：synthetic 用例零依赖；真实数据仅 akshare/baostock 公开源。

---

## File Structure

| File | Responsibility |
| --- | --- |
| `src/chan_engine/__init__.py` | 包入口 |
| `src/chan_engine/spec/model.py` | 归一数据模型：Bar/FX/Bi/Segment/ZhongShu/BSPoint + Direction + sure 标记 |
| `src/chan_engine/spec/case_io.py` | 用例 YAML 加载/校验（schema + claim_refs 存在性校验） |
| `src/chan_engine/spec/cases/*.yaml` | 26 条 synthetic 用例（七族，见 Task 6） |
| `src/chan_engine/spec/golden/*.yaml` | 金标样本（Task 7） |
| `src/chan_engine/spec/builders.py` | synthetic K 线构造助手（紧凑记法→Bar 列表） |
| `src/chan_engine/harness/adapter.py` | 适配器协议：`run(bars) -> NormalizedChart` |
| `src/chan_engine/harness/adapter_chanpy.py` | chan.py 适配器（记录其配置快照） |
| `src/chan_engine/harness/adapter_czsc.py` | czsc 适配器（仅 FX/BI/ZS 层，其余标 N/A） |
| `src/chan_engine/harness/diff.py` | 输出归一化 + 逐字段 diff |
| `src/chan_engine/harness/report.py` | 校准矩阵 + markdown 报告生成 |
| `tests/chan_engine/` | harness 组件测试 + 用例 schema 测试 |
| `docs/design/chanlun-calibration-report.md` | **M1 最终产出：口径偏差清单** |
| `docs/design/chanlun-quant-adr.md` | 歧义仲裁记录（本计划 Task 0 预建骨架） |

---

## Task 0: 环境与 vendor 准备

**Files:**
- Create: `third_party/chanpy/`（vendor copy）、`docs/design/chanlun-quant-adr.md`
- Modify: 无（requirements 通过 `.venv` 内 pip 安装，不写文件）

- [ ] **Step 1: vendor chan.py**
  浅克隆 `https://github.com/Vespa314/chan.py` 到临时目录，拷贝源码（含 `LICENSE`）到 `third_party/chanpy/`，删除其 `.git`。记录 commit hash 到 `third_party/chanpy/VENDORED.txt`（格式：`source=<url>\ncommit=<sha>\ndate=2026-07-18`）。创建空 `PATCHES.md`（表头：文件/函数/原行为/改后行为/claim id/用例 id——M2 填）。
- [ ] **Step 2: 安装依赖到 `.venv`**
  `.venv/bin/pip install "czsc==<调研时最新stable>" pyyaml`；chan.py 依赖按其 `Script/requirements.txt`（numpy/pandas/matplotlib/baostock/ipython/requests）补齐。版本钉入 `third_party/chanpy/VENDORED.txt` 附注。验证：`.venv/bin/python -c "import czsc, pandas, numpy; print(czsc.__version__)"`。
- [ ] **Step 3: 建 ADR 骨架**
  `docs/design/chanlun-quant-adr.md`：预列 4 个已知歧义（77 课"区间"口径 / 新笔旧笔 / 特征序列缺口细节 / 古怪线段），每条格式：备选解释 A/B、claims 原文依据、暂定默认、状态=pending。
- [ ] **Step 4: 验证 chan.py 可导入**
  `PYTHONPATH=src:third_party/chanpy .venv/bin/python -c "from Chan import CChan"`（按其实际包名调整）；不通则记录阻塞原因，**不要改 chan.py 源码**，优先用 sys.path/导入方式解决。

## Task 1: 归一数据模型

**Files:**
- Create: `src/chan_engine/spec/model.py`
- Test: `tests/chan_engine/test_model.py`

**Interfaces:**
- Produces: `Direction(Enum)`, `Bar`, `FX`, `Bi`, `Segment`, `ZhongShu`, `BSPoint`, `NormalizedChart`（dataclasses；每个结构元素带 `sure: bool` 与 `source: str`（实现名））

- [ ] **Step 1: 先写测试** — `test_model.py`：构造各对象，断言字段、默认值（`sure=True`）、`NormalizedChart` 五张表（fx/bi/seg/zs/bsp）初始为空列表。
- [ ] **Step 2: 实现 model.py**（最小实现过测试）。字段口径：Bar=`(ts,o,h,l,c,vol)`；FX=`(idx,type,sure)`；Bi=`(start_idx,end_idx,dir,sure)`；Segment=`(start_bi,end_bi,dir,sure)`；ZhongShu=`(zd,zg,start_idx,end_idx,level,sure)`；BSPoint=`(idx,bstype(1/2/3),dir,level,sure)`。
- [ ] **Step 3: `pytest tests/chan_engine/test_model.py` 全绿**

## Task 2: 用例加载与 claim_refs 校验

**Files:**
- Create: `src/chan_engine/spec/case_io.py`
- Test: `tests/chan_engine/test_case_io.py`

- [ ] **Step 1: 先写测试** — 一个最小用例 YAML fixture；断言：加载成功、缺字段报错、claim_refs 指向不存在 id 时报错（扫描 `knowledge/claims/*.yaml` 建立 id 全集后校验）。
- [ ] **Step 2: 实现 case_io.py** — schema 校验（case_id/bars/expect 必需；expect 子键 fx/bi/seg/zs/bsp 可选）、bars 数组转 Bar、claim id 全集缓存加载。
- [ ] **Step 3: 全绿 + 用一个真实 claim id 手动验证存在性校验工作**（如 `claim-20070905-001-b`）。

## Task 3: synthetic 构造助手

**Files:**
- Create: `src/chan_engine/spec/builders.py`
- Test: `tests/chan_engine/test_builders.py`

- [ ] **Step 1: 先写测试** — 紧凑记法（如 `"10,11,9,12,8"` 收盘价序列+默认振幅，或显式 `(o,h,l,c)` 元组列表）生成 Bar；断言 h≥max(o,c)、l≤min(o,c) 自动满足。
- [ ] **Step 2: 实现 builders.py** — 支持显式元组与简写两种输入；自动补 ts（递增）、vol（常量）。
- [ ] **Step 3: 全绿**

## Task 4: chan.py 适配器

**Files:**
- Create: `src/chan_engine/harness/adapter.py`、`src/chan_engine/harness/adapter_chanpy.py`
- Test: `tests/chan_engine/test_adapter_chanpy.py`

**Interfaces:**
- Consumes: `list[Bar]`
- Produces: `NormalizedChart`（五表填满；chan.py 的 `is_sure` 直接映射到 `sure`）

- [ ] **Step 1: 先写测试** — 用 builders 造一段确定走势（含 2 笔），断言适配器输出的 FX/BI 数量与方向、配置快照字段存在。
- [ ] **Step 2: 定义 adapter.py 协议**（`class ChartAdapter(Protocol): name: str; config_snapshot: dict; def run(self, bars) -> NormalizedChart`）。
- [ ] **Step 3: 实现 adapter_chanpy.py** — 按 chan.py `CChanConfig` **默认配置**实例化（快照记录全部配置项，偏差分析时要用）；逐帧 `trigger_load` 投喂；从其 `bi_list/seg_list/zs_list/bs_point_lst` 抽取并归一。卡点时查 `third_party/chanpy/quick_guide.md` 与 `Debug/strategy_demo*.py` 用法，不改其源码。
- [ ] **Step 4: 全绿；打印一次归一输出人工 sanity check（与 chan.py 自带画图结果对照）**

## Task 5: czsc 适配器

**Files:**
- Create: `src/chan_engine/harness/adapter_czsc.py`
- Test: `tests/chan_engine/test_adapter_czsc.py`

- [ ] **Step 1: 先写测试** — 同 Task 4 的输入，断言 FX/BI 输出、ZS 表存在、Segment/BSPoint 表为 N/A 标记（`NormalizedChart.na_fields`）。
- [ ] **Step 2: 实现 adapter_czsc.py** — `RawBar` 转换、`CZSC` 实例化（记录版本+`min_bi_len` 等到快照）、抽取 `fx_list/bi_list` 与中枢（`get_zs_seq` 输出）；笔方向/端点索引映射归一。
- [ ] **Step 3: 全绿**

## Task 6: diff 引擎与报告生成

**Files:**
- Create: `src/chan_engine/harness/diff.py`、`src/chan_engine/harness/report.py`
- Test: `tests/chan_engine/test_diff.py`、`tests/chan_engine/test_report.py`

- [ ] **Step 1: 先写测试** — 构造 expect 与两份人工输出：全一致→PASS；一笔端点差 1→FAIL 且 diff 指明字段；N/A 字段跳过比对。
- [ ] **Step 2: 实现 diff.py** — 序列对齐策略：按 `(start_idx,end_idx,dir)` 主键对齐，缺/多元素单列；容差=0（严格），容差设计留参数。
- [ ] **Step 3: 实现 report.py** — 校准矩阵（case_id × impl × PASS/FAIL + diff 详情）渲染 markdown；汇总偏差条目模板：【规则源 claim / chan.py 行为 / czsc 行为 / 原文依据 / 仲裁结论 / M2 改造点】。
- [ ] **Step 4: 全绿**

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

## Task 8: 金标样本（3-5 条，降级预案内建）

**Files:**
- Create: `src/chan_engine/spec/golden/*.yaml`

- [ ] **Step 1: 定位课文实例** — 从 claims 的 evidence_quote 提取缠师做过图上分解的实例（课 33/35/36 的 2007 年 5 分钟中枢段、课 24 MACD 背驰例），记录品种/时段/周期/课文结论。
- [ ] **Step 2: 尝试取数** — akshare 拉对应时段数据；2007 分钟级不可得则降级：①日线级课文实例 ②按课文描述等比 synthetic。降级决策记入 ADR。
- [ ] **Step 3: 写成 golden/*.yaml**（格式同 cases，多一个 `source_ref` 字段：课号+原文段落）

## Task 9: 全量对表 + 校准报告

**Files:**
- Create: `docs/design/chanlun-calibration-report.md`

- [ ] **Step 1: 全量运行** — `PYTHONPATH=src:third_party/chanpy .venv/bin/python -m chan_engine.harness.report --cases src/chan_engine/spec/cases --golden src/chan_engine/spec/golden --out docs/design/chanlun-calibration-report.md`
- [ ] **Step 2: 人工评审矩阵** — 每条 FAIL 判定归属：实现偏差 / 用例错误 / 原文歧义；用例错误改用例，歧义进 ADR，实现偏差进清单
- [ ] **Step 3: 完成报告** — 校准矩阵 + 偏差清单（每条含 M2 改造点）+ ADR 更新 + M2/M3 重新估算
- [ ] **Step 4: 评审门（人工 checkpoint）** — UP 过报告 → 签认后进 M2 计划

---

## 执行编排（subagent-driven-development）

| 批次 | 任务 | 并行性 | checkpoint |
|------|------|--------|-----------|
| B0 | Task 0 | 串行（环境前置） | chan.py 可导入验证 |
| B1 | Task 1+2+3（模型/加载/构造器） | 串行（互相依赖） | 三测试全绿 |
| B2 | Task 4+5（两适配器） | **并行 2 个 coder** | 各自冒烟通过 |
| B3 | Task 6（diff/report） + Task 7（26 用例） | **并行**：diff 1 个 coder；用例按族拆 3 个 coder（族 1-3 / 族 4-5 / 族 6-7） | schema 全绿 |
| B4 | Task 8（金标） | 串行 | 降级决策确认 |
| B5 | Task 9（对表+报告） | 串行 | **UP 评审门** |

每批完成后主控做 spec-compliance + 代码质量两段评审（superpowers Phase 6），Critical 问题不过夜。

## M2/M3 占位（M1 报告出来后重新估算并单独立 plan）

- **M2**：按偏差清单改造 `third_party/chanpy/`（PATCHES.md 逐条登记），校准门 100% PASS
- **M3**：`src/chan_engine/core/levels/` 递归层（f1/f2），批量正确性→增量一致性
- **M4**：策略特征层，另立项

## 验收清单（M1 Definition of Done）

- [ ] 26+3 条用例全部过 schema 与 claim_refs 校验
- [ ] 两适配器在全量用例上跑通不崩溃（FAIL 是产出不是错误）
- [ ] `chanlun-calibration-report.md` 含矩阵+偏差清单+ADR+M2 估算
- [ ] harness 组件测试全绿（`pytest tests/chan_engine/`）
- [ ] 全程无 git 操作、无 chan.py 源码改动
