#!/bin/bash
curl -s -X POST http://localhost:8000/analyze/trigger \
  -H 'Content-Type: application/json' \
  -d '{
    "timestamp": "2026-06-16T09:20:00+08:00",
    "user_query": "今天(6/16)优先买哪些股票？仓位怎么操作？大盘突破下降趋势线短期看多做多，但今天分歧日开盘冲高先T出。我现在只有159381 ETF在手上",
    "context": {
      "market_framework": {
        "current_stage": "缩量修复待验证。6/15全A中阳+AI硬科技普涨，UP触发4088但强调缩量+聚焦度不足。6/16验证日：分歧日看承接去弱留强。UP早盘提示突破下降趋势线短期看多做多"
      },
      "positions": {
        "accounts": [{
          "name": "主账户",
          "positions": [{"code": "159381", "name": "创业板AI ETF", "cost": 1.344, "quantity": 8800}]
        }]
      },
      "watchlist": {}
    }
  }'
