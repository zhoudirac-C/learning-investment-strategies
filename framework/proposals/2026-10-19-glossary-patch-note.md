---
date: 2026-10-19
type: glossary-patch
status: open
source: evals/shadow/attributions/2026-10-19.json
---

# 多指数周期分歧采用区间或中位锚定

## 分析

cycle_state 存在三指数分歧（科创50 bottom_date=2026-10-16 rebound_day=1、上证=2026-10-13 rebound_day=4、创业板指=2026-09-17 rebound_day=16），AI 却“按科技主线科创50锚定 rebound_day=1”用于操作依据，属于选取对预设结论“调整”最有利的单一指数锚定；正确做法应给出区间或取中位并显式标注分歧，该行为构成概念误用。方向 commercial_aerospace 失败原因：选择依据是盘前催化+昨日板块资金净流入28亿+华力创通机构净买3558万，但同一数据中“资金净流入28亿但股价仅+0.59%尾随”已显式量价背离，且当日外部 AI 硬件链大跌（AMD-5.95/AVGO-4.52/MRVL-5.56/CRWV-11.91/MU-5.63/COHR-7.06）、宽基数据缺失，市场处于调整期，低级别事件催化无法对冲系统性下行；AI 自评“本条置信度低”却仍唯一输出该方向，说明缺少“低置信度方向不进入 directions”和“周期位置过滤事件驱动”的步骤。

## 处置建议

当 cycle_state 中各指数 bottom_date/rebound_day 不一致时，必须输出跨度区间（如 rebound_day 1-16）或中位数，并在操作依据中显式标注分歧；禁止引用单一指数锚定结论，违反视为概念误用。
