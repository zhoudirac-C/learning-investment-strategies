# 盲判提案批量裁决（簇 D/E/F）任务记录

date: 2026-10-24
status: completed（当日收尾并提交）
related: [framework/proposals/2026-10-24-direction-adjudication.md,
  framework/proposals/2026-10-24-macro-shock-adjudication.md,
  framework/proposals/2026-10-24-panic-adjust-adjudication.md]

## 任务概述

2026-10-24 12:29 重新生成的 `logs/shadow-status.md` 显示盲判双轨积压
105 份 open 提案（本批处置 89 份），按错因收敛分三簇合并裁决，逐簇落地
prompt 规则 + 机械校验 + 回归验证。本文档记录跨会话进度，防 ACP 超时
丢失上下文。

## 中断史（重要）

- 会话 1（簇 F 编码+测试阶段）：客户端报 `ACP request timeout: session/prompt`
  死亡，留下孤儿进程。
- 会话 2（`session_9906dc22`）：杀死孤儿、完成簇 F 大部分工作，15:02 前后
  再次 ACP 超时死亡。其 todo 与产出可从 wire 日志恢复：
  `~/.kimi-code/sessions/wd_learning-investment-strategies_4366e2e4f8b8/session_9906dc22-*/agents/main/wire.jsonl`
- 会话 3（当前）：收尾。规则47 回扫、v24 回归缺口补齐、文档回填、提交。

## 三簇状态

| 簇 | 范围 | 裁决文档 | prompt | 状态 |
|---|---|---|---|---|
| D 方向簇 | 19 份（08-14~10-14） | direction-adjudication.md | v22（规则23/36 增补+43/44/45，盘前 39-41） | applied，回归完成 |
| E 宏观/外部冲击簇 | 16 份（08-17~10-16） | macro-shock-adjudication.md | v23（规则40 增补+46，盘前 42） | applied，回归完成 |
| F 恐慌判别簇 | 4 份（10-15/16/16/22） | panic-adjust-adjudication.md | v24（规则47，盘前 43；glossary 两词条；sentiment_cycle step2 二分条款） | 收尾中 |

簇 F 四提案处置：10-15-glossary=applied、10-16-glossary=pending（量化阈值
单日反推挂起，重启条件见裁决文档「暂缓项」节）、10-16-pattern=merged、
10-22-pattern=applied。frontmatter 均已回写。

## 已完成（本会话，截至 17:45）

- ACP/孤儿状态确认：无遗留进程；`p3_waf_probe.log` 为无关定时任务
- `logs/shadow-status.md` 再生成：open 105→50，已解决 90（applied 26 /
  merged 26 / implemented 35 / done 3），pending 16；预测记录 136 天未变
- 仓库根 `xaa` 残留（"NOMATCH"）已删

## 后台任务（会话 3 启动）

| 任务 | 命令 | 产出 |
|---|---|---|
| 规则47 历史回扫 | `.venv/bin/python /tmp/rule47_rescan.py`（不限时，增量落盘） | `/tmp/rule47_rescan_result.json`；预期复现文档结论：盘后+盘前各记录回扫，规则47 命中恰 5 条（10-15、10-15-pre、10-16、10-16-pre、10-22-pre），无误伤 |
| v24 回归第三轮 | `SHADOW_DISABLE_HERMES=1 .venv/bin/python /tmp/v24_regression3.py` | `/tmp/v24-regression3/summary.jsonl` 增量；补 10-22（二轮 429 error）+ 对照日 10-19/10-21（二轮漏跑） |
| 全量 pytest | `.venv/bin/python -m pytest tests/ -q --ignore=tests/chan_engine/test_adapter_czsc.py` | 注意：`test_adapter_czsc.py` 缺 `czsc` 包是 7 月遗留环境问题，全量收集必卡，须 `--ignore` |

回归第二轮（`/tmp/v24-regression2/summary.jsonl`，15:11 完成）：
10-15 ✓passed；10-14 命中但 validation failed（规则42）；**10-16 仍违反
规则47**（r20=-8.31% 判「调整」，机械校验拦截）；10-22=429 error。

回归第三轮（`/tmp/v24-regression3/`，本会话）：10-22 ✓passed（恐慌，
r20=-9.91%）；10-19 ✓passed；10-21 首跑 429、等限流窗口复跑 ✓passed
（stage_reason 显式计算 r20=-7.60% 未升级）。**6 日全表已回填裁决文档**
`__REGRESSION_RESULTS__` 节：错判日 2/3 收敛（10-15/10-22），10-16 为
模型层残余（机械校验拦下）；对照日 3/3 零误升。

## 剩余步骤（全部完成，2026-10-24 收尾）

1. ✅ 规则47 回扫复验：独立重跑命中恰 5 条（10-15、10-15-pre、10-16、
   10-16-pre、10-22-pre），0 重建失败，与裁决文档结论一致
2. ✅ `panic-adjust-adjudication.md` 的 `__REGRESSION_RESULTS__` 已回填
   （6 日全表：错判日 2/3 收敛，10-16 残余由机械校验拦下；对照日 3/3
   零误升）
3. ✅ 全量 pytest 1997 过（`--ignore=tests/chan_engine/test_adapter_czsc.py`，
   缺 czsc 系 7 月遗留）；3 个失败均为预存问题：bilibili ASR 长视频阈值
   测试未同步（10-23 d037a2af）、qing_review 真实标签漂移
   （daily_review_summary.json 两个新标签未映射）、test_buy_signal_e2e
   顺序依赖（单独运行通过）
4. ✅ 已提交（全部 67 修改 + 5 新文件）
5. 已知挂起项（非欠账）：10-16-glossary 阈值待 ≥1 个独立样本重启

## 关键路径索引

- prompt+机械校验：`src/investment_engine/blindtest/replay.py`（v24、
  validate_result 规则47 在 1233 行附近）
- 盘前轨：`src/investment_engine/shadow/premarket.py`（规则43）
- 回归 harness：`scripts/_v24_regression.py`（一轮）；二/三轮脚本在
  `/tmp/v24_regression3.py`（临时）
- LLM 通道：回归用 `SHADOW_DISABLE_HERMES=1` 走 .env sensenova 通道
