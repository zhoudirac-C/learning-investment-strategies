# 数据源降级链：腾讯 → 新浪 → 东财

> 2026-06-10 修复。解决服务器 IP 被东方财富严格限流的问题。

---

## 问题现象

`stock_monitor.py` 调用 `akshare` → 东方财富 API 获取实时行情，服务器 IP 被严格限流：
- 连续请求返回 `RemoteDisconnected`
- 脚本阻塞重试直至超时
- cron job 静默失败，无行情数据

手动验证：`akshare.stock_zh_index_spot_em()` 同样触发限流，确认是数据源层面问题。

---

## 根因分析

**旧逻辑（问题）：**
```python
def fetch_quotes_with_fallback(targets):
    # 1. 东财优先
    em_result = fetch_eastmoney_quotes(targets)
    if not em_errors and len(em_quotes) >= len(targets):
        return em_result  # 东财正常时返回
    
    # 2. 东财失败才尝试腾讯
    tencent_result = fetch_tencent_quotes(targets)
    if tencent_quotes:
        return tencent_result
    
    # 问题：东财返回 0 quotes + errors 时，不会触发降级！
    # 因为 len(em_quotes)=0 < len(targets)，但 em_errors 存在时仍返回 em_result
```

**问题点：**
1. 东财对服务器 IP 限流严格，大量请求时返回空响应
2. 判断条件 `len(em_quotes) >= len(targets)` 在限流时失败，但后续逻辑未正确降级
3. 腾讯接口实际可用（测试 184/184 标的正常返回），但从未被优先尝试

---

## 修复方案

### 新降级链

```
腾讯(gtimg) 优先 → 新浪(hq.sinajs.cn) 备用 → 东财(push2) 兜底 → 合并兜底
```

| 优先级 | 数据源 | 成功条件 | 特点 |
|--------|--------|----------|------|
| 1 | 腾讯 `qt.gtimg.cn` | 返回 ≥80% 标的 且 无错误 | 对服务器IP最友好，响应快 |
| 2 | 新浪 `hq.sinajs.cn` | 返回数据 且 无错误 | 备用，支持批量 |
| 3 | 东财 `push2.eastmoney.com` | 返回数据 且 无错误 | 数据最全但限流严格 |
| 兜底 | 合并所有可用源 | 任意源有数据 | 补充缺失标的，汇总错误 |

### 新增函数

**`fetch_sina_quotes(targets)`**：
- 接口：`https://hq.sinajs.cn/list=sh600519,sz000001`
- 格式：`var hq_str_sh600519="贵州茅台,1740.00,...";`
- 批量限制：chunk_size=80
- 编码：GBK → UTF-8
- 字段：name, pre_close, latest, high, low, volume, amount

**`_merge_quotes(base, extra)`**：
- 以 base 为主，extra 补充缺失的 secid
- 去重逻辑：secid 为 key

### 新 `fetch_quotes_with_fallback()` 逻辑

```python
def fetch_quotes_with_fallback(targets):
    # 1. 腾讯优先
    tencent_result = fetch_tencent_quotes(targets)
    tencent_quotes = tencent_result.get("quotes", [])
    tencent_errors = tencent_result.get("errors", [])
    if len(tencent_quotes) >= len(targets) * 0.8 and not tencent_errors:
        return tencent_result  # 腾讯完全成功
    
    # 2. 新浪备用
    sina_result = fetch_sina_quotes(targets)
    sina_quotes = sina_result.get("quotes", [])
    sina_errors = sina_result.get("errors", [])
    if sina_quotes and not sina_errors:
        if tencent_quotes:
            merged = _merge_quotes(tencent_quotes, sina_quotes)
            return {"source": "tencent_gtimg+sina_hq", "quotes": merged, "errors": []}
        return sina_result
    
    # 3. 东财兜底
    em_result = fetch_eastmoney_quotes(targets)
    em_quotes = em_result.get("quotes", [])
    em_errors = em_result.get("errors", [])
    if em_quotes and not em_errors:
        return em_result
    
    # 4. 合并兜底
    best_result = tencent_result if tencent_quotes else (sina_result if sina_quotes else em_result)
    best_quotes = best_result.get("quotes", [])
    if best_quotes:
        merged = best_quotes
        if tencent_quotes and best_result is not tencent_result:
            merged = _merge_quotes(merged, tencent_quotes)
        if sina_quotes and best_result is not sina_result:
            merged = _merge_quotes(merged, sina_quotes)
        if em_quotes and best_result is not em_result:
            merged = _merge_quotes(merged, em_quotes)
        
        all_errors = []
        if tencent_errors: all_errors.append(f"腾讯: {tencent_errors[0][:80]}")
        if sina_errors: all_errors.append(f"新浪: {sina_errors[0][:80]}")
        if em_errors: all_errors.append(f"东财: {em_errors[0][:80]}")
        
        return {"source": "fallback_merged", "quotes": merged, "errors": all_errors}
    
    # 5. 完全失败
    return {
        "source": "all_failed",
        "quotes": [],
        "errors": [f"所有数据源失败。腾讯: {tencent_errors[:1]}; 新浪: {sina_errors[:1]}; 东财: {em_errors[:1]}"]
    }
```

---

## 验证结果

```bash
# 测试1: 正常场景（腾讯优先）
cd ~/learning-investment-strategies
python3 -c "
import sys; sys.path.insert(0, 'src')
from qing_investment.stock_monitor import fetch_quotes_with_fallback, collect_quote_targets, load_monitor_config
config = load_monitor_config()
targets = collect_quote_targets(config)  # 184 个标的
result = fetch_quotes_with_fallback(targets)
print(f'source={result[\"source\"]}, quotes={len(result[\"quotes\"])}/{len(targets)}, errors={result.get(\"errors\",[])}')
# 输出: source=tencent_gtimg, quotes=184/184, errors=[]
"

# 测试2: 新浪接口
python3 -c "
import sys; sys.path.insert(0, 'src')
from qing_investment.stock_monitor import fetch_sina_quotes
result = fetch_sina_quotes({'上证指数': '1.000001', '深证成指': '0.399001', '贵州茅台': '600519'})
print(f'source={result[\"source\"]}, quotes={len(result[\"quotes\"])}, errors={result.get(\"errors\",[])}')
# 输出: source=sina_hq, quotes=3, errors=[]
"

# 测试3: 东财失败场景（模拟大量标的）
python3 -c "
import sys; sys.path.insert(0, 'src')
from qing_investment.stock_monitor import fetch_eastmoney_quotes, fetch_tencent_quotes
targets = {f'stock_{i}': f'1.{600000+i:06d}' for i in range(184)}
em = fetch_eastmoney_quotes(targets)
tc = fetch_tencent_quotes(targets)
print(f'东财: quotes={len(em[\"quotes\"])}, errors={len(em[\"errors\"])}')
print(f'腾讯: quotes={len(tc[\"quotes\"])}, errors={len(tc[\"errors\"])}')
# 输出: 东财: quotes=0, errors=26; 腾讯: quotes=162, errors=0
"
```

---

## 关键参数

| 参数 | 值 | 说明 |
|------|-----|------|
| 腾讯 chunk_size | 60 | `qt.gtimg.cn` 批量限制 |
| 新浪 chunk_size | 80 | `hq.sinajs.cn` 批量限制 |
| 东财 chunk_size | 15 | `push2.eastmoney.com` 批量限制 |
| 腾讯成功阈值 | 80% | `len(quotes) >= len(targets) * 0.8` |
| 超时 | 15s | 所有接口统一 timeout |

---

## 预防复发

1. **新增数据源时**：按"对服务器IP友好度"排序，不是按"数据完整度"
2. **修改降级逻辑时**：确保"部分成功"也能触发降级（不是仅完全失败才降级）
3. **监控指标**：cron 输出中检查 `source=` 字段，若频繁出现 `eastmoney_push2` 而非 `tencent_gtimg`，说明降级链可能有问题

---

## 相关文件

- `src/qing_investment/stock_monitor.py` — `fetch_sina_quotes()`, `fetch_quotes_with_fallback()`, `_merge_quotes()`
- `references/data-source-fallback-chain.md` — 更广泛的备用方案（含 curl 命令）
