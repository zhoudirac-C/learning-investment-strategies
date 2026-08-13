#!/usr/bin/env bash
# 等待 K 线落库任务完成后，删除旧早盘盲判产物并重跑。
# 用法：后台运行，完成后自动通知。
set -euo pipefail
cd /home/ubuntu/learning-investment-strategies

KLINE_PID=2960148
TARGET_DAY="2026-08-13"
PRE_JSON="evals/shadow/predictions/${TARGET_DAY}-pre.json"

echo "[watcher] 等待 K 线任务 PID=${KLINE_PID} 结束..."

# 轮询进程是否还在（最多等 6 小时）
for i in $(seq 1 720); do
    if ! kill -0 "${KLINE_PID}" 2>/dev/null; then
        echo "[watcher] K 线任务已结束"
        break
    fi
    sleep 30
done

echo "[watcher] K 线落库结果："
tail -5 /tmp/tdx_klines2.log

echo "[watcher] 当前库内股票数："
.venv/bin/python -c "import sqlite3; c=sqlite3.connect('infra/data/kline_cache.db'); print('  ', c.execute('SELECT COUNT(DISTINCT code) FROM stocks_kline').fetchone()[0], '只')"

# 删除旧产物（幂等保护会跳过 pending_maturity，需先删）
if [ -f "${PRE_JSON}" ]; then
    echo "[watcher] 删除旧产物 ${PRE_JSON}"
    rm -f "${PRE_JSON}"
fi

echo "[watcher] 重跑早盘盲判 ${TARGET_DAY} ..."
set -a && source .env && set +a
.venv/bin/python scripts/shadow_premarket.py --date "${TARGET_DAY}" 2>&1 | tail -20

echo "[watcher] 完成。产物："
.venv/bin/python -c "import json; d=json.load(open('${PRE_JSON}')); print('  status:', d.get('status')); print('  prev_day:', d.get('meta',{}).get('prev_day')); print('  overnight_date:', d.get('meta',{}).get('overnight_date')); print('  directions:', len((d.get('result') or {}).get('directions', [])))"
