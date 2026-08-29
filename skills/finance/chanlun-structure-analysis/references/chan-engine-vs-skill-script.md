# chan_engine（项目量化引擎）vs chan_analysis（skill 简化脚本）— 复用评估与实证

> 2026-08-28 实证。用户问"复用 chan_engine 替换 skill 脚本是否可行、是否精准"时的完整评估。

## 一、两套引擎定位

| 维度 | chan_analysis.py（skill 脚本） | chan_engine（src/chan_engine/） |
|---|---|---|
| 位置 | `~/.hermes/skills/finance/chanlun-structure-analysis/scripts/` | `learning-investment-strategies/src/chan_engine/` |
| 口径 | SKILL.md 7 步简化算法直译（笔间隔≥3 合并后≈旧笔、背驰阈值 0.9、连续3笔重叠中枢） | 337 条 claims 验收 + 11 条 ADR 仲裁（新笔 ADR-002、77课区间 strict ADR-001、特征序列缺口 ADR-003、笔/段中枢双哲学 ADR-010） |
| 能力 | 单级别：包含→分型→笔→MACD→中枢→背驰→买卖点；**支持 30m/60m/任意分钟** | 多级递归：L0 线段 → 多级中枢 → 多级买卖点 + **is_sure 透传**；数据层 M6 **只有日线**（分钟线是明确非目标） |
| 依赖 | 零第三方依赖（纯 subprocess/urllib） | 需 `third_party/chanpy` 在 sys.path（czsc 仅对照，可不装） |
| 输出 | 控制台摘要 + `/tmp/chan_results.json`（防守线/反转位等直接可消费） | NormalizedChart 五表（fx/bi/seg/zs/bsp + sure），需 adapter 翻译成报告惯例 |

## 二、chan_engine API 速查（复用入口）

```python
import sys
sys.path.insert(0, "~/learning-investment-strategies/src")
sys.path.insert(0, "~/learning-investment-strategies/third_party/chanpy")
from chan_engine.core.engine import RecursionEngine
from chan_engine.spec.model import Bar, Direction

bars = [Bar(ts=i, o=..., h=..., l=..., c=..., vol=...) for i, k in enumerate(klines)]
chart = RecursionEngine().run(bars)          # 批量
chart = RecursionEngine().run_incremental(bars)  # 增量（逐 bar push）
chart = RecursionEngine().new_session()       # RecursionSession，可 push 单根
# chart.fx / .bi / .seg / .zs / .bsp；每元素带 .sure（右侧未确认=False）与 .source
```

- 数据层：`data/fetch.py` 降级链 akshare→baostock（日线，前复权 qfq 唯一口径），`data/store.py` SQLite（infra/data/chan_bars.db）。**无分钟线接口**。
- 笔级依赖 chanpy（vendored fork），构造 `RecursionEngine()` 时懒加载 `ChanPyAdapter`。

## 三、实证：同一份 512400 日线 261 根，两套输出对比

| 维度 | chan_analysis（简化） | chan_engine（claims 校准） |
|---|---|---|
| 笔数 | 27（间隔极短，5~6 根K线成笔） | 19（首笔跨 39 根） |
| 最近中枢 | [20~26] ZD=1.849 ZG=1.851（窄到 0.002） | [136~177] ZD=2.032 ZG=2.197 L1 |
| 买卖点 | 0 个 | 1 个：1 类卖点 @2026-03-02 L1 |
| 线段 | 无 | 4 个 L0 走势类型 |

**结论：不是"哪个更准"，是定义不同（口径分叉）**——简化参数的 0.9 背驰阈值/间隔≥3 成笔 vs claims 校准的新笔规则。同一 K 线一个看"中枢 1.849~1.851 附近"，一个看"1 类卖点"，方向可相反。

## 四、复用评估（给用户的结论）

- **代码可复用** ✅：API 清晰、chanpy 依赖可用、核心 182 测试全绿。
- **不能"直接替换"** ❌：① 口径分叉 → 历史-未来判断基准断裂（用户做多天连续演变复盘）；② 分钟线缺失 → 30m/60m 入场时机是刚需，engine 接不了；③ 输出契约不同 → 需报告翻译 adapter。
- **正确姿势**：双轨并存（日线深度结构用 engine + adapter 翻译；分钟线保留 chan_analysis）或先对照观察一轮。

## 五、对比 probe（可复用方法）

同一份真实 klines 喂两套，diff 笔/中枢/买卖点：
```python
# 1) 用 chan_analysis 拉数（命中缓存不联网）：
klines = ca.fetch_tencent_daily("sh512400", fresh=False)
# 2) chan_analysis 侧：merge_inclusion→find_fractals→find_bi→identify_zhongshu→detect_backtension→classify_buy_points
# 3) chan_engine 侧：Bar 列表 → RecursionEngine().run()
# 4) 对比笔数/端点、最近中枢 [ZD,ZG]、买卖点有/无与位置
```
完整对比脚本模板：`/tmp/compare_chan.py`（2026-08-28 会话产出，若仍在）。

## 六、chan_analysis 缓存格式坑

`/tmp/klines/{code}.json` 存的是**腾讯原始响应**（`{"code","msg","data"}`→`data[sym]['qfqday']`，行格式 `[date,open,close,high,low,vol]`），不是统一 dict。直接读缓存做别的用途时，**走 `fetch_tencent_daily` 解析**（内部处理 qfqday/day 选择），勿手写解析。
