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

echo "=== Step 0: 服务预检（Qdrant 服务端模式，不停服）==="
# 2026-09-16 重构：Qdrant 自 2026-06-16 起为「仅服务端模式」（./bin/qdrant, port 6333, RocksDB）。
# 服务端支持多 Client 并发，--force-recreate 在服务端内部完成，无需独占锁。
# 因此原「停 Agent + gateway + MCP」逻辑已全部移除——它不仅多余，且会在盘中打断监控链路
# （pkill gateway 会杀死正在执行任务的 Hermes 主进程本身）。

QDRANT_OK=0; AGENT_OK=0; NEO4J_OK=0
curl -sf --max-time 5 http://localhost:6333/collections >/dev/null 2>&1 && QDRANT_OK=1
curl -sf --max-time 5 http://localhost:8000/health    >/dev/null 2>&1 && AGENT_OK=1
curl -sf --max-time 5 http://localhost:7474           >/dev/null 2>&1 && NEO4J_OK=1

echo "  Qdrant(6333): $([ $QDRANT_OK = 1 ] && echo OK || echo DOWN)"
echo "  Agent(8000) : $([ $AGENT_OK  = 1 ] && echo OK || echo DOWN)"
echo "  Neo4j(7474) : $([ $NEO4J_OK  = 1 ] && echo OK || echo DOWN)"

if [ $QDRANT_OK = 0 ]; then
  echo "  ⚠️  Qdrant 服务端未运行，尝试拉起..."
  nohup ./bin/qdrant > /tmp/qdrant.log 2>&1 &
  for i in {1..15}; do
    curl -sf --max-time 3 http://localhost:6333/collections >/dev/null 2>&1 && { echo "  ✅ Qdrant 已就绪"; QDRANT_OK=1; break; }
    sleep 1
  done
  [ $QDRANT_OK = 0 ] && { echo "  ❌ Qdrant 启动失败，见 /tmp/qdrant.log"; exit 1; }
fi

if [ $NEO4J_OK = 0 ]; then
  echo "  ❌ Neo4j 未运行（迁移步骤需要它）。请先启动 Neo4j 再重试。" >&2
  exit 1
fi

echo "=== Step 1: 关系发现 discover_claim_relations.py --all-missing ==="
PYTHONPATH=src .venv/bin/python src/qing_investment/agent/tools/discover_claim_relations.py --all-missing

echo "=== Step 2: Neo4j 同步 migrate_claims_to_neo4j.py ==="
PYTHONPATH=src .venv/bin/python scripts/migrate_claims_to_neo4j.py

echo "=== Step 3: Qdrant 重建 index_claims_to_qdrant.py --force-recreate ==="
PYTHONPATH=src .venv/bin/python scripts/index_claims_to_qdrant.py --force-recreate

echo "=== Step 4: 验证 Agent（仅当不在线才拉起）==="
# 2026-09-16 重构：不再无条件 kill + 重启 Agent，也不再重启 Hermes gateway。
# gateway 重启会连带杀掉作为其子进程的 Agent，且会杀死正在执行任务的 Hermes 主进程本身。
if curl -sf --max-time 5 http://localhost:8000/health >/dev/null 2>&1; then
  echo "  Agent 已在线，无需重启。"
else
  echo "  Agent 不在线，拉起中..."
  PYTHONPATH=src nohup .venv/bin/python -m uvicorn qing_investment.agent.main:app \
    --host 127.0.0.1 --port 8000 --log-level info > /tmp/qing-agent.log 2>&1 &
  for i in {1..20}; do
    curl -sf --max-time 3 http://localhost:8000/health >/dev/null 2>&1 && break
    sleep 1
  done
fi

echo "=== Step 5: 三件套终验 ==="
for pair in "Qdrant:http://localhost:6333/collections" "Agent:http://localhost:8000/health" "Neo4j:http://localhost:7474"; do
  name="${pair%%:*}"; url="${pair#*:}"
  if curl -sf --max-time 5 "$url" >/dev/null 2>&1; then
    echo "  ✅ $name OK"
  else
    echo "  ❌ $name DOWN"
  fi
done

echo "=== 同步管线完成 ==="
echo "提示：如需重启 Hermes gateway（Kimi Code CLI 侧 MCP 句柄失效时），"
echo "      gateway 会连带杀掉 Agent，重启后必须重新拉起并验证 Agent health。"
