# M1 Task 4 实施报告：chan.py 适配器

日期：2026-07-18 ｜ 执行：coder subagent ｜ 计划：`docs/superpowers/plans/2026-07-18-chanlun-quant-m1-calibration-gate.md` Task 4

## 文件清单（全部新增）

- `src/chan_engine/harness/__init__.py` — 包入口
- `src/chan_engine/harness/adapter.py` — `ChartAdapter(Protocol)`：`name: str` / `config_snapshot: dict` / `run(bars) -> NormalizedChart`，`@runtime_checkable`
- `src/chan_engine/harness/adapter_chanpy.py` — `ChanPyAdapter`：chan.py → NormalizedChart 搬运归一
- `tests/chan_engine/test_adapter_chanpy.py` — 4 条测试

## 测试命令与结果

```
PYTHONPATH=src:third_party/chanpy .venv/bin/python -m pytest tests/chan_engine/test_adapter_chanpy.py -q
4 passed in 0.04s
```

全量回归：`pytest tests/chan_engine/ -q` → **62 passed**（含既有 58 条，无回归）。
严格 TDD：测试先写（collection error 红）→ 实现 → 一次全绿，未改 chan.py 任何文件。

测试数据：显式 `(o,h,l,c)` 13 根 zigzag（顶@2 → 底@6 → 顶@10，相邻 K 线零包含，
严格笔跨度=4 恰好满足默认 `bi_strict`），断言 2 笔方向 DOWN→UP、端点 (2,6)/(6,10)、
3 个分型、配置快照关键字段、source/索引口径、重复运行确定性。

## chan.py 使用方式（关键决策）

- 入口 `from Chan import CChan`，`lv_list=[KL_TYPE.K_DAY]` 单级别；`data_src` 在
  trigger 模式下不会被触达，无需数据源类。
- **配置 = CChanConfig 全默认，唯一例外 `trigger_step=True`**：逐帧 `trigger_load` 投喂
  是 chan.py 官方外部喂数据姿势（`Debug/strategy_demo2.py` 同款）；该开关只改变计算
  触发方式（每帧增量算 vs 末尾统一算），作者明确两种模式最终状态一致。快照中如实记录。
- 投喂：每根 Bar 构造一个 `CKLine_Unit`，`chan.trigger_load({KL_TYPE.K_DAY: [klu]})`。

## 索引映射依据（归一 idx ↔ chan.py 内部索引）

归一模型 idx 一律为输入 bars 的 **0 基下标**。映射成立依据（源码级）：

1. `CChan.try_set_klu_idx`（Chan.py:230）：klu.idx 未显式设置时，按投喂顺序从 0 顺编
   （`self[lv][-1][-1].idx + 1`）。我们逐帧投喂且不预设 idx（构造器默认 -1），
   故 **klu.idx == 输入 bars 的 0 基下标**，与 Bar.ts 的具体取值无关。
2. `Bar.ts`（int 序号）只用于合成时间：`2000-01-01 + pos 天` → `CTime(y,m,d,0,0)`，
   保证严格单调（chan.py 强制 `kline_unit.time > last_t`，ErrCode.KL_NOT_MONOTONOUS）。
   时间仅作占位，不参与归一输出。
3. 笔端点取 `bi.get_begin_klu()/get_end_klu()`（Bi.py:121-131）：端点分型所在合并 K 线内
   的峰值单 K，其 `.idx` 即原始 bar 下标——即使发生包含合并，映射仍落在原始 bar 上。
4. `Segment.start_bi/end_bi` 取 `seg.start_bi.idx`：chan.py 笔序号从 0 顺编，与归一笔表
   行序一一对应。`ZhongShu.start_idx/end_idx` 取 `zs.begin/end`（CKLine_Unit）的 `.idx`；
   `zd=zs.low`、`zg=zs.high`（ZS.py docstring：low/high=中枢范围）。
5. `BSPoint.idx` 取 `bsp.klu.idx`（= 所在笔 `get_end_klu()`）。

## FX / sure / bsp 的归一口径（chan.py 无直接对应字段处）

- **FX 表从笔端点推导**：首笔起点 + 每笔终点（N 笔 → N+1 个分型，相邻笔共享端点）。
  chan.py 的分型标记在合并 K 线 `CKLine.fx` 上、无独立 is_sure 与"第几根 bar"口径，
  从笔端点取既确定又与归一模型"FX.idx=分型中间 K 线 bar 索引"对齐（笔端点即分型极点）。
  已用 native 视图交叉验证：13 根用例 chan.py 的 klc fx 标记 TOP@2/BOTTOM@6/TOP@10，
  与归一 FX 表完全一致。
- **FX.sure**：取终结于该分型的笔的 `is_sure`；首起点分型取首笔的 `is_sure`。
- **BSPoint.sure**：`CBS_Point` 无 is_sure 字段，取所在笔 `bi.is_sure` 近似（搬运选择，非口径修正）。
- **BSPoint.bstype**：`bsp.type[0].main_type()`（'1'/'1p'→1，'2'/'2s'→2，'3a'/'3b'→3）；
  多类型重合点（如 2+3）只取首个主类型——归一模型单 bstype 所限，diff 阶段如需可再议。
