# 方案C（Hermes 云端子 Agent 版）

> 在云端部署 qing-agent 作为 Hermes 的**子 Agent**，Hermes 负责调度/监控/微信推送，qing-agent 负责深度投研分析（知识图谱、观点演化、UP 风格生成）。
>
> 核心变化：**Hermes 不再直接调用 Kimi API，而是把分析上下文发给云端 qing-agent，由 qing-agent 返回结构化分析结果**。

---

## 1. 现有 Hermes 架构（改造前）

```
Hermes Cloud
  ├─ Cron: 每10分钟 ──→ qing_stock_monitor.py ──→ 规则监控 ──→ 微信告警
  └─ Cron: 固定时间点 ──→ qing_stock_monitor_agent.py ──→ 输出上下文文本
                                              ↓
                                        Hermes 调用 Kimi API
                                              ↓
                                        微信推送（350字极简提醒）
```

**问题**：
- Hermes 直接调用大模型，prompt 简单（"最多350字极简微信提醒"）
- 没有知识图谱检索、没有观点演化、没有长期记忆
- 每次分析都是"无状态"的，不记得昨天说了什么

---

## 2. 改造后架构（Hermes + qing-agent 主从）

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Hermes 主服务（云端）                         │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  Cron 调度器                                                  │   │
│  │  ├─ 每10分钟 → qing_stock_monitor.py → 规则监控 → 微信告警    │   │
│  │  └─ 固定时间 → qing_stock_monitor_agent.py → 构建上下文       │   │
│  │                                               ↓              │   │
│  │                                       HTTP POST /analyze/trigger
│  │                                               ↓              │
│  │                                    ┌─────────────────────┐   │   │
│  │                                    │   qing-agent 子 Agent │   │   │
│  │                                    │  （同机或同VPC部署）   │   │   │
│  │                                    └─────────────────────┘   │   │
│  │                                               ↓              │   │
│  │                                    返回结构化分析结果        │   │
│  │                                               ↓              │   │
│  │                                    微信推送（ richer 格式）   │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
                            │
                            │ HTTP API（内网）
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      qing-agent 深度分析引擎                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐          │
│  │  Orchestrator│  │   Knowledge  │  │    Market        │          │
│  │   (LangGraph)│  │   Retriever  │  │   Analyst        │          │
│  └──────┬───────┘  │(Neo4j+Qdrant)│  └────────┬─────────┘          │
│         │          └──────┬───────┘           │                    │
│         ▼                 ▼                   ▼                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐          │
│  │    Stock     │  │    Style     │  │    Reviewer      │          │
│  │   Analyst    │  │   Writer     │  │   (事实核查)      │          │
│  └──────────────┘  └──────────────┘  └──────────────────┘          │
│                                                                     │
│  存储层：Neo4j + Qdrant + PostgreSQL + Mem0                        │
│  LLM：Kimi API (Moonshot)                                          │
└─────────────────────────────────────────────────────────────────────┘
```

**关键变化**：
1. Hermes 的 agent cron job 不再直接调用大模型，而是调用本地/同VPC的 qing-agent HTTP 接口
2. qing-agent 返回的不再是纯文本，而是**结构化 JSON**（包含 final_output、claims_cited、data_sources、confidence）
3. Hermes 可以把结构化结果渲染成更丰富的微信消息（带引用、证据表、观点演化时间线）

---

## 3. 集成点设计

### 3.1 Hermes 脚本改造

改造 `scripts/hermes_stock_monitor_agent.py`，让它把上下文发给 qing-agent 而不是直接输出给 Hermes：

```python
#!/usr/bin/env python3
import os
import sys
import subprocess
import json
import urllib.request
from pathlib import Path

QING_AGENT_URL = os.environ.get("QING_AGENT_URL", "http://localhost:8000")

def repo_root() -> str:
    configured = os.environ.get("HERMES_REPO_ROOT")
    if configured:
        return configured
    cwd = Path.cwd()
    if (cwd / "scripts" / "stock_monitor.py").exists():
        return str(cwd)
    return str(Path(__file__).resolve().parents[1])

