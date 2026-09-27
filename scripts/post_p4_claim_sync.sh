#!/usr/bin/env bash
# P4 redo-judge 完成后，自动补跑 claim 下游同步：discover → Neo4j → Qdrant → 关系回填提交。
# 设计为 cron no_agent 周期触发：P4 未完成或已完成过则静默退出。
set -euo pipefail

ROOT="/home/ubuntu/learning-investment-strategies"
cd "$ROOT"

# P4 仍在跑则静默退出（[s] 防止 pgrep 匹配到本脚本自身命令行）
if pgrep -f "[s]cripts/xueqiu_expert/verdict_pipeline.py" >/dev/null 2>&1; then
  exit 0
fi

# P4 rerun 未完成判定：没有 TOP20 输出或 verdicts 尚未落盘则静默退出
if ! grep -q "TOP20 →" logs/p4_verdict_rerun.log 2>/dev/null; then
  exit 0
fi
if [ "$(find data/xueqiu/verdicts -maxdepth 1 -name '[0-9]*.json' | wc -l)" -eq 0 ]; then
  exit 0
fi

MARKER="logs/.post_p4_claim_sync_done"
if [ -f "$MARKER" ]; then
  exit 0
fi

LOG="logs/post_p4_claim_sync.log"
{
  echo "[$(date '+%F %T')] P4 done detected, start claim downstream sync"

  # embedding 预检：发现 Fallback 先回 pin hub（ONNX 静默降级坑）
  if ! PYTHONPATH=src .venv/bin/python - <<'PY'
from qing_investment.agent.tools.llm_client import get_embedding_model
assert type(get_embedding_model()).__name__ == "OnnxEmbeddingModel"
PY
  then
    echo "[$(date '+%F %T')] embedding fallback detected, pin huggingface-hub==0.36.2"
    .venv/bin/pip install huggingface-hub==0.36.2
  fi

  # Qdrant 服务端检查
  if ! curl -sf localhost:6333/collections >/dev/null 2>&1; then
    echo "[$(date '+%F %T')] qdrant not ready, start server"
    nohup ./bin/qdrant > /tmp/qdrant.log 2>&1 &
    sleep 3
  fi
  curl -sf localhost:6333/collections >/dev/null

  echo "[$(date '+%F %T')] discover --all-missing"
  PYTHONPATH=src .venv/bin/python src/qing_investment/agent/tools/discover_claim_relations.py --all-missing

  echo "[$(date '+%F %T')] migrate claims to Neo4j"
  PYTHONPATH=src .venv/bin/python scripts/migrate_claims_to_neo4j.py

  echo "[$(date '+%F %T')] rebuild Qdrant claims index"
  PYTHONPATH=src .venv/bin/python scripts/index_claims_to_qdrant.py --force-recreate --skip-agent-kill

  if ! curl -sf http://127.0.0.1:8000/health >/dev/null 2>&1; then
    echo "[$(date '+%F %T')] agent health not ready, restart uvicorn"
    nohup env PYTHONPATH=src .venv/bin/python -m uvicorn qing_investment.agent.main:app \
      --host 127.0.0.1 --port 8000 --log-level info > logs/qing-agent-restart.log 2>&1 &
    sleep 3
  fi
  curl -sf http://127.0.0.1:8000/health >/dev/null

  git add knowledge/claims
  if ! git diff --cached --quiet; then
    git commit -m "claim: post-P4 discover 关系回填"
    git push origin master
    echo "[$(date '+%F %T')] relations committed and pushed"
  else
    echo "[$(date '+%F %T')] no claim relation diff to commit"
  fi

  touch "$MARKER"
  echo "[$(date '+%F %T')] DONE"
} >> "$LOG" 2>&1

cat "$LOG"
