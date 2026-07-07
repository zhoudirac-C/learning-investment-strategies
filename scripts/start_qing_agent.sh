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

# 加载 .env
echo "Starting Qing-Agent..."
set -a
source .env
set +a

# 默认所有 Qing-Agent LLM 调用优先走本地 Kimi Code ACP（kimi acp）。
# ACP 通过 stdio JSON-RPC 与 Kimi Code 通信，每次请求新建 session，避免 kimi -p 的 argv 长度限制。
# 强制覆盖 .env 中的设置，确保切换生效；如需关闭可注释下面这行。
export KIMI_CODE_ACP_FIRST=1
# 大 context 下本地 ACP 可能耗时 5-10 分钟；给足单节点超时
export KIMI_CODE_ACP_TIMEOUT=600
# 看盘定时任务 wrapper 与 qing-agent HTTP 客户端超时对齐
# 大 context + reviewer 多轮 retry 实测可达 23 分钟，给足余量
export QING_AGENT_TIMEOUT=1800

nohup .venv/bin/python -m uvicorn qing_investment.agent.main:app \
    --host 127.0.0.1 --port 8000 \
    > /tmp/qing-agent.log 2>&1 &

echo "Qing-Agent started (PID $!)"
echo "Wait ~30s and check: curl http://127.0.0.1:8000/health"
