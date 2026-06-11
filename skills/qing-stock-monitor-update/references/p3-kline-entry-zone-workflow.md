# P3-观察标的 介入区间计算工作流

## 场景

用户要求为 P3-观察标的（仅方向扩散确认，不主动买入）填充基于 K 线技术位的介入区间，供 poll 检测候选。

## 数据源选择（按可靠性排序）

| 数据源 | API | 适用场景 | 限流 |
|--------|-----|---------|------|
| 新浪日K (vip.stock) | `https://vip.stock.finance.sina.com.cn/quotes_service/api_json_v2.php/CN_MarketData.getKLineData?symbol={prefix}{code}&scale=240&ma=no&datalen=30` | ✅ 推荐，30 条日K，含 OHLCV | 1s 间隔 |
| akshare | `ak.stock_zh_a_hist(symbol, period="daily")` | 备用，支持复权 | 易限流 |

**前缀规则**：`sh` 沪市（60xxxx），`sz` 深市（00xxxx/002xxx）

## 计算指标

```python
closes = [d["close"] for d in data]
highs = [d["high"] for d in data]
lows = [d["low"] for d in data]

ma5  = sum(closes[-5:]) / 5
ma10 = sum(closes[-10:]) / 10
ma20 = sum(closes[-20:]) / 20

low20 = min(lows[-20:])
high20 = max(highs[-20:])
pct_5d = closes[-1]/closes[-5] - 1
```

## P3 标的区间设计原则

| 维度 | 规则 |
|------|------|
| price_range | 基于技术位，设 **wider margins**（比 P1/P2 宽 50%）— 因为 P3 不主动买，仅当意外跌深时才值得关注 |
| 方法 | 均线法优先（多头票），低点法次之（空头票） |
| hard_stop | 必须有，基于 price_range 下限下方 5-10% |
| confirm_signal | 必须含方向扩散条件（如"昊华科技先企稳"） |
| position_ratio | **不超过 0.3 成**，且标题标注 P3-观察 |

### 方法选择参考

| 均线排列 | 推荐方法 | 区间范围 |
|---------|---------|---------|
| 多头 (MA5>MA10>MA20) | 均线法，回踩 MA10~MA20 | `[MA10*0.95, MA5*0.98]` |
| 交叉 | 均线法，基于最近支撑位 | `[近低点, MA10]` |
| 空头 (MA5<MA10<MA20) | 近低点法 | `[20日低*1.01, MA5*1.05]` |

## watchlist 写入标准格式

```yaml
entry_zone:
  description: 均线状态+一句话判断。MA5=X MA10=Y MA20=Z 均线排列。
  current_ref: '日期 最新=价格(涨跌幅) MA5=X MA10=Y MA20=Z 20日低=W'
  price_range: 低 ~ 高
  method: 均线法/低点法，基于MA10/Z日低，说明
  confirm_signal: 缩量/方向票企稳/板块联动等条件
  hard_stop: 跌破X且30分钟不能收回
  position_ratio: 不超过0.3成（P3-观察，仅方向扩散确认）
```

## 完整工作流

```
Step 1: 筛选出 P3-观察且 price_range=null 的标的
  → python3 -c "import yaml; ... for stock in ... if 'P3' in priority and not price_range"

Step 2: 拉新浪日K
  → for each code: url=f"https://vip.stock.finance.sina.com.cn/...{prefix}{code}&datalen=30"

Step 3: 计算技术位
  → MA5/MA10/MA20, 20日低/高, 近5日涨幅, 量比

Step 4: 结合 UP 观点推理区间
  → 从 watchlist 已有字段提取：watch_reason / up_positioning / up_mention_status
  → 从 claims 搜索：mcp_neo4j_search_claims_graph(keyword) 或 mcp_qdrant_search_claims

Step 5: 写入 watchlist
  → patch entry_zone 字段，跑 validate_watchlist.py 确认

Step 6: Git 提交
  → commit message 含每只标的的 price_range + 方法
```

## 常见 pitfall

- **P3 标的写数字区间但注释写 '不建议介入'** → parse_price_zone 不读注释，只提数字 → poll 会当成有效区间。**解法**：P3 标的 post-fix 必须跑 `validate_watchlist.py` 确认 price_range 格式一致
- **Sina API 返回 30min K 线而非日K** → `scale=240` 是日K（240分钟=4小时），`scale=30` 是 30分钟线。确认 URL 参数
- **akshare RemoteDisconnected** → 被限流，退回到新浪 API