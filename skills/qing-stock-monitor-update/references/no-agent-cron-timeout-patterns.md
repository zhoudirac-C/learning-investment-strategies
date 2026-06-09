# no-agent Cron 超时陷阱与防御模式

## 问题

Hermes 对 `no_agent: true` 的 cron job 有**隐式超时（约 120 秒）**。
脚本执行超过此时限会被 kill 并报告 `error`，即使部分工作已完成。

## 防御模式

### 模式 A：增量 + 高频 cron（适合全量构建类任务）

适用于：缓存重建、数据同步等长耗时（>2分钟）任务。

```
旧: 30 8 * * 1-5     （每天一次，失败则全天无缓存）
新: */30 6-8 * * 1-5  （盘前 6 次，每次 <2min 增量跳过）
```

**脚本端**：
1. 开头检查缓存是否新鲜（TTL内），新鲜则 `sys.exit(0)` 秒级返回
2. 缓存过期才执行全量构建
3. 第 1 次 cron 可能超时，但缓存已部分写入 → 第 2 次（30分钟后）检测到缓存存在且有效，秒级跳过

**效果**：6 次 cron 中至少 1 次成功，失败自动恢复，不依赖单次超时。

### 模式 B：`--force`/`--max-sectors` 必须防御缓存破坏

**反面案例**：`build_sector_mapping.py --force --max-sectors 5` 将 4331 条全量缓存覆盖为 242 条。

**根因**：`--max-sectors` 是测试/限制参数，但底层 `build_stock_sector_mapping()` 无条件调 `_save_mapping_cache()`。

**修复**：增加 `save_cache` 参数，测试模式 `save_cache=False`：

```python
def build_stock_sector_mapping(
    max_sectors: int | None = None,
    progress_callback: callable | None = None,
    save_cache: bool = True,  # ← 关键
) -> dict[str, list[dict]]:
    ...
    if save_cache:
        _save_mapping_cache(mapping)
```

调用端：
```python
build_stock_sector_mapping(
    max_sectors=args.max_sectors,
    progress_callback=_progress,
    save_cache=args.max_sectors is None,  # 限制模式不写缓存
)
```

**通用规则**：任何带 `--max-*` / `--limit` / `--dry-run` 的构建类脚本，必须确保这些标志不会触发生产数据写入。

### 模式 C：HTTP 层重试 + 退避

适用于：依赖外部 API 的长运行脚本。

```python
_HTTP_RETRY_COUNT = 3
_HTTP_RETRY_BACKOFF_BASE = 5.0  # 5s, 10s, 20s

def _http_get(url, timeout=30.0, retries=3):
    for attempt in range(1, retries + 1):
        try:
            ...
        except Exception as e:
            if attempt < retries:
                wait = _HTTP_RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
                time.sleep(wait)
    raise last_err
```

关键参数：
- timeout: 10s → **30s**（新浪等中国金融 API 响应慢）
- 重试 3 次，指数退避（5s → 10s → 20s）
- 不重试 4xx（无意义），只重试网络超时/连接重置

### 模式 D：`python -u` 非缓冲输出

cron 环境是非 TTY，Python 默认缓冲 stdout。脚本可能已运行但看不到任何输出。

```bash
# ❌ 输出可能被缓冲，cron 日志为空
python scripts/build_sector_mapping.py

# ✅ 实时刷新输出
python -u scripts/build_sector_mapping.py
```

或脚本内加：
```python
import sys
sys.stdout.reconfigure(line_buffering=True)  # Python 3.7+
```

## 验证方法

1. 运行 `--force --max-sectors N` 后立即检查缓存文件大小不变
2. cron 执行后检查 `~/.hermes/cron/output/<job_id>/` 的日志
3. 脚本加 `--verbose` 时，确认日志行在运行过程中逐渐出现（而非结束后一次性输出）
