#!/bin/bash
# Use timeout to prevent hanging indefinitely
timeout 80 curl -s -X POST http://localhost:8000/analyze/trigger \
  -H 'Content-Type: application/json' \
  -d '{
    "timestamp": "2026-06-16T09:20:00+08:00",
    "user_query": "今天(6/16)分歧日，优先买哪些？仓位怎么操作？手上有159381 ETF",
    "context": {
      "market_framework": {
        "current_stage": "缩量修复待验证。6/16分歧日看承接去弱留强。UP早盘提示突破下降趋势线短期看多做多",
        "opening_scenarios": {
          "scenario_A_放量续强": "量能维持3万亿+，结构性转全面行情",
          "scenario_B_缩量震荡": "量能回落至2.5-3万亿，持有不动"
        }
      },
      "positions": {
        "accounts": [{
          "name": "主账户",
          "positions": [{"code": "159381", "name": "创业板AIETF", "cost": 1.344, "quantity": 8800}]
        }]
      }
    }
  }'
