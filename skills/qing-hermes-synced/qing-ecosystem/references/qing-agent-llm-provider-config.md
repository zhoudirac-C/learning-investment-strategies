# Qing-Agent LLM Provider 配置

## 架构

Qing-Agent 通过 `src/qing_investment/agent/tools/llm_client.py` 的 `get_llm_client()` 选择 LLM provider。

路由决策链：

```
.env 中的 LLM_PROVIDER
    ↓ (被 KIMI_CODE_ACP_FIRST 覆盖)
若 KIMI_CODE_ACP_FIRST=1 → 优先本地 Kimi Code ACP（子进程 JSON-RPC）
若 KIMI_CODE_ACP_FIRST=0 → 走 LLM_PROVIDER 配置的标准 provider
```

## 配置字段（.env）

| 字段 | 示例 | 说明 |
|------|------|------|
| `LLM_PROVIDER` | `deepseek` | 目标 provider，对应 `LLM_PROVIDERS` 字典的 key |
| `KIMI_CODE_ACP_FIRST` | `0` 或 `1` | `1`=优先本地 ACP，`0`=禁用 ACP |
| `DEEPSEEK_API_KEY` | `sk-...` | DeepSeek API 密钥 |
| `KIMI_API_KEY` | `sk-...` | Kimi API 密钥 |

## 可用 Provider 列表

代码中 `LLM_PROVIDERS` 字典（`llm_client.py:105-161`）定义了以下 provider：

- `openai` — base_url=`https://api.openai.com/v1`, default_model=`gpt-4o`
- `kimi` — base_url=`https://api.moonshot.cn/v1`, default_model=`moonshot-v1-128k`
- `kimi-coding` — base_url=`https://api.kimi.com`, default_model=`kimi-k2-turbo-preview`
- `deepseek` — base_url=`https://api.deepseek.com/v1`, default_model=`deepseek-v4-flash`
- `zhipu` — base_url=`https://open.bigmodel.cn/api/paas/v4`, default_model=`glm-4.7-flash`
- `qwen` — base_url=`https://dashscope.aliyuncs.com/compatible-mode/v1`, default_model=`qwen-max`
- `kimi-code-acp` — 特殊 provider，不走 API 而是子进程 JSON-RPC 调用本地 Kimi CLI

## 典型切换场景

### 从 ACP 切回 DeepSeek API
```
.env 文件：
  LLM_PROVIDER=deepseek             # ← 已设为 deepseek
  KIMI_CODE_ACP_FIRST=0             # ← 关键：关掉 ACP 优先
  DEEPSEEK_API_KEY=sk-...           # ← 确认密钥存在
```

### 生效要求
修改 `.env` 后**必须重启 Agent**（uvicorn 进程）：
```bash
pkill -f "uvicorn qing_investment" && sleep 2
cd ~/learning-investment-strategies
nohup .venv/bin/uvicorn qing_investment.agent.main:app \
  --host 127.0.0.1 --port 8000 > /tmp/agent.log 2>&1 &
```
重启后验证：`curl localhost:8000/health` → `{"status":"ok"}`

## Agent 日志检查

Agent 启动时日志会打印当前 provider：
```
[get_llm_client] target=deepseek model=deepseek-v4-flash base_url=... has_key=True
```

若看到 `target=kimi-code-acp` 则表示 ACP 优先仍在生效。
