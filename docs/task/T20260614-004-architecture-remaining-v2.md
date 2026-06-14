# T20260614-004 架构剩余任务 v2

> 状态: ✅ **全部完成**（2026-06-15）
> 总耗时: 约 4.5 天（Subtask 1: 3天 + Subtask 2: 0.5天 + 测试/文档: 1天）

---

## 1. 任务概览

本任务完成架构设计文档中剩余的两个核心组件：

| 编号 | 组件 | 优先级 | 估算 | 状态 |
|------|------|:------:|:----:|:----:|
| 1 | 事件驱动行情管线 (WebSocket) | P1 | 3天 | ✅ |
| 2 | CitationValidator 引用校验器 | P1 | 0.5天 | ✅ |

---

## 2. 交付物清单

### 2.1 Subtask 2: CitationValidator（0.5天）✅

| 文件 | 说明 | 测试 |
|------|------|:----:|
| `src/qing_investment/agent/validators/citation_validator.py` | 纯规则驱动的引用校验器 | 23/23 ✅ |
| `tests/test_citation_validator.py` | 23 个测试用例 | 全部通过 |

**核心功能：**
- 正则提取数字 claim（价格、百分比、成交量、区间如 30.5-31.0元）
- 检查每个 claim 是否有来源标注（来源/数据/claim ID/参考来源段落）
- 跨句引用隔离（避免前面句子的引用被后面句子借用）
- 章节跳过（操作建议/风险提示等不检查）
- 覆盖率统计 + 阈值控制（默认 60%）
- 人类可读的格式化报告输出

### 2.2 Subtask 1.1: WsQuoteClient WebSocket 客户端（1天）✅

| 文件 | 说明 | 测试 |
|------|------|:----:|
| `src/qing_investment/monitor/fetchers/ws_client.py` | WebSocket 行情客户端 | 12/12 ✅ |
| `tests/test_ws_client.py` | 12 个测试用例 | 全部通过 |

**核心功能：**
- `connect()` / `subscribe()` / `read_events()` / `close()` 标准接口
- `QuoteEvent` 数据类（code, price, change_pct, volume, timestamp）
- 自动重连（指数退避）
- 心跳保活
- 事件流生成器

### 2.3 Subtask 1.2: WsEventDrivenFetcher 集成包装器（1天）✅

| 文件 | 说明 | 测试 |
|------|------|:----:|
| `src/qing_investment/monitor/fetchers/ws_event_fetcher.py` | 事件驱动行情获取器 | 11/11 ✅ |
| `tests/test_ws_event_fetcher.py` | 11 个测试用例 | 全部通过 |

**核心功能：**
- 将 WsQuoteClient 事件流转换为 `quote_snapshot` 格式（兼容 scheduler）
- 事件去重（500ms 窗口内同一标的合并）
- 断路器（3次失败 → 打开 → 1小时后自动恢复）
- HTTP 降级（断路器打开后自动切换到 HTTP 轮询）
- 动态更新订阅标的
- 缓存快照构建

**集成方式：**
```python
# Scheduler 中使用
fetcher = WsEventDrivenFetcher(
    http_fetcher=scheduler._fetch_quotes,  # 降级时调用
    codes=scheduler.config.watchlist_codes,
)
await fetcher.start()
snapshot = await fetcher.get_snapshot()  # 实时缓存数据
```

### 2.4 Subtask 1.3: B站增量 diff + claims 去重（0.5天）✅

| 文件 | 说明 | 测试 |
|------|------|:----:|
| `src/qing_investment/monitor/deduplicator.py` | Claims 去重器 | 8/8 ✅ |
| `tests/test_deduplicator.py` | 8 个测试用例 | 全部通过 |

**核心功能：**
- 对比本地缓存，仅新内容入 claims pipeline
- 内存缓存最近 50 条 claims（指纹去重）
- 缓存持久化（JSON 文件）
- 指纹规范化（去除空格/标点，避免格式差异导致误判）
- Diff 日志记录

**使用方式：**
```python
from qing_investment.monitor.deduplicator import deduplicate_bilibili_claims

result = deduplicate_bilibili_claims(new_claims, cache_dir=Path("temp/bilibili_diff"))
if result.has_new:
    process(result.new_claims)  # 仅新 claims 入 pipeline
```

