# M7-4 区间套递归层实施计划

> 设计依据：`docs/design/chanlun-m7-multitimeframe-skill.md` §七（M7-4 设计）+ §5.2（容器）。
> 验收（§十一）：golden 精确复现 §1.1 实证；二买=次级别一买链路有测试；双口径冲突场景按 MACD 下结论有测试。

## 预检实证（2026-08-29，512400 真实数据探针）——对设计 §三的一处修正

**问题**：设计 §三写"切片 → 次级别引擎分解"。实测把 60m 切片（笔 [7/20~8/11] 窗，
68 根）单独喂引擎 → **zs 全空、无一卖**——切片起点落在结构中段，丢失进入段上下文，
中枢/三件套无法形成。而 §7.3 golden 要求复现的 §1.1 结构全部产自**全序列**引擎运行。

**修正（实证仲裁）**：M7-4 采用**全序列引擎 + 窗口归属**——sub chart 由完整 260 根
分钟序列跑出（保留全部结构上下文），BiSlice 时间窗只做结构归属（zs/bsp span 与窗口
相交即归入该笔）。修正后真实数据全量复现 spike：

- 日线：末端笔 (232,248) up sure=False = [7/20~8/11]，8 月无中枢无买卖点 ✓
- 60m：中枢 [1.712,1.851]（idx143-204）+ [1.860,1.960]（204-231）✓；
  一卖 L2 @2026-08-11 10:30 ✓；**三买 L1 @2026-08-19 15:00 价 1.864 精确复现** ✓
- 30m：中枢 [1.753,1.820] L2 + [1.860,1.960] L1 ✓；
  **一买 L1+L2 双级别共振 @2026-08-19 15:00 价 1.864 精确复现** ✓
- 附带验证 M7-3 产出：60m 二卖 L2 @8/18、30m 二买 L2 @8/25（G4 真实数据自洽）

## 范围

1. `src/chan_engine/multi_tf/model.py`：`SubLevelConfirmation`（§5.2 + §7.1 扩展字段）、
   `MultiTimeframeChart` 增 `confirmations` 字段。
2. `src/chan_engine/multi_tf/nested.py`：`analyze_nested` 管线
   （日线图 + 次级别行 → sub 图 + 归属 + 四输出）。
3. 测试：`test_multi_tf_nested.py`（synthetic，stub 引擎）+ golden（真实快照）。

## SubLevelConfirmation 字段（§5.2 骨架 + §7.1 四输出补全）

```python
bi_ref: tuple[int, int]         # 日线笔 (start_idx, end_idx)
tf: str                         # '60m' / '30m'
zs_in_bi: list[ZhongShu]        # 笔内次级别中枢（支撑/阻力）
bsp_in_bi: list[BSPoint]        # 笔内次级别买卖点（精确定位）
backchi: bool                   # 窗口内存在反向 bstype=1（次级别背驰确认信号）
backchi_metric: dict            # 双口径证据 {"area_proxy": {…}, "macd_area": {…}}
coverage: bool                  # 次级别数据覆盖整笔（BiSlice 透传）
note: str                       # coverage=False 时的"次级别数据不足"标注
small_to_large: bool            # 小转大候选（G10：次级别背驰 + 大级别同位置无背驰；
                                # 仅标注，升级须人工与大级别背驰确认——课 43 纪律）
second_buy_confirmed: bool | None  # 日线二买候选确认（买点定律 claim-20061205-001-a）：
                                # 该笔末端关联日线二买时，窗口末段有次级别一买→True，
                                # 无→False，无关联→None
```

## 关键口径

- **归属**：zs/bsp 的 span 与窗口 [start_pos, end_pos) 相交即归入（bsp 按 idx 落窗）。
- **末端**：窗口末段 = 最后 1 个交易日（60m 4 根 / 30m 8 根，240//tf）。
- **backchi_metric**：对产生背驰三买/卖点的末个三件套，同位置计算双口径面积
  （Σ|Δc| 对照 + MACD 主口径），结论已按 MACD 下（M7-3 引擎默认），指标为证据。
- **日线二买 sure 不原地改写**：确认结论经 `second_buy_confirmed` 输出，
  sure 调整留给 M7-5 报告层（引擎输出保持纯净，设计 §7.1-2 语义的层间分工）。
- synthetic 测试用 stub 引擎（注入罐头 NormalizedChart）隔离归属逻辑；
  golden 用真实快照（tests/chan_engine/fixtures/mt512400_20260828.json，
  日线 262 + 60m/30m 各 260，2026-08-28 收盘固化，分钟不可回填——ADR-005 口径）。

## 任务拆分（TDD）

1. model.py 扩展字段（SubLevelConfirmation + MultiTimeframeChart.confirmations）。
2. nested.py：归属逻辑 + 四输出 + analyze_nested 管线。
3. synthetic：归属边界（窗内/窗外/相交）、coverage=False 传播、complete=0 不进引擎、
   backchi 方向规则、small_to_large 两情形、二买确认三态（True/False/None）。
4. golden：spike 全锚点（日线末端笔、60m 中枢+一卖+三买、30m 双级别一买共振、
   small_to_large 候选=True、backchi_metric 双口径字段存在）。
5. 验收：全量零回归 + golden 绿 + 本文件验收记录。

## 验收记录（2026-08-29，全部通过）

| 验收项（§十一 M7-4） | 结果 |
|---|---|
| golden 精确复现 §1.1 实证 | ✅ `test_multi_tf_nested_golden.py` 10 例：日线末端笔 (232,248) sure=False；60m 中枢 [1.712,1.851] + 一卖 L2 @2026-08-11 10:30 + 三买 L1 @8/19 15:00 价 1.864；30m 一买 L1+L2 共振 @8/19 15:00 价 1.864 + 双中枢区间 |
| 二买=次级别一买链路有测试 | ✅ synthetic 三态（True/False/None）+ 末段窗口（60m 末 4 根/30m 末 8 根）边界 |
| 双口径冲突按 MACD 下结论 | ✅ M7-3 引擎默认 MACD（测试层隔离已锚定）；M7-4 `backchi_metric` 双口径证据字段 golden 断言（enter>leave 双口径同向） |
| synthetic 边界 | ✅ 归属相交/落窗、coverage=False 传播、complete=0 不进引擎、空 tf 数据、小转大两情形——14 例 |
| 零回归 | ✅ 366 passed（=342 + 24 新增）；校准矩阵 chanpy 25 / czsc 25 / recursion 19 逐 cell 不变 |

交付物：`multi_tf/nested.py`（analyze_nested 管线 + 双口径证据）、`multi_tf/model.py`
（SubLevelConfirmation + MultiTimeframeChart.confirmations）、`tests/chan_engine/
fixtures/mt512400_20260828.json`（切片快照）、synthetic + golden 两测试文件、
设计文档 §七 实证修正注记。

附带实证（探针副产品）：M7-3 的 G3/G4 在真实数据自洽——60m 一卖 @8/11 标注
consolidation_div（单 L2 中枢语境，结构诚实）；60m 二卖 L2 @8/18、30m 二买 L2 @8/25
（G4 二买/二卖生成真实落地）。
