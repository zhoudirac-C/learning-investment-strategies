# 归档：依赖已封禁 TDX 能力的死脚本（2026-09-23）

TDX 服务端已按**接口粒度**封禁 `HostCapability.CapMainKline`（实测：
`尝试 5 台服务器均返回空结果，疑似服务端按接口粒度封禁`）。
**TDX 其他能力存活**（`CapSector880` 板块成分文件 269 板块 ✅、
历史分时 `get_intraday` 120 根 ✅），故只有依赖 K线的脚本是死链。

| 文件 | 死因 | 状态 |
|---|---|---|
| `chan_fetch_30m.py` | 直连 `TdxMarket.get_kline` → CapMainKline 封禁 | 归档（一次性临时脚本，缓存 /tmp/tdx_30m，无引用方） |
| `chan_fetch_60m.py` | 同上 | 归档（同上） |

## 替代方案

K线统一走 `qing_investment.marketdata`：腾讯优先 → 东财 → TDX → 新浪 → 同花顺。
**注意**：腾讯/新浪 bar 的 `amount` 恒为 `0.0`，量能场景必须
`sources=["eastmoney", "tencent"]`（见 skill
`qing-stock-monitor-ops` 的 `references/marketdata-unified-intraday-usage.md`）。

## 仍存活、勿误改

- `scripts/fetch_tdx_sector_members.py` — 走 `CapSector880`（**未封禁**，269 板块正常）
- `scripts/pre_fetch_klines.py` — 自带 TDX 连通性探测 + 回退腾讯（安全）
- `scripts/fetch_tdx_sector_klines.py` — 已走 `marketdata.get_kline`（安全）
