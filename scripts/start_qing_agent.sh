#!/bin/bash
# 守护进程 — 健康检查通过时静默，离线时自动重启
# 由 cron 每 15 分钟调用（07df0a7909f4）

set -e

cd /home/ubuntu/learning-investment-strategies

# 如果已有运行中的 agent，跳过（不重复杀）
if pgrep -f 'uvicorn.*qing_investment' > /dev/null 2>&1; then
    echo "Qing-Agent already running, checking health..."
    HEALTH=$(curl -s http://127.0.0.1:8000/health 2>/dev/null || echo "down")
    if [ "$HEALTH" = '{"status":"ok","version":"0.1.0"}' ]; then
        echo "Health OK, nothing to do."
        exit 0
    fi
    echo "Agent running but health failed, will restart..."
    pkill -f 'uvicorn.*qing_investment' 2>/dev/null || true
    sleep 2
fi

# 加载 .env 并启动
echo "Starting Qing-Agent..."
set -a
source .env
set +a

nohup .venv/bin/python -m uvicorn qing_investment.agent.main:app \
    --host 127.0.0.1 --port 8000 \
    > /tmp/qing-agent.log 2>&1 &

echo "Qing-Agent started (PID $!)"
echo "Wait ~30s and check: curl http://127.0.0.1:8000/health"
