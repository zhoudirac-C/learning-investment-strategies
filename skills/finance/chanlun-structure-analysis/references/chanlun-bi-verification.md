# 缠论笔/中枢验证实验（M7-5 引擎，教学/排疑用）

> 适用：用户对引擎画的笔、中枢有疑问时（"中枢是相邻三笔画出来的吗""这段为什么合并成一根笔""时间跨度是不是太大"）。
> 原则：**不嘴讲，用数据 + 截断实验验证**。2026-08-29 立新案例实证有效。

## 引擎验证 API（chan_engine / chan_analysis）

```python
import sys, os
sys.path.insert(0, os.path.expanduser("~/.hermes/skills/finance/chanlun-structure-analysis/scripts"))
import chan_analysis as ca
from chan_engine.core.engine import RecursionEngine
from chan_engine.spec.model import Bar, Direction

k = ca.fetch_sina("sz001258", 60, fresh=True)        # 分钟线（新浪）
k = ca.fetch_tencent_daily("sz001258", fresh=True)   # 日线（腾讯）
bars = [Bar(ts=i, o=x["open"], h=x["high"], l=x["low"], c=x["close"],
            vol=x.get("vol",0) or 0) for i,x in enumerate(k)]
chart = RecursionEngine().run(bars)
```

- `chart.bi`：笔表，字段 start_idx/end_idx/dir（Direction.UP/DOWN）
- `chart.fx`：分型表，字段 idx/type（**type 是 Direction.UP=顶 / DOWN=底，不是 f.dir！**）
- `chart.zs`：中枢表，字段 start_idx/end_idx/zd/zg/level
- `chart.bsp`：买卖点表
- 引擎的 fx/bi 委托给 **chanpy 适配器**（RecursionEngine 自身只做 zs/bsp/trend 增强）

## 验证方法 1：中枢构成验证

中枢 `[ZD, ZG]` 应等于**相邻三笔**的价格重叠：
- ZG = min(三笔各自高点)，ZD = max(三笔各自低点)

用引擎给出的中枢反查构成笔，验证重叠区间吻合。若用户问"中枢哪来的"，逐笔列区间给重叠计算。

## 验证方法 2：截断实验（黄金法，"为啥合并成一根笔"）

步骤：
1. 取完整 K 线
2. 在疑似转折点**前后**分别截断（如：截到跌停后 vs 截到创新高后）
3. 各跑 `RecursionEngine().run(to_bars(k[:cut]))`，对比笔的划分
4. 若早期截断时该处是分型/笔终点、后期截断后消失 → **证明该分型被后续走势推翻**

立新案例（2026-08-29）：bi12 向上笔 7/14→8/12（6.37→16.88），内部 7/28-7/29 两根跌停（15.73→11.61）。
- 截到 7/29：bi12 终点 = 7/28（顶分型成立）
- 截到 8/12：7/28 顶分型**消失**，bi12 延伸到 8/12
- 结论：7/28 顶分型被 8/12 新高 16.88 突破 → 合并成一根向上笔

## 核心概念澄清（教学用，用户连环追问过的点）

1. **中枢 = 相邻三笔的价格重叠区间 [ZD,ZG]，与时间无关**。用户看到矩形"宽"≠区间大。
2. **延伸中枢**：三笔形成后更多笔在区间内震荡，区间不变、时间拉长（矩形变宽但 ZD/ZG 不变）。
3. **笔不按"涨跌"切，按"分型 + 后续确认"切**：顶分型是"候选"不是"判决"，后续创新高会推翻它（笔的动态修正）。
4. 同一标的 30m/60m 中枢可能高度重合（260 根滑动窗口下近期中枢一致），正常。

## 陷阱

- 分型属性是 `f.type`（不是 `f.dir`），方向是 Direction 枚举。
- 日线中枢数值在**腾讯日线 vs chan_bars.db** 间可能有 ±0.03 前复权差异（立新 8.32 vs 8.35 / 11.56 vs 11.59）——同一个中枢，标注时说明数据源。
- `fetch_sina` 的 scale 是分钟数（30/60）；日线用 `fetch_tencent_daily`。
