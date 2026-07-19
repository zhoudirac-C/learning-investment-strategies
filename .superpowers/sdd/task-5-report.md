# Task 5 报告：czsc 适配器

日期：2026-07-18 ｜ 状态：DONE

## 文件清单

| 文件 | 说明 |
| --- | --- |
| `src/chan_engine/harness/__init__.py` | 新建（harness 包入口；若与并行 Task 4 的创建重叠，内容仅一行 docstring，无冲突） |
| `src/chan_engine/harness/adapter_czsc.py` | 新建：`CzscAdapter`（name / config_snapshot / run(bars) → NormalizedChart） |
| `tests/chan_engine/test_adapter_czsc.py` | 新建：8 条测试，先红（ModuleNotFoundError）后绿 |

未触碰 `adapter.py` / `adapter_chanpy.py` / 既有测试 / `third_party/chanpy/`。适配器结构性对齐 ChartAdapter 协议（鸭子类型），未 import `adapter.py`（编写时该文件尚不存在）。

## 测试命令与结果

- `PYTHONPATH=src .venv/bin/python -m pytest tests/chan_engine/test_adapter_czsc.py -q` → **8 passed**
- `PYTHONPATH=src .venv/bin/python -m pytest tests/chan_engine/ -q` → **58 passed**（含既有 50 条，无回归）

## czsc 0.10.12 实际 API 与计划描述的出入

1. **默认后端是 Rust（rs_czsc）**，不是 Python：`czsc.CZSC` 来自 `czsc.core`，按 `CZSC_USE_PYTHON` 环境变量在 rust/python 实现间切换，默认 rust。对外属性名一致（`fx_list`/`bi_list`/`finished_bis`/`bars_ubi`），但**枚举类不同**（rust 的 Mark/Direction 与 `czsc.py.enum` 不是同一类），适配器统一按 `.value` 字符串（"顶分型"/"底分型"/"向上"/"向下"）比对。
2. **`min_bi_len` 不是 CZSC 构造参数**：构造函数为 `CZSC(bars, get_signals=None, max_bi_num=50)`；`min_bi_len` 由 `czsc.envs.get_min_bi_len()` 从环境变量 `czsc_min_bi_len` 读取（默认 6，即"新笔"口径）。适配器 `__init__` 支持传入并设置该环境变量（进程级副作用，已在 docstring 注明）。
3. **`get_zs_seq` 不在 CZSC 上**，是 `czsc.utils.sig.get_zs_seq(bis: List[BI]) -> List[ZS]`，对笔列表滚动分组。其分组松散（单笔即可起组），适配器剔除 `len(bis)<3` 或 `is_valid=False` 的组（缠论中枢需≥3 段重叠；此剔除属归一判断，已记录）。
4. **`CZSC.fx_list` 不含第一笔的起始分型**：实现按 `bi.fxs[1:]` 拼接（本意去重相邻笔共享分型，连带丢掉首笔 fx_a）。这是 czsc 原生口径，适配器如实搬运并在测试中用注释钉住——对表时 FX 表会暴露此差异，属预期产出。
5. FX/BI/ZS 对象字段与 `czsc/py/objects.py` 一致：`FX(dt, mark, fx, high, low, elements)`、`BI(fx_a, fx_b, fxs, direction, sdt, edt)`、`ZS(zd, zg, bis, is_valid, sdt/edt)`。

## 索引映射依据

归一 idx = 输入 bars 的 0 基位置下标。转换时第 i 根 Bar → `RawBar(id=i+1, dt=BASE_DT + i天, freq=Freq.D)`（BASE_DT = 2000-01-01 tz-aware UTC），同时建 `{dt: i}` 字典。czsc 输出的 `FX.dt`/`BI.fx_a.dt`/`BI.fx_b.dt` 必为某根输入 RawBar 的 dt（去包含合并 `remove_include` 取极值所在原始 K 线的 dt），查字典即得 0 基下标；与 `Bar.ts` 无关，映射按位置构造、双向可查。

## 配置快照内容（config_snapshot）

`czsc_version`（0.10.12）、`backend`（rust/python，由 `check_rs_czsc()` + `CZSC_USE_PYTHON` 判定）、`rs_czsc_version`、`min_bi_len`（实际生效值，默认 6）、`max_bi_num`（默认 50）、`freq`（日线）、`dt_base`（合成 dt 起点）。

