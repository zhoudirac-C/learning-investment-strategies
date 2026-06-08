#!/usr/bin/env bash
# Wrapper for discover_claim_relations.py with:
# - Progress logging every 10 minutes
# - Error/interrupt capture with reason
# - Output to timestamped log file
# See: references/claim-relations-discovery.md and docs/neo4j-relation-pipeline.md
set -euo pipefail

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_DIR="/home/ubuntu/learning-investment-strategies/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/discover_relations_${TIMESTAMP}.log"
PROGRESS_FILE="$LOG_DIR/discover_relations_${TIMESTAMP}.progress"

echo "========================================" | tee "$LOG_FILE"
echo "Start: $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG_FILE"
echo "Command: discover_claim_relations.py --all-missing" | tee -a "$LOG_FILE"
echo "Log: $LOG_FILE" | tee -a "$LOG_FILE"
echo "========================================" | tee -a "$LOG_FILE"

cleanup() {
    local exit_code=$?
    echo "" | tee -a "$LOG_FILE"
    echo "========================================" | tee -a "$LOG_FILE"
    echo "END: $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG_FILE"
    echo "Exit code: $exit_code" | tee -a "$LOG_FILE"
    case $exit_code in
        0)   REASON="正常完成" ;;
        130) REASON="SIGINT (Ctrl+C 或进程被中断)" ;;
        137) REASON="SIGKILL (OOM Killer 或强制杀掉)" ;;
        143) REASON="SIGTERM (正常终止信号)" ;;
        *)   REASON="未知错误 (exit=$exit_code)" ;;
    esac
    echo "中断原因: $REASON" | tee -a "$LOG_FILE"
    echo "========================================" | tee -a "$LOG_FILE"
}
trap cleanup EXIT

progress_reporter() {
    local log="$1"
    local prog="$2"
    while true; do
        sleep 600
        if ! kill -0 $$ 2>/dev/null; then
            exit 0
        fi
        local last_line
        last_line=$(grep -E '^\[[0-9]+/[0-9]+\]' "$log" 2>/dev/null | tail -1 || echo "尚未开始处理")
        echo "[$(date '+%H:%M:%S')] 📊 进度: $last_line" >> "$prog"
        echo "[$(date '+%H:%M:%S')] 📊 进度: $last_line" >&2
    done
}

progress_reporter "$LOG_FILE" "$PROGRESS_FILE" &
REPORTER_PID=$!

cd /home/ubuntu/learning-investment-strategies
PYTHONPATH=src .venv/bin/python src/qing_investment/agent/tools/discover_claim_relations.py --all-missing 2>&1 | tee -a "$LOG_FILE"

kill $REPORTER_PID 2>/dev/null || true
wait $REPORTER_PID 2>/dev/null || true