- **BSPoint.dir**：取所在笔方向（买点=DOWN 笔末端，卖点=UP 笔末端），与 FX.type
  "终结笔方向"约定一致。

## 默认配置快照内容摘要（`adapter.config_snapshot`，JSON 可序列化）

从实例化后的 CChanConfig 逐属性读取（快照=实际运行配置），Enum 取 str 值/名字，`inf` 转 `"inf"`：

- 顶层：`trigger_step=True`（唯一非默认项）、`skip_step=0`、`kl_data_check=True`、
  `max_kl_misalgin_cnt=2`、`max_kl_inconsistent_cnt=5`、`auto_skip_illegal_sub_lv=False`、
  `print_warning/print_err_time=True`、`mean_metrics=[]`、`trend_metrics=[]`、
  `macd={fast:12,slow:26,signal:9}`、`cal_demark/cal_rsi/cal_kdj=False`、`rsi_cycle=14`、
  `kdj_cycle=9`、`demark={...}`、`boll_n=20`
- `bi`：`bi_algo=normal`、`is_strict=True`、`bi_fx_check=STRICT`、`gap_as_kl=False`、
  `bi_end_is_peak=True`、`bi_allow_sub_peak=True`
- `seg`：`seg_algo=chan`、`left_method=PEAK`
- `zs`：`need_combine=True`、`zs_combine_mode=zs`、`one_bi_zs=False`、`zs_algo=normal`
- `bsp`（buy 侧，sell 侧默认相同）：`divergence_rate="inf"`、`min_zs_cnt=1`、
  `bsp1_only_multibi_zs=True`、`max_bs2_rate=0.9999`、`macd_algo=PEAK`、`bs1_peak=True`、
  `target_types=[1,1p,2,2s,3a,3b]`、`bsp2_follow_1/bsp3_follow_1=True`、`bsp3_peak=False`、
  `bsp2s_follow_2=False`、`max_bsp2s_lv=None`、`strict_bsp3=False`、`bsp3a_max_zs_cnt=1`

## 遇到的坑

1. **CChanConfig 会消费传入的 dict**（`ConfigWithCheck.get` 逐键 `del`，剩余键报 PARA_ERROR）：
   同一 dict 不能复用，每次实例化必须传新副本（`CChanConfig(dict(self._conf_dict))`）。
2. **时间格式**：chan.py 强制时间严格单调，`Bar.ts` int 序号必须先转 CTime；按投喂位置
   合成日期（而非直接拿 ts 当偏移）可同时兼容 ts0≠0、ts 有缺口等任意 int 序号。
3. **逐帧投喂姿势**：`trigger_step=False`（纯默认）下每次 `trigger_load` 末尾会全量
   `cal_seg_and_zs()`，既慢又不是官方外部喂数据路径；`trigger_step=True` 时
   `add_single_klu` 逐帧增量算 seg/zs/bsp，`trigger_load` 末尾不再重算——demo2 路径。
4. **builders 收盘价简写在转折点必产包含**（相邻 bar 高/低点相等），chan.py 合并后
   严格笔跨度常不足 4 → 整段缩成 1 笔。这是 chan.py 自身行为（如实搬运），但构造
   "确定多笔"用例时须用显式 `(o,h,l,c)` 保证转折点高低点严格错位——Task 7 写用例注意。

## Sanity check 结论（人工核对通过）

两组输入，归一输出与 chan.py 原生视图（`bi_list/seg_list/zs_list/bs_point_lst` 直接打印）
**逐字段一致**：

- 13 根 2 笔 zigzag：bi DOWN 2→6 / UP 6→10（均 sure），klc fx 标记 TOP@2/BOTTOM@6/TOP@10
  与归一 FX 表完全相同；seg/zs/bsp 两视图均为空。
- 29 根 6 笔 zigzag（显式 OHLC 无包含）：归一 6 笔（2→6→10→14→18→22→26，D/U 交替）、
  2 段（seg#0 DOWN bi0→4、seg#1 UP bi5→5，均 is_sure=False）、1 中枢（ZD=0.4 ZG=4.6，
  klu 6→18，sure=False）、bsp 空——与 native 打印逐项吻合，sure 标记原样透传。

未用 chan.py 自带 matplotlib 画图（headless 环境），改用框架自身元素打印对照，
覆盖字段更细（含 is_sure），结论等价。

## 合规确认

- 无 git 提交类操作；`third_party/chanpy/` 零改动（纯 import 使用）。
- 未触碰 `tests/chan_engine/` 既有测试与 czsc 适配器相关文件；只新增上述 4 个文件。
- 适配器零口径修正：只做字段搬运与归一，所有映射选择在本文档留痕。

## 遗留 / 给后续任务的接口

- `ChartAdapter` 协议 + `ChanPyAdapter(config_overrides=None)`：Task 6 diff 可直接以
  `adapter.run(bars)` 取归一结果；`config_snapshot` 供偏差清单引用。
- BSP 多类型重合点只保留 `type[0]` 主类型，如 BSP 族用例需要区分 2s/1p/3a/3b 子类型，
  需在归一模型或快照层另行约定（当前模型 bstype∈{1,2,3} 不支持子类型）。
- 构造多笔用例须避开转折点包含（见"坑 4"），Task 7 直接用显式 OHLC 行。
