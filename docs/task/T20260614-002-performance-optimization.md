# Task: 监控引擎性能优化 — 并发Fetch + 缓存策略

> 任务ID: T20260614-002
> 优先级: 🟡 P1
> 状态: 待执行
> 创建: 2026-06-14
> 触发: 架构优化方案 v1.1 §2.2（竞品分析发现1/2）+ 瘦身完成后性能瓶颈诊断
> 参考设计: `docs/design/architecture-optimization-plan.md`

---

## 一、任务背景

瘦身完成后，监控引擎的模块化拆分已就绪，但**性能层面未优化**。参考竞品 AlphaAnalyst 的架构设计：

> "LLM是writer不是knower" + "10个Fetcher并发" + "纯Python估值"

当前痛点：

| 问题 | 现状 | 影响 |
|------|------|------|
| 串行Fetch | 每次tick逐个拉取行情 | 耗时2-5秒，错过盘中突变 |
| 无缓存层 | 每次tick重复请求相同数据 | 浪费API配额，延迟高 |
| 竞价值缓存原始 | 只存了raw数据 | 重复计算竞价指标 |
| 无数据新鲜度标记 | 无法判断数据是否够新 | 可能基于过期数据做决策 |

---

## 二、优化目标

1. **Tick延迟 < 1秒**（当前2-5秒）
2. **缓存命中率 > 60%**（同日内重复请求减少）
3. **并发Fetch覆盖所有独立数据源**
4. **数据新鲜度可追踪**

---

## 三、子任务清单

### Subtask 1: 并发Fetch层

**优先级**: 🔴 P0 | **预估工时**: 3-4h | **依赖**: T20260614-001（瘦身完成）

核心思路：将串行HTTP请求改为 `asyncio.gather` 并发。

**设计要点**:
- 当前 `fetch_quotes_with_fallback` 是同步串行 → 改为 `asyncio` 并发
- 按数据源分组（行情×1、龙虎榜×1、竞价×1）
- 超时统一控制（single_fetch_timeout=3s, total_timeout=5s）
- 失败隔离：一个源失败不影响其他

```python
# 目标接口
async def fetch_all(
    config: MonitorConfig,
) -> dict:
    """并发获取所有数据源。"""
    tasks = {
        "quotes": fetch_quotes(config),
        "dragon_tiger": fetch_dragon_tiger(config),
        "auction": fetch_auction_snapshot(config),
    }
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    # 处理部分失败
    ...
```

**验收标准**:
- [ ] 并发Fetch正确实现（asyncio.gather）
- [ ] 超时控制生效（>5s 自动降级）
- [ ] 单源失败不阻塞整体
- [ ] `run_tick` 集成后延迟 < 1秒

---

### Subtask 2: 内存缓存层

**优先级**: 🟡 P1 | **预估工时**: 2-3h | **依赖**: Subtask 1

核心思路：为行情、竞价、龙虎榜数据添加TTL缓存。

**设计要点**:
- TTL缓存（行情30秒，龙虎榜5分钟，竞价10分钟）
- 缓存key = `{data_type}:{stock_code}:{date}`
- 支持条件刷新（价格突破时强制刷新）
- 缓存命中统计（后续可调优）

```python
# 目标接口
class DataCache:
    def get(self, key: str) -> Any | None: ...
    def set(self, key: str, value: Any, ttl: int = 30) -> None: ...
    def invalidate(self, pattern: str) -> None: ...
    def stats(self) -> dict: ...  # 命中率/大小/过期数
```

**验收标准**:
- [ ] TTL过期自动失效
- [ ] 缓存命中率可追踪
- [ ] 不增加内存泄漏风险（上限控制）
- [ ] 行情数据30秒内复用

---

### Subtask 3: 竞价数据缓存优化

**优先级**: 🟡 P1 | **预估工时**: 1-2h | **依赖**: Subtask 2

核心思路：当前 `_update_auction_cache` / `_load_auction_cache` 是文件JSON，改为分层（内存+文件）。

**优化点**:
- 当日竞价数据走内存缓存（Subtask 2）
- 历史竞价数据走JSON文件（现有机制，保留）
- 竞价量比预计算（`_compute_auction_volume_ratio` 结果缓存）

**验收标准**:
- [ ] 当日竞价数据不再重复读文件
- [ ] 竞价指标（量比/对比）缓存复用
- [ ] 向后兼容现有 auction_cache JSON

---

### Subtask 4: 配置热更新性能优化

**优先级**: 🟢 P2 | **预估工时**: 1h | **依赖**: 无

核心思路：当前 `ConfigWatcher` 每次tick都检查文件修改时间，改为inotify事件驱动。

**优化点**:
- 用 `watchdog` 库替代轮询（避免每次tick 1次stat调用）
- 配置变更时标记缓存失效（关联Subtask 2的缓存层）
- 降级：如果 `watchdog` 不可用，回退到5秒interval轮询

**验收标准**:
- [ ] 配置变更后 < 1秒触发重载
- [ ] 不增加额外tick开销
- [ ] 降级方案可用

---

## 四、执行顺序

```
Subtask 1 (并发Fetch) → Subtask 2 (内存缓存) → Subtask 3 (竞价缓存优化) → Subtask 4 (热更新优化)
```

**依赖关系**:
- Subtask 2 依赖 Subtask 1（缓存的数据来源是并发Fetch的结果）
- Subtask 3 依赖 Subtask 2（复用缓存层）
- Subtask 4 无依赖，可并行

**总工时**: 7-10 小时（1-2个工作日）

---

## 五、验收标准（整体）

- [ ] `run_tick` 常规执行 ≤ 1秒
- [ ] 缓存命中率 ≥ 60%（日志可查）
- [ ] 单源数据失败不阻塞tick
- [ ] 配置变更热重载 ≤ 1秒
- [ ] 无内存泄漏（运行4小时后内存稳定）

---

## 六、风险与应对

| 风险 | 概率 | 影响 | 应对 |
|------|------|------|------|
| asyncio 改造影响现有同步代码 | 中 | 高 | 渐进式：先包装异步接口，保留同步兼容层 |
| 缓存数据过期导致错误判断 | 低 | 高 | 强制刷新机制（价格突破时 invalidate） |
| watchdog 库依赖 | 低 | 中 | try-import，降级到轮询 |
| 并发Fetch导致API限流 | 中 | 中 | 控制并发数 ≤ 5，加指数退避重试 |

---

## 七、相关文档

| 文档 | 路径 |
|------|------|
| 架构优化方案 v1.1 | `docs/design/architecture-optimization-plan.md` |
| 监控瘦身任务 | `docs/task/T20260614-001-monitor-slimming.md` |
| 监控技术设计 | `docs/hermes-stock-monitor-technical-design.md` |

---

*任务版本: v1.0*
*创建: 2026-06-14*
*状态: 待执行*
