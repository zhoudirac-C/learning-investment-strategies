# M1 Task 1-3 实施报告：归一模型 / 用例加载 / synthetic 构造器

日期：2026-07-18 ｜ 执行：coder subagent ｜ 计划：`docs/superpowers/plans/2026-07-18-chanlun-quant-m1-calibration-gate.md`

## 测试结果

```
PYTHONPATH=src .venv/bin/python -m pytest tests/chan_engine/ -q
50 passed in 0.18s
```

全程严格 TDD：每个组件先写测试（collection error 变红）→ 最小实现 → 全绿。

## Task 1: 归一数据模型

- 实现：`src/chan_engine/spec/model.py`
- 测试：`tests/chan_engine/test_model.py`（18 条）

`Direction(Enum)` + `Bar/FX/Bi/Segment/ZhongShu/BSPoint/NormalizedChart` 七个 dataclass，
字段口径与计划 Task 1 逐字对齐；结构元素均带 `sure: bool = True` 与 `source: str = ""`。
纯数据容器，零缠论逻辑。

## Task 2: 用例加载与 claim_refs 校验

- 实现：`src/chan_engine/spec/case_io.py`
- 测试：`tests/chan_engine/test_case_io.py`（14 条）

- schema：`case_id/bars/expect/claim_refs` 必需；`expect` 子键仅允许 fx/bi/seg/zs/bsp（可选），未知子键报错。
- claim id 全集：按行正则 `^\s*-\s+id:\s*(claim-\S+)` 扫描 `knowledge/claims/*.yaml`（不做完整 YAML parse），
  模块级缓存（`dict[Path, frozenset]`），全库 2753 个 id，首扫 <0.2s，缓存命中 ~0.1ms。
- 存在性校验已用真实 id `claim-20070905-001-b`（在 `knowledge/claims/claim-20070905-001.yaml`）验证通过；
  假 id `claim-99999999-999-z` 正确报错且错误信息含该 id。

## Task 3: synthetic 构造助手

- 实现：`src/chan_engine/spec/builders.py`
- 测试：`tests/chan_engine/test_builders.py`（18 条，含 case_io 字符串 bars 集成 1 条）

- `bars_from_closes("10,11,9,12,8", amplitude=0.5, vol=1000.0, ts0=0)`：o 取前收（首根 o=c），
  h=max(o,c)+amplitude、l=min(o,c)−amplitude，合法性恒成立。
- `bars_from_ohlc(rows)`：显式 (o,h,l,c)，逐行校验 h≥max(o,c)、l≤min(o,c)，违例抛 ValueError。
- `bars_from(data)` 分发器；`case_io` 的 bars 解析已委托给它（字符串/列表两种写法都支持），
  builders 的 ValueError 在 case_io 层包装为 CaseValidationError。

## 设计决策（与计划字面不完全相同处）

1. **claim_refs 设为必需字段**：计划 Task 2 只列 case_id/bars/expect 必需，但全局约束要求"每条用例必须挂
   claim id"，故在 schema 层强制（非空列表且每个 id 须存在）。Task 7 写用例时天然满足。
2. **na_fields 表示为 `set[str]`**（默认空集），取值范围为五张表名；`model.CHART_TABLES = ("fx","bi","seg","zs","bsp")`
   常量留给 Task 5/6 校验用。集合语义贴合"哪些表 N/A"的成员判断。
3. **FX.type 复用 Direction**：约定 UP=顶分型、DOWN=底分型（= 终结于该分型的笔的方向），
   与 Bi.dir 衔接一致，避免再引入 FXType 枚举；已写入 model.py docstring。
4. **Bar.ts 为 int 序号**（builders 自 ts0 递增）：模型不绑定时间类型；Task 4 适配 chan.py 需要
   datetime 时由适配器负责转换。
5. **BSPoint.bstype 在 `__post_init__` 校验 ∈ {1,2,3}**（计划写了 bstype(1/2/3)），其余结构不加校验保持容器纯粹。
6. **expect 保留原始 dict**：归一到模型对象属于 diff（Task 6）职责，case_io 不做。

## 合规确认

- 无任何 git 提交类操作（仅 `git status` 只读确认：新增均为未跟踪文件）。
- `third_party/chanpy/` 零改动（`git diff third_party/` 为空）。
- 未触碰 `src/qing_investment/` 与 `tests/` 既有文件；只新增 `src/chan_engine/`、`tests/chan_engine/`。

## 遇到的问题

- 一处测试自身笔误：`test_custom_amplitude_and_vol_and_ts0` 对第二根 bar 的 l 期望值算错
  （o=10,c=12,amp=1.0 → l=min(o,c)−1=9，误写 11），按实现正确行为修正测试后全绿。实现本身无返工。

## 遗留 / 给后续任务的接口

- `NormalizedChart.na_fields`、`CHART_TABLES` 待 Task 5（czsc 标 seg/bsp 为 N/A）与 Task 6（diff 跳过）消费。
- case_io 暂不支持 golden 的 `source_ref` 顶层字段——当前顶层未知字段默认放行，Task 8 可直接用。
