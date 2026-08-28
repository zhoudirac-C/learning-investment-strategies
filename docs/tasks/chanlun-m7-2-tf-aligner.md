# M7-2 跨周期对齐层实施计划

> 设计依据：`docs/design/chanlun-m7-multitimeframe-skill.md` §五（M7-2 设计）。
> 验收（§十一）：synthetic 切片用例（含空窗/越界断言）全绿；既有测试零回归。

## 范围

1. `src/chan_engine/multi_tf/model.py`：`BiSlice`（笔→切片窗口映射）+ `MultiTimeframeChart` 容器
2. `src/chan_engine/multi_tf/aligner.py`：`TFAligner`（日线笔时间窗 → 次级别 bar 切片）
3. 测试：`tests/chan_engine/test_multi_tf_aligner.py`、`test_multi_tf_model.py`（synthetic，不触网、不依赖 chanpy 环境）

## 关键口径（设计 §5 锁定）

- **时间窗映射**：日线笔 bi(start_idx, end_idx) → `daily_dates[start_idx] 00:00 ~ daily_dates[end_idx] 15:00`
  的 tf 切片（暂定案，简单无歧义可测试；真结构递归留 M7-4 后演进）。
- **未收盘 bar 剔除**：aligner 默认过滤 complete=0 行（load_minute 已默认剔除，此处防御性再过滤）。
- **时间戳对齐纪律**：分钟 dt 须为 'YYYY-MM-DD HH:MM' 且落在 A 股时段
  （(09:30, 11:30] ∪ [13:00, 15:00]，bar 标签=周期结束时刻），异常 dt 抛 `AlignmentError` 明确报错。
- **重叠校验**：切片结果全部 bar 必须落在窗口内，超出即断言失败（防数据错位）。
- **coverage 显式传播**：切片空窗 / 数据起点晚于窗口起点（前段缺）/ 数据终点早于窗口终点（后段缺）
  → `coverage=False` + `note` 标注"次级别数据不足"，**禁止静默降级**。
- **位置对齐**：BiSlice 的 start_pos/end_pos 为 tf rows 列表（与 `load_bars(tf)` 同序同过滤）内切片界
  （python slice 惯例，含头不含尾）。
- tf 标签：multi_tf 层用 str（'60m'/'30m'，对齐设计 §5.2），`tf_label(60)`/`tf_minutes('60m')` 转换。

## 容器（M7-4 前的最小形态）

```python
MultiTimeframeChart {
    daily: NormalizedChart,
    sub: dict[str, NormalizedChart] = {},   # {'60m':…,'30m':…}，M7-4 引擎分解后填充
    slices: list[BiSlice] = [],             # 日线笔 × 次级别 映射
}
BiSlice { bi_ref, tf, window, start_pos, end_pos, coverage, note }
```

SubLevelConfirmation（§5.2）属 M7-4 产出，本期不建（YAGNI）。

## 任务拆分（TDD）

1. model.py：tf_label/tf_minutes、BiSlice、MultiTimeframeChart、build 入口（daily_chart + daily_dates + sub_rows → slices）。
2. aligner.py：TFAligner（构造校验 dt 时段 + 过滤 complete=0）、slice_bi、slice_all、slice_rows。
3. synthetic 用例：时段校验（异常 dt 报错）、partial 剔除、基本切片位置、窗口边界、
   coverage 三情形（空窗/前段缺/后段缺）、slice_all、越界断言、bi 索引越界报错。
4. 回归：全量 chan_engine 测试零回归。

## 验收记录（2026-08-28，全部通过）

- **synthetic 用例全绿**：`test_multi_tf_aligner.py` 22 例——时段校验（形态/午餐/开盘界/
  盘后）、partial 剔除与 include_partial、基本切片位置与窗口边界、空窗/前段缺/后段缺/
  窗口整体晚于数据四情形 coverage=False、bi 索引越界与未知 tf 报错、slice_all 笔×tf、
  容器装配、tf 标签互转、输入乱序排序、complete=None 容忍。
- **真实数据 smoke**（512400，库内真实日线+分钟线）：设计 §1.1 spike 笔 [7/20~8/11]
  → 60m 切片 68 根 `2026-07-20 10:30 ~ 2026-08-11 15:00`，coverage=True；
  末端笔 [8/11~8/28] → 30m 切片 112 根至 `2026-08-28 15:00`；
  切片位置与 `load_bars(tf=60)` 逐位对齐。
- **零回归**：全量 255 passed（=233 + 22 新增）+ 15 环境 error 基线一致。
- **TDD 过程修正**：窗口整体晚于数据终点时 start_pos 计算 StopIteration（边界遗漏），
  补用例后修复为 `next(..., len(rows))` 默认界。

