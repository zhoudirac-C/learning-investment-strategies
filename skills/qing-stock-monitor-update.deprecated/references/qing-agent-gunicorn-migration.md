# Qing-Agent: Uvicorn → Gunicorn 迁移指南

> **触发**：2026-06-10 排查 Qing-Agent `/analyze/trigger` 挂死根因时，发现 uvicorn 单 worker 串行排队问题，尝试迁移到 gunicorn。
> **结论**：gunicorn 单 worker（`-w 1`）替代 uvicorn，获得更好的进程管理；多 worker 因 Qdrant 本地模式限制不可行。

---

## 问题背景

**症状**：Qing-Agent `/health` 返回 OK，但 `/analyze/trigger` 挂死，全部 cron 走 fallback。

**根因**：uvicorn 单 worker 串行处理请求。LangGraph 管线耗时 30s+，脚本超时 45s。第一个慢请求触发超时后，worker 仍在后台处理（无中断机制），后续请求排队等待 → 全部超时。

**验证**：
- 单请求：30s 完成 ✅
- 5 并发：前 4 个超时，第 5 个才返回 → 证实串行排队

---

## Uvicorn vs Gunicorn 通俗解释

| | Uvicorn | Gunicorn |
|---|---|---|
| **角色** | 轻量级 HTTP 前台 | 餐厅经理 + 多个前台 |
| **worker 数** | 1 个（默认） | 可配置多个 |
| **进程管理** | 无（崩溃即停止） | 有（崩溃自动重启、优雅关闭） |
| **并发处理** | 单进程串行 | 多进程并行 |
| **适用场景** | 开发、低负载 | 生产、高可用 |

**gunicorn 启动命令**：
```bash
gunicorn qing_investment.agent.main:app \
  -w 2 \                           # 2 个 worker
  -k uvicorn.workers.UvicornWorker \  # 每个 worker 都是 Uvicorn
  --bind 127.0.0.1:8000
```

---

## 多 Worker 尝试失败：Qdrant 本地模式限制

**测试**：`gunicorn -w 2` 启动后，并发请求触发错误：

```
RuntimeError: Storage folder /path/to/.qdrant_data is already accessed
by another instance of Qdrant client. If you require concurrent access,
use Qdrant server instead.
```

**原因**：`QdrantClient(path="...")` 使用本地 SQLite + portalocker 独占锁。进程 A 打开后，进程 B 无法同时打开。

**代码位置**：`src/qing_investment/agent/tools/qdrant_client.py:25`
```python
self._client = QdrantClient(path=self.local_path)  # 本地模式 = 独占锁
```

**解决方案对比**：

| 方案 | 做法 | 效果 | 工作量 |
|---|---|---|---|
| A. 单 worker gunicorn | `-w 1` | 进程管理优势，无并发提升 | 已实施 ✅ |
| B. Qdrant Server | `docker run -p 6333:6333 qdrant/qdrant` | 真正多 worker 并发 | 需部署容器 + 改代码 |
| C. 代码级单例 | 全局共享 QdrantClient | 多 worker 共享一个连接 | 需重构初始化逻辑 |

**当前选择：方案 A**（gunicorn 单 worker）。cron 场景是串行触发（9 个定点，不会同时到达），单 worker 足够。

---

## 已实施的修复

### 1. 脚本超时 + 重试（`hermes_stock_monitor_agent.py`）

```python
QING_AGENT_TIMEOUT = float(os.environ.get("QING_AGENT_TIMEOUT", "120"))
QING_AGENT_MAX_RETRIES = int(os.environ.get("QING_AGENT_MAX_RETRIES", "3"))

def call_qing_agent(data: dict) -> dict | None:
    for attempt in range(QING_AGENT_MAX_RETRIES):
        try:
            req = urllib.request.Request(
                QING_AGENT_URL,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=QING_AGENT_TIMEOUT) as resp:
                return json.loads(resp.read())
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < QING_AGENT_MAX_RETRIES - 1:
                time.sleep(2 ** attempt)  # 1s, 2s, 4s
            else:
                return None
```

### 2. Gunicorn 单 Worker 启动

```bash
cd ~/learning-investment-strategies
nohup .venv/bin/gunicorn qing_investment.agent.main:app \
  -w 1 -k uvicorn.workers.UvicornWorker \
  --bind 127.0.0.1:8000 \
  --timeout 120 --keep-alive 5 \
  > /tmp/qing-agent.log 2>&1 &
```

**参数说明**：
| 参数 | 含义 |
|---|---|
| `-w 1` | 1 个 worker（Qdrant 本地模式限制） |
| `-k uvicorn.workers.UvicornWorker` | 每个 worker 用 Uvicorn 处理 ASGI |
| `--timeout 120` | worker 处理请求的最大时间 |
| `--keep-alive 5` | HTTP keep-alive 连接保持 5s |

### 3. 成功/失败显式标记

```python
# 成功
print("[Qing-Agent ✓] 分析完成")
print(result["final_output"])

# 失败 fallback
print("[Qing-Agent ✗ FALLBACK] Qing-Agent 不可达，使用本地 LLM 生成分析")
print(fallback_text)
```

---

## 验证方法

```bash
# 1. 检查进程
pgrep -a -f "gunicorn"
# 应看到：master (PID X) + worker (PID Y)

# 2. 健康检查
curl -s http://localhost:8000/health
# {"status":"ok","version":"0.1.0"}

# 3. 实际端点测试（必须测这个，不能只看 /health）
curl -s --max-time 30 -X POST http://localhost:8000/analyze/trigger \
  -H "Content-Type: application/json" \
  -d '{"query":"测试","session_id":"test-001","analysis_type":"market"}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('OK' if d.get('final_output') else 'FAIL')"
```

---

## 未来升级路径

如需真正多 worker 并发（例如同时处理多个用户的 `/chat` 请求）：

1. **部署 Qdrant Server**：
   ```bash
   docker run -d -p 6333:6333 qdrant/qdrant:v1.9.7
   ```

2. **修改代码为远程模式**：
   ```python
   # qdrant_client.py
   self._client = QdrantClient(host="localhost", port=6333)  # 远程模式
   ```

3. **gunicorn 多 worker**：
   ```bash
   gunicorn -w 2 -k uvicorn.workers.UvicornWorker --bind 127.0.0.1:8000
   ```

> **注意**：Qdrant Server 模式需要 Docker，当前 VM 网络限制可能无法拉取镜像。需先解决 Docker 可用性问题。
