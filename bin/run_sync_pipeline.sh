#!/bin/bash
#  Qing 知识库同步管线
#  discover → Neo4j → Qdrant → 重启 Agent / Hermes gateway / MCP servers
#  用法：./bin/run_sync_pipeline.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

HERMES_VENV="/home/ubuntu/.hermes/hermes-agent/venv"
PYTHON3="$HERMES_VENV/bin/python3"
HERMES="$HERMES_VENV/bin/python -m hermes_cli.main"

echo "=== Step 0: 停止 Qing-Agent + Hermes gateway + MCP servers ==="
# 停 Qing-Agent（释放 Qdrant 锁）
pkill -f "uvicorn.*qing_investment" 2>/dev/null || true
for i in 1 2 3; do
  if pgrep -f "gunicorn.*qing_investment" >/dev/null 2>&1; then
    pkill -f "gunicorn.*qing_investment" 2>/dev/null || true
    sleep 1
  fi
done
pgrep -f "gunicorn.*qing_investment" >/dev/null 2>&1 && pkill -9 -f "gunicorn.*qing_investment" 2>/dev/null || true

# 停 Hermes gateway（会顺带关闭其管理的 MCP server 子进程）
pkill -f "hermes_cli.main gateway" 2>/dev/null || true
sleep 2

# 兜底：直接清掉残留的 MCP server
pkill -f "mcp_qdrant_server.py" 2>/dev/null || true
pkill -f "mcp_neo4j_server.py" 2>/dev/null || true
sleep 2

echo "Agent / gateway / MCP processes cleared"

echo "=== Step 1: 关系发现 discover_claim_relations.py --all-missing ==="
PYTHONPATH=src .venv/bin/python src/qing_investment/agent/tools/discover_claim_relations.py --all-missing

echo "=== Step 2: Neo4j 同步 migrate_claims_to_neo4j.py ==="
PYTHONPATH=src .venv/bin/python scripts/migrate_claims_to_neo4j.py

echo "=== Step 3: Qdrant 重建 index_claims_to_qdrant.py --force-recreate ==="
PYTHONPATH=src .venv/bin/python scripts/index_claims_to_qdrant.py --force-recreate

echo "=== Step 4: 重启 Qing-Agent ==="
PYTHONPATH=src nohup .venv/bin/python -m uvicorn qing_investment.agent.main:app --host 127.0.0.1 --port 8000 --log-level info > agent.log 2>&1 &
sleep 5

echo "=== Step 5: 验证 Agent health ==="
curl -s http://localhost:8000/health || echo "Health check failed"

echo "=== Step 6: 重启 Hermes gateway（连带重启 Kimi Code CLI / Hermes Agent 的 MCP）==="
nohup "$PYTHON3" -m hermes_cli.main gateway run --replace > /tmp/hermes_gateway.log 2>&1 &
sleep 5

# 等待 gateway 起来
for i in {1..12}; do
  if pgrep -f "hermes_cli.main gateway" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo "=== Step 7: 验证 MCP 连接 ==="
hermes mcp test qdrant 2>&1 | tail -5
hermes mcp test neo4j 2>&1 | tail -5

echo "=== 同步管线完成 ==="