---

## 3. 测试汇总

| 测试文件 | 用例数 | 状态 |
|----------|:------:|:----:|
| `tests/test_citation_validator.py` | 23 | ✅ 通过 |
| `tests/test_ws_client.py` | 12 | ✅ 通过 |
| `tests/test_ws_event_fetcher.py` | 11 | ✅ 通过 |
| `tests/test_deduplicator.py` | 8 | ✅ 通过 |
| **总计** | **54** | **✅ 全部通过** |

运行命令：
```bash
cd /home/ubuntu/learning-investment-strategies
python -m pytest tests/test_citation_validator.py tests/test_ws_client.py tests/test_ws_event_fetcher.py tests/test_deduplicator.py -v
```

---

## 4. 架构说明

### 4.1 事件驱动行情管线架构

```
┌─────────────────┐     ┌──────────────┐     ┌──────────────────┐
│  WebSocket 服务端 │────▶│ WsQuoteClient │────▶│ WsEventDriven   │
│  (行情推送)       │     │ (连接/订阅)   │     │ Fetcher          │
└─────────────────┘     └──────────────┘     │ (去重/断路/降级)  │
                                             └────────┬─────────┘
                                                      │
                              ┌───────────────────────┘
                              ▼
                       ┌──────────────┐
                       │  Scheduler   │
                       │ (tick/eval)  │
                       └──────────────┘
                              │
                              ▼
                       ┌──────────────┐
                       │  Agent       │
                       │ (分析/决策)  │
                       └──────────────┘
```

**降级路径：**
```
WsQuoteClient 连接失败 ×3 → 断路器打开 → 自动降级到 HTTP 轮询 → 1小时后重试 WS
```

### 4.2 B站 Claims 处理流程

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│ fetch_bilibili  │────▶│ extract claims   │────▶│ BilibiliClaims  │
│ _up_v2.py       │     │ (LLM/规则)       │     │ Deduplicator    │
└─────────────────┘     └──────────────────┘     └────────┬────────┘
                                                            │
                              ┌─────────────────────────────┘
                              ▼
                       ┌──────────────┐
                       │ 新 claims?   │──Yes──▶ extract_claims_pipeline
                       │              │──No───▶ 跳过（记录日志）
                       └──────────────┘
```

### 4.3 CitationValidator 在 Agent 输出流程中的位置

```
Agent 生成输出
     │
     ▼
┌─────────────────┐
│ CitationValidator│── 检查数字 claim 是否有引用来源
│ (规则校验)       │── 覆盖率 < 60% → 标记警告
└────────┬────────┘
         │
    ┌────┴────┐
    ▼         ▼
 通过      警告
    │         │
    ▼         ▼
 发送    补充引用后重发
```

---

## 5. 后续建议

### 5.1 生产环境部署 checklist

- [ ] WsQuoteClient 接入真实 WebSocket 行情源（需配置 URL、认证参数）
- [ ] Scheduler 配置 `ws_mode: true` 启用事件驱动模式
- [ ] B站监控 cron 任务集成 `BilibiliClaimsDeduplicator`
- [ ] CitationValidator 接入 Agent 输出后处理流程
- [ ] 监控告警：断路器状态、降级次数、缓存命中率

### 5.2 性能优化方向

1. **WsEventDrivenFetcher**: 考虑使用环形缓冲区替代 dict 缓存，减少 GC 压力
2. **BilibiliClaimsDeduplicator**: 指纹算法可升级为 simhash（语义相似去重）
3. **CitationValidator**: 可扩展支持 LLM-based 引用验证（更智能但成本更高）

---

## 6. 变更记录

| 日期 | 变更 | 作者 |
|------|------|------|
| 2026-06-14 | 创建任务文档 | Agent |
| 2026-06-15 | 完成 CitationValidator | Agent |
| 2026-06-15 | 完成 WsQuoteClient | Agent |
| 2026-06-15 | 完成 WsEventDrivenFetcher | Agent |
| 2026-06-15 | 完成 BilibiliClaimsDeduplicator | Agent |
| 2026-06-15 | 全部测试通过（54/54） | Agent |
