# 东方财富 API 差异限流模式 — 分级别降级策略

> 经验证：2026-07-22 09:47 BJT 集合竞价后，clist/get 返回空响应(rc=102)，ulist.np/get 仍正常返回 3 轮后也限流。

## 现象

东方财富 push2 公网 API 存在**基于接口级别的差异限流**，而非全局统一限流：

| API 端点 | 功能 | 限流阈值 | 2026-07-22 行为 |
|----------|------|---------|-----------------|
| `push2.eastmoney.com/api/qt/clist/get` | 板块排行、全市场排序、条件筛选 | **最低** | 始终返回空或 rc=102 |
| `push2.eastmoney.com/api/qt/ulist.np/get` | 已知 secid 的个股/指数批量报价 | 中等 | 前 3 次调用正常，后续也返回空 |
| `push2.eastmoney.com/api/qt/stock/get` | 单只个股深度数据 | 最高（?） | 2026-07-22 17:00 复盘验证：即使单次请求（1.000001+fields=f43）+ UA 头，也返回 `Remote end closed connection without response`。**
实际结论：所有 push2 端点在同一 IP 上 均已不可用，非分级别差异** |
| push2.eastmoney.com/api/qt/clist/get | 板块排行等 | 最低 | 2026-07-22 同一 IP 返回空串（无报错、无数据） |
| push2.eastmoney.com/api/qt/clist/get (m:90+t:2 行业板块) | 行业板块 | per-minute 1-2次 | 2026-07-24: 成功1-2次后~30s内返回空；t:2和t:3共享同一限流桶 |
| push2.eastmoney.com/api/qt/clist/get (m:0+t:6+f:!50 全市场) | 全市场个股列表 | 独立桶更宽松 | 2026-07-24: sector已限流时此端点仍可用 |
| push2.eastmoney.com/api/qt/ulist.np/get | 已知secid指数/个股 | 独立桶更宽松 | 2026-07-24: sector已限流时此端点仍可用 |
## 应对策略

### 原则
发现 clist/get 失败后，**不要假定整个 EM 都挂了**。按以下顺序尝试：

1. **先试 `ulist.np/get`**（通过 `fetch_eastmoney_quotes()` 或直接构造 URL）
   - 成功 → 获得指数 + 核心标的报价，虽无板块排行，可做基础分析
   - 失败 → 跳到步骤 2

2. **切换到路径 D（Tencent API，`qt.gtimg.cn`）**
   - 极稳定，几乎不受限流影响
   - 仅需 curl / urllib，零依赖

### `fetch_eastmoney_quotes()` 用法

项目代码中已有封装函数。在 venv 中直接调用：

```python
import sys
sys.path.insert(0, 'src')
from qing_investment.stock_monitor import fetch_eastmoney_quotes

targets = {
    '上证指数': '1.000001',
    '深证成指': '0.399001',
    '创业板指': '0.399006',
    '科创50': '1.000688',
}
result = fetch_eastmoney_quotes(targets)
# result['quotes'] = list of {secid, label, code, name, latest, pct_change, ...}
# result['errors'] = list of error strings for failed targets
```

**secid 格式**：`交易所编号.代码`
- 上交所：`1.` 前缀（如 `1.000001`, `1.688xxx`, `1.6xxxxx`）
- 深交所：`0.` 前缀（如 `0.002409`, `0.399001`, `0.3xxxxx`）

此函数不依赖任何额外库（仅 urllib + json），解包即可用。

### 完整降级序列（2026-07-22 验证）

```
发现 clist/get 失败 (板块数据拿不到)
    ↓
尝试 ulist.np/get → 成功 (指数+个股行情)
    ↓ 3轮后也限流
尝试 Tencent API (qt.gtimg.cn) → 稳定成功
    ↓
Neo4j 关键词搜索 (替代 Qdrant 语义搜索, huggingface-hub 版本冲突时)
    ↓
最终报告: 指数+个股来自 Tencent, 板块强弱靠宽基指数差值推断, 周期判断来自 claims
```

## 已知限制

- `ulist.np/get` 要求预先知道 secid，无法做"板块排行"或"全市场按条件排序"
- 限流阈值与 IP 相关，更换节点可能恢复
- Tencent API 不提供板块排行数据（见 `references/tencent-finance-api-fallback.md`）
