# Qing-Agent 模型配置与服务重启

## 模型配置位置

Qing-Agent 的 LLM 模型有两层配置：

### 1. Provider 默认模型（代码硬编码）

文件：`src/qing_investment/agent/tools/llm_client.py`

```python
LLM_PROVIDERS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-v4-flash",  # ← 修改此处
        "api_key_env": "DEEPSEEK_API_KEY",
    },
    "kimi": {
        "base_url": "https://api.moonshot.cn/v1",
        "default_model": "moonshot-v1-128k",
        "api_key_env": "KIMI_API_KEY",
    },
    # ... 其他 provider
}
```

### 2. 环境变量覆盖（.env）

文件：项目根目录 `.env`

```bash
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-v4-flash      # 覆盖默认模型
DEEPSEEK_API_KEY=sk-xxx
```

优先级：`.env` 中的 `LLM_MODEL` > provider 的 `default_model`。

## 修改模型后必须重启服务

Python 模块在 import 时缓存，修改 `llm_client.py` 或 `.env` 后**必须重启 uvicorn** 才能生效。

### 重启命令（推荐：使用启动脚本）

项目已提供带环境变量的启动脚本，会自动加载 `.env` 并使用远端 provider 链：

```bash
cd ~/learning-investment-strategies
bash scripts/start_qing_agent.sh
```

脚本核心行为：
- `source .env` 加载模型配置（`LLM_PROVIDER`、`DEEPSEEK_API_KEY` 等）
- `KIMI_CODE_ACP_FIRST` 与 `KIMI_CODE_ACP_TIMEOUT` 已注释，不再启动本地 ACP 子进程
- 设置 `QING_AGENT_TIMEOUT=1800`，覆盖大 context + reviewer retry 的最坏情况（实测约 23 分钟）

### 手动重启命令（仅调试时使用）

```bash
# 1. 停止旧服务（确保完全停止）
pkill -f "uvicorn.*qing_investment"
sleep 2
pgrep -f "uvicorn.*qing_investment" || echo "已停止"

# 2. 启动新服务
cd ~/learning-investment-strategies
set -a
source .env
set +a
# 大 context + reviewer 多轮 retry 实测可达 23 分钟，给足余量
export QING_AGENT_TIMEOUT=1800
.venv/bin/uvicorn qing_investment.agent.main:app --host 127.0.0.1 --port 8000 &

# 3. 验证
sleep 2
curl -s http://127.0.0.1:8000/health
# → {"status":"ok","version":"0.1.0"}
```

### 常见陷阱

- **kill 后进程仍在**：uvicorn 有自动重启机制，单 kill 可能触发子进程重新拉起。使用 `pkill -f` 确保全部终止。
- **后台启动用 `&`**：手动调试时直接用 `&` 或 `terminal(background=true)`。`scripts/start_qing_agent.sh` 因被 cron 调用，使用 `nohup`。
- **验证健康检查**：启动后必须 `curl /health` 确认，不要假设启动成功。
- **本地 ACP 已禁用**：`_safe_llm_invoke()` 的 ACP 优先路由与 `get_llm_client()` 的 ACP 客户端创建代码均已注释；即使设置 `KIMI_CODE_ACP_FIRST=1` 也不会生效。运行日志不应再出现 `KimiCodeAcpClient` 或 `kimi acp` 子进程。

## 与 Hermes 模型统一

当前环境配置：

| 组件 | 模型 | Provider |
|------|------|----------|
| Hermes 主代理 | kimi-for-coding | custom:kimicode |
| Hermes 子代理 | kimi-for-coding | custom:kimicode |
| Qing-Agent | deepseek-v4-flash | deepseek |

若需将 Qing-Agent 也切到 kimi-for-coding：
1. 改 `.env`：`LLM_PROVIDER=kimi` + `KIMI_API_KEY=sk-xxx`
2. 确认 `llm_client.py` 中 kimi 的 `default_model` 支持 `kimi-for-coding`（当前为 `moonshot-v1-128k`，可能需要新增 provider 条目或覆盖 `LLM_MODEL`）
3. 重启服务
