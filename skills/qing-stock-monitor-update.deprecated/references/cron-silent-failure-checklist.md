# Cron 静默失败排查清单

> status=ok + 输出 0 字节 ≠ 一切正常。此清单用于快速诊断 cron 静默失败。

## 一、检查输出文件大小

```bash
ls -lt ~/.hermes/cron/output/<job_id>/ | head -3
stat -c%s ~/.hermes/cron/output/<job_id>/<latest_file>
# 0 字节 → 静默失败（无 error 信号）
```

## 二、三级排查链

### 1. 脚本存在性

```bash
# 检查 cron job 的 script 字段引用的文件是否存在
ls -la scripts/<script_name>
```

**常见失败模式**：文件重命名/删除 → cron 仍引用旧名 → scheduler 静默跳过。

### 2. subprocess 调用链

脚本 A 可能 subprocess 调用脚本 B。B 的路径硬编码 → B 重命名后 A 内部静默失败。

```bash
# 手动执行脚本观察 stdout/stderr
cd ~/learning-investment-strategies
PYTHONPATH=src timeout 30 .venv/bin/python scripts/<script_name> 2>&1

# 直接复现 cron 调用的底层命令（绕过外层脚本）
PYTHONPATH=src .venv/bin/python -m qing_investment.stock_monitor --ignore-trading-time
```

**常见失败模式**：`scripts/stock_monitor.py` 改为 `-m qing_investment.stock_monitor` 前，硬编码文件路径在文件重命名后全部失效。

### 3. Qing-Agent 真正可用性

```bash
# /health 只检查进程存活，不检查 LangGraph 管线
curl -s http://localhost:8000/health          # 可能返回 OK

# /analyze/trigger 才是真正的功能测试
curl -s --max-time 30 -X POST http://localhost:8000/analyze/trigger \
  -H "Content-Type: application/json" \
  -d '{"query":"测试","session_id":"diag","analysis_type":"market"}' \
  | python3 -c "import sys,json; print('OK' if json.load(sys.stdin).get('final_output') else 'DEAD')"
# HTTP_CODE=000 + 超时 → gunicorn worker 挂死 → 需重启
```

**常见失败模式**：`/health` 返回 OK，但 `/analyze/trigger` 无响应（worker 卡在 LLM 调用或管线死循环）。gunicorn `--timeout 120` 后自动重启 worker，但期间所有请求排队超时。

### 4. YAML 格式类型错误

```bash
# 直接跑底层脚本看 traceback
PYTHONPATH=src timeout 30 .venv/bin/python -m qing_investment.stock_monitor --ignore-trading-time 2>&1
# TypeError: unhashable type: 'dict' → YAML 中 list 元素是 dict 但代码期望 str
# KeyError → YAML 缺少必填字段
```

## 三、快速全链路验证

```bash
cd ~/learning-investment-strategies

# 1. no-agent 轮询（验证底层 stock_monitor 无 crash）
PYTHONPATH=src timeout 30 .venv/bin/python -m qing_investment.stock_monitor --ignore-trading-time
echo "poll exit=$?"

# 2. agent 管线（验证 Qing-Agent 可用）
PYTHONPATH=src timeout 120 .venv/bin/python scripts/hermes_stock_monitor_agent.py
echo "agent exit=$?"

# 3. 检查输出文件（验证不空）
ls -lt ~/.hermes/cron/output/<job_id>/ | head -3
```

## 四、常见根因速查

| 症状 | 最可能根因 | 参考陷阱 |
|------|-----------|---------|
| 0字节 + status=ok | script 字段文件名不存在 | 陷阱 20 |
| 0字节 + status=ok + 昨日正常 | subprocess 硬编码路径失效 | 陷阱 21 |
| 有内容但非 Qing-Agent 格式 | 脚本不在 ~/.hermes/scripts/，Hermes 回退 LLM | 陷阱 23 |
| HTTP_CODE=000 + 超时 | Qing-Agent worker 挂死 | 陷阱 2/2b |
| TypeError/KeyError | YAML 格式类型错误 | 陷阱 19 |
