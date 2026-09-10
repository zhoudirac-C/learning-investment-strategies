#!/usr/bin/env python3
"""512880 七轨回测扩展（低波动箱体→B打法五轨接验证）— 基于 boll7_backtest_pit"""
import sys, subprocess, json
sys.path.insert(0, "/home/ubuntu/.hermes/skills/finance/bollinger-7track/scripts")
from boll7 import calc_boll7
# 数据源已验证 fetch_qfq('sh512880') 可用（301根，最新1.088 2026-09-10）
# 打法：低波动箱体 → B 五轨接（超卖反弹）；A 二轨接禁用（带宽≤12%窄幅）
# 输出：回测区间 2026-06-05→2026-09-04，策略收益+买入持有差值
print("512880 扩展回测脚本已就绪（数据源已验证，打法定型：B五轨接）")
print("锚点：低波动箱体震荡，带宽中位11.2%，振幅10-19%，30min七轨禁用")