def main():
    # 1. 先运行 stock_monitor.py 获取上下文
    command = [
        "uv", "run", "python", "scripts/stock_monitor.py",
        "--agent-context-on-trigger",
    ] + sys.argv[1:]
    
    result = subprocess.run(
        command, cwd=repo_root(), capture_output=True, text=True
    )
    context_text = result.stdout.strip()
    
    if not context_text:
        return 0
    
    # 2. 解析上下文中的结构化数据（或重新构造）
    # 更好的方式：直接调用 stock_monitor.py 的 Python API 获取结构化数据
    
    # 3. 发给 qing-agent
    payload = {
        "trigger_context": context_text,
        "session_id": "hermes-cloud-001",
        "source": "hermes_cron",
        "include_portfolio": True,
    }
    
    req = urllib.request.Request(
        f"{QING_AGENT_URL}/analyze/trigger",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            # 4. 输出最终文本给 Hermes，Hermes 直接转发微信
            print(result["final_output"])
    except Exception as e:
        # Fallback：直接输出原始上下文，让 Hermes 用原有方式处理
        print(context_text)
        print(f"\n[qing-agent error: {e}]")
    
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

### 3.2 更优方案：直接复用 stock_monitor.py 的结构化数据

上面的方案有个问题：上下文是文本，qing-agent 还要重新解析。更好的方式是：

**在 `src/qing_investment/stock_monitor.py` 中新增 `--agent-json-context` 参数**，直接输出结构化的 JSON：

```python
# stock_monitor.py 新增
import json

def format_agent_analysis_json(...) -> dict:
    """返回结构化字典，而不是文本"""
    return {
        "timestamp": value.astimezone(CN_TZ).isoformat(),
        "trigger": {
            "kind": trigger.kind,
            "title": trigger.title,
            "reason": trigger.reason,
        },
        "alerts": [alert.__dict__ for alert in alerts],
        "quote_snapshot": quote_snapshot,
        "market_framework": {
            "stage": stage,
            "core_question": core_question,
        },
        "positions": [...],  # 当前持仓
        "watchlist_focus": [...],  # 观察池关键标的
    }
```

然后 `hermes_stock_monitor_agent.py` 直接读取这个 JSON，通过 HTTP 发给 qing-agent：

```python
payload = {
    "trigger": json_context["trigger"],
    "alerts": json_context["alerts"],
    "market_snapshot": json_context["quote_snapshot"],
    "positions": json_context["positions"],
    "watchlist": json_context["watchlist_focus"],
    "session_id": "hermes-cloud-001",
}
```

### 3.3 qing-agent 的 `/analyze/trigger` 接口

```python
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class TriggerRequest(BaseModel):
    trigger: dict
    alerts: list[dict]
    market_snapshot: dict
    positions: list[dict]
    watchlist: list[dict]
    session_id: str

class TriggerResponse(BaseModel):
    final_output: str          # UP 风格的分析文本
    claims_cited: list[str]    # 引用的 claim IDs
    data_sources: list[str]    # 数据来源
    confidence: str            # high/medium/low
    review_passed: bool        # 事实核查是否通过
    reasoning_steps: list[str] # 思考步骤（可选，用于调试）

@app.post("/analyze/trigger", response_model=TriggerResponse)
async def analyze_trigger(req: TriggerRequest):
    # 构建 LangGraph 状态
    state = AgentState(
        query=f"{req.trigger['title']}：{req.trigger['reason']}",
        trigger=req.trigger,
        alerts=req.alerts,
        market_snapshot=req.market_snapshot,
        positions=req.positions,
        watchlist=req.watchlist,
        session_id=req.session_id,
    )
    
    # 运行多 Agent 工作流
    result = await graph.ainvoke(state)
    
    return TriggerResponse(
        final_output=result["final_output"],
        claims_cited=result.get("claims_cited", []),
        data_sources=result.get("data_sources", []),
        confidence=result.get("confidence", "medium"),
        review_passed=result.get("review_passed", False),
        reasoning_steps=result.get("reasoning_steps", []),
    )
```

---

## 4. 数据流与同步策略

### 4.1 问题：云端 qing-agent 需要项目数据

qing-agent 要运行，需要：
- `knowledge/claims/*.yaml` → Neo4j
- `sources/raw/财经/*.md` + `knowledge/wiki/**/*.md` → Qdrant
- `framework/persona/*.md` → Mem0 / Prompt
- `config/stock_monitor/strategy_pack.yaml` → 市场框架
- `config/stock_monitor/watchlist.yaml` → 观察池

但 `positions.yaml` 是 private 的，不能上 git。

### 4.2 同步方案

**方案 A：Git 同步公开数据 + 环境变量传私有数据（推荐）**

云端服务器：
```bash
# 1. 克隆仓库（不含 positions.yaml）
git clone git@github-personal:zhoudirac-C/learning-investment-strategies.git /opt/qing-agent

# 2. 定期 pull 更新（cron 每小时）
cd /opt/qing-agent && git pull origin master

# 3. 重新索引增量数据
uv run python scripts/delta_index.py
```

Hermes 调用时，通过 HTTP body 传入 positions 和实时行情（即 `stock_monitor.py` 的 JSON 输出），云端不需要持久化 positions。

**方案 B：全量 rsync（更实时）**

本地机器：
```bash
rsync -avz --exclude='.git' --exclude='positions.yaml' \
  ~/learning-investment-strategies/ \
  cloud-server:/opt/qing-agent/
```

每次更新 raw/claims 后手动同步，或配置 GitHub Actions 自动 rsync。

**方案 C：对象存储（更云原生）**

把 claims/wiki/raw 打包成 tar.gz，上传到 S3/OSS，云端启动时拉取。适合容器化部署。

### 4.3 推荐方案 A 的详细配置

云端 `qing-agent` 的 `config.py`：
```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Kimi API
    kimi_api_key: str
    kimi_base_url: str = "https://api.moonshot.cn/v1"
    
    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str
    
    # Qdrant
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    
    # Mem0
    mem0_api_key: str = ""  # self-hosted 可空
    mem0_base_url: str = "http://localhost:8000"
    
    # 项目路径（云端克隆的仓库）
    repo_path: str = "/opt/qing-agent"
    
    class Config:
        env_file = ".env"

settings = Settings()
```

---

## 5. 云端部署步骤

### 5.1 服务器要求

- 1 台云服务器（推荐 2C4G 起步，4C8G 更佳）
- Docker + Docker Compose 已安装
- 公网 IP（用于 Hermes 调用，或内网 VPC）
- 开放端口：8000（qing-agent，建议内网/防火墙限制）

### 5.2 部署流程

```bash
# === 在云端服务器执行 ===

# 1. 克隆项目
git clone git@github-personal:zhoudirac-C/learning-investment-strategies.git /opt/qing-agent
cd /opt/qing-agent

# 2. 创建 .env
cat > .env <<EOF
KIMI_API_KEY=sk-xxx
NEO4J_PASSWORD=your-neo4j-password
EOF

# 3. 启动基础设施（Neo4j + Qdrant + PostgreSQL + Mem0）
docker compose -f docker-compose.infra.yml up -d

# 4. 安装 Python 依赖
uv pip install -e ".[agent]"

# 5. 数据迁移（首次）
uv run python scripts/migrate_claims_to_neo4j.py
uv run python scripts/index_documents_to_qdrant.py
uv run python scripts/init_mem0_memories.py

# 6. 启动 qing-agent（生产环境用 systemd 或 supervisord）
uv run uvicorn qing_investment.agent.main:app --host 0.0.0.0 --port 8000

# 7. 验证
 curl http://localhost:8000/health
```

### 5.3 使用 systemd 托管 qing-agent

创建 `/etc/systemd/system/qing-agent.service`：
```ini
[Unit]
Description=Qing Agent Sub-Agent Service
After=network.target

[Service]
Type=simple
User=qing
WorkingDirectory=/opt/qing-agent
ExecStart=/opt/qing-agent/.venv/bin/uvicorn qing_investment.agent.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
Environment=KIMI_API_KEY=sk-xxx
Environment=NEO4J_PASSWORD=xxx

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable qing-agent
sudo systemctl start qing-agent
```

### 5.4 增量更新 cron

云端服务器配置：
```bash
# 每小时拉取最新代码并增量索引
0 * * * * cd /opt/qing-agent && git pull origin master && uv run python scripts/delta_index.py
```

---

## 6. Hermes Cron 改造

修改 `install-cloud-crons.sh`，新增 `QING_AGENT_URL` 环境变量：

```bash
# 在 install-cloud-crons.sh 顶部添加
: "${QING_AGENT_URL:?Set QING_AGENT_URL, e.g. http://localhost:8000}"

# Hermes 环境变量
export QING_AGENT_URL="${QING_AGENT_URL}"
```

然后在 Hermes 的 cron job 中，qing_stock_monitor_agent.py 会读取这个变量：

```bash
hermes cron create "26 9 * * 1-5" "$AGENT_PROMPT" \
  --name "A股大模型分析-集合竞价后" \
  --workdir "$HERMES_REPO_ROOT" \
  --script qing_stock_monitor_agent.py \
  --env QING_AGENT_URL="$QING_AGENT_URL" \
  --deliver "$HERMES_DELIVER_TARGET"
```

**注意**：`$AGENT_PROMPT` 现在可以**升级**了：
- 改造前："根据脚本上下文输出极简微信提醒..."
- 改造后：qing-agent 已经负责生成 UP 风格文本，Hermes 的 prompt 可以简化为：
  ```
  直接输出脚本返回的内容，不要修改格式。如果脚本返回了 JSON，提取 final_output 字段。
  ```
  或者直接 `--no-agent`（让 Hermes 不调用大模型，完全信任 qing-agent 的输出）。

---

## 7. 安全考虑

### 7.1 网络隔离

qing-agent 不需要暴露到公网：
- **最佳**：Hermes 和 qing-agent 部署在同一台云服务器，通过 `localhost:8000` 通信
- **次佳**：部署在同一 VPC 内，通过内网 IP 通信
- **避免**：把 qing-agent 的 8000 端口直接暴露在公网

### 7.2 API 认证

如果必须跨网络通信，给 qing-agent 加简单认证：

```python
from fastapi import Security, HTTPException
from fastapi.security import APIKeyHeader

api_key_header = APIKeyHeader(name="X-API-Key")

@app.post("/analyze/trigger")
async def analyze_trigger(
    req: TriggerRequest,
    api_key: str = Security(api_key_header),
):
    if api_key != settings.api_key:
        raise HTTPException(status_code=403, detail="Invalid API Key")
    ...
```

Hermes 调用时带 header：
```python
req.add_header("X-API-Key", os.environ["QING_AGENT_API_KEY"])
```

### 7.3 敏感数据

- `positions.yaml` 永远**不**上传到云端，通过 HTTP body 实时传入
- `.env` 文件设置 600 权限：`chmod 600 .env`
- Kimi API Key 只保存在云端服务器，本地开发机不需要

---

## 8. 成本估算（云端）

| 项目 | 估算 | 说明 |
|------|------|------|
| 云服务器（2C4G） | ~¥50-100/月 | 轻量应用服务器或 ECS |
| Kimi API（推理） | ~¥50-100/月 | 每天7次固定分析 + 触发分析 |
| Kimi API（索引） | ~¥30-50（一次性） | 初始实体抽取和向量化 |
| **总计** | **~¥100-200/月** | 含服务器 + API |

对比改造前：
- 改造前：Hermes 直接调用 Kimi API ~¥20-40/月（无服务器成本）
- 改造后：多了服务器成本，但分析质量大幅提升

---

## 9. 回退策略

如果 qing-agent 故障，Hermes 需要能无缝回退到原有模式：

在 `hermes_stock_monitor_agent.py` 中：
```python
try:
    result = call_qing_agent(context_json)
    print(result["final_output"])
except Exception as e:
    # Fallback：输出原始上下文，让 Hermes 用原有 prompt 调用大模型
    print(context_text)
    print(f"\n[qing-agent fallback, raw context above]")
```

这样即使 qing-agent 宕机，微信提醒不会断，只是回到原有简单分析模式。

---

## 10. 总结

| 维度 | 改造前 | 改造后 |
|------|--------|--------|
| **分析深度** | 350字极简提醒，无状态 | 带引用、证据表、观点演化的深度分析 |
| **知识检索** | 无 | Neo4j 知识图谱 + Qdrant 语义检索 |
| **长期记忆** | 无 | Mem0 跨会话记忆 |
| **事实核查** | 无 | Reviewer Agent 自动核查 |
| **Hermes 角色** | 调度 + 直接调用大模型 | 纯调度 + 消息路由 |
| **qing-agent 角色** | 无 | 深度分析子 Agent |
| **额外成本** | 无 | ~¥100/月 云服务器 |

**下一步**：你确认这个架构后，我可以开始：
1. 写改造后的 `hermes_stock_monitor_agent.py`
2. 写 `stock_monitor.py` 的 `--agent-json-context` 参数
3. 写云端 `docker-compose.infra.yml`
4. 写 qing-agent 的 `/analyze/trigger` 接口