## sure 口径

czsc 无显式"右侧确认"标记，归一规则：Bi 出现在 `finished_bis`（按 fx_a/fx_b 的 dt 对匹配）为 sure=True；FX 出现在任一 finished bi 的 `fxs` 中为 sure=True，仅在未完成笔（ubi）中的分型 sure=False。

## 遇到的坑

1. **rs_czsc 的 naive datetime 时区坑**：输入 naive datetime 被当作北京时间转 UTC，输出 dt 整体 -8 小时（`2020-01-06 00:00` → `2020-01-05 16:00`），直接按 dt 值映射会全错。解：投喂 tz-aware（UTC）datetime，输出 dt 与输入逐值相等（tz 被丢弃）。已写入适配器 docstring。
2. **合并后 NewBar.id 不可靠**：`remove_include` 合并时新 NewBar 继承前一根的 id 而 dt 取极值所在根，故不能用 id 回推输入下标，只能用 dt。
3. **分型判等是严格不等**（`k1.high < k2.high > k3.high`），等高 K 线不成/偏移分型——测试用例的期望端点（如首笔顶分型落在 idx5 而非 idx4）是按 czsc 实证输出钉住的，属 czsc 口径而非错误。

## Fix: min_bi_len 快照失真

**问题**（code review Important）：`CzscAdapter.__init__` 设置环境变量 `czsc_min_bi_len`，`config_snapshot` 把 `envs.get_min_bi_len()` 记为"实际生效值"。但 rs_czsc 完全忽略该环境变量（实证：设 7 后 rust 输出不变，`min_bi_len` kwarg 被 `CZSC.__new__` 拒绝），只有 python 后端（`czsc/py/analyze.py:check_bi` 每次调用时读 `envs.get_min_bi_len()`）才响应。后果：`CzscAdapter(min_bi_len=7)` 输出与默认一致，快照却记 7——校准门配置快照失真；且 `__init__` 设环境变量不恢复，属进程级污染。

**后端选择机制核实**（czsc 0.10.12）：`czsc/core.py` 在 import 时按 `CZSC_USE_PYTHON` / rs_czsc 是否安装二选一，import 后无法再切换顶层后端；但 `czsc.py` 子包始终可独立 import，其 CZSC 与 `get_zs_seq` 兼容、枚举 `.value` 字符串与 rust 一致。

**方案**：实例级 python 后端切换（优先方案的本地化实现，不做进程级 reload）。传非默认 `min_bi_len` 且顶层为 rust 时，该实例 run() 改用 `czsc.py.analyze.CZSC` + `czsc.py` 的 RawBar/Freq 执行，参数真实生效；环境变量仅在 CZSC 构造期间临时设置、finally 恢复原值（含原未设置则删除）。显式传默认值 6 或未传参时走原 rust 快路径，行为不变。

**改动点**（仅两文件）：
- `src/chan_engine/harness/adapter_czsc.py`：`__init__` 不再写环境变量，改为判定 `_rust_backend`/`_use_py_path`/`_backend_switch_reason`；新增 `_run_python_backend()`（懒加载 czsc.py 对象 + env set/restore）；`_to_raw_bars` 参数化 `raw_bar_cls`/`freq`；`config_snapshot` 新增 `requested_min_bi_len`、`effective_min_bi_len`、`backend_switch_reason`，`min_bi_len` 保留为兼容 key 但如实记实际生效值（rust 路径恒为内置 6，不再读环境变量）。
- `tests/chan_engine/test_adapter_czsc.py`：新增 4 条回归——非默认 min_bi_len 输出真实变化（敏感序列：6 成 2 笔 / 7 成 0 笔）、快照 requested/effective 区分且记录切换原因、默认路径快照（rust/None/6/无切换原因）、run() 后环境变量恢复原状。

**测试输出**：`PYTHONPATH=src .venv/bin/python -m pytest tests/chan_engine/test_adapter_czsc.py -q` → 12 passed；`PYTHONPATH=src:third_party/chanpy .venv/bin/python -m pytest tests/chan_engine/ -q` → 66 passed。
