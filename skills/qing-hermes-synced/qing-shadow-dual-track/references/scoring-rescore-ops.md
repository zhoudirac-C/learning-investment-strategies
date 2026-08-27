# 评分重评与归因运维（2026-08-27 会话实录）

适用：历史预测的 due_scores 失明重评 + 归因补跑。均为会话级细节，SKILL.md 只留要点。

## 一、判断哪些日子需要补

归因只对「判错日」存在，不是每天都有。核对顺序：

1. **stage_miss**：预测文件 `stage_hit` vs `load_truth()` 真值（早盘 -pre 和晚盘都要查）
2. **direction_miss**：`status=scored` 且 `due_scores.direction_details` 平均超额 ≤0
   （`investment_engine.shadow.daily._direction_missed` 同口径）
3. 与 `evals/shadow/attributions/` 目录比对缺失

注意 `direction_details=[]` 且 `directions.samples=0` 的 scored 日 = 评分失明日，
不是「方向判对」，需重评后才能下 direction_miss 结论。

## 二、评分重评流程（samples=0 应急）

```python
import sys, json
sys.path.insert(0,"src"); sys.path.insert(0,".")
from investment_engine.blindtest.score import _forward, stock_scores

# 1) 成分映射：中文名方向无映射时，取盲判自选 stocks（directions[].stocks 字段）
# 2) 口径与 direction_scores 完全一致：5 日相对沪深300 超额，等权，>1e-9 为 hit
day = "2026-08-19"
bench = _forward("infra/data/kline_cache.db", "IDX000300", day, 5)
rets = [v for v in (_forward("infra/data/kline_cache.db", c, day, 5) for c in members) if v is not None]
dir_ret = sum(rets)/len(rets); hit = (dir_ret - bench) > 1e-9

# 3) 回填 due_scores：directions 统计 + direction_details 明细
#    必附 _rescore_note 说明：成分=盲判自选个股（n=1~2），非板块全样本，偏乐观
# 4) stocks 字段用 stock_scores() 同步重算（原 samples=0 的原因相同）
# 5) 回填后跑 _direction_missed(rec) 判定是否补归因；write_status() 刷新报告
```

实测结果（2026-08-27）：8-19 银行+1.55%/煤炭+0.29% hit；8-20 医药+22.7%/通信设备+21.9% hit
（康希诺单股 +44% 拉高均值——即 n 小的失真实例）。两天均未 direction_miss，无新增归因。

## 三、手动补归因

```bash
cd ~/learning-investment-strategies
set -a; source .env; set +a   # SENSENOVA_API_KEY 必须，否则 call_deepseek 直接 RuntimeError
.venv/bin/python /tmp/backfill_attr.py   # 脚本写 /tmp，repo 根执行（ATTR_DIR 相对路径）
```

- LLM 调用 ~15s/日（thinking off）；sensenova 偶发 429 靠内置重试自愈
- `trigger="stage_miss_premarket"` 用 `track: "premarket"` 的 score_info
- 生成的提案自动落 `framework/proposals/{day}-{type}-{slug}.md`（status: open）
- 提交只 add：attributions/*.json + proposals/*.md + logs/shadow-status.md

## 四、K 线停更（2026-08-27 已修，防复发机制在场）

- **根因（勿再当未知问题排查）**：`fetch_tdx_sector_klines.py` 断点续拉阈值曾硬编码
  `"2026-08-01"`（注释写"最近10天"但实现非动态），8 月过后 4582 只 8-13 停更的
  成分股被永久误判"已最新"→ 每次跑都跳过。已改动态 `今天-10天`（commit a5c3120，
  tests/test_fetch_tdx_sector_klines.py 7 用例含回归 `test_stale_data_not_skipped`）。
- **同 commit 修复的 --only bug**：①全部已最新（0 待拉）时返回 0 而非 1（幂等语义）；
  ②`os._exit` 前 flush stdout/stderr（管道/cron 场景输出不再全空）。`main(argv)` 支持
  `--sector-json/--db` 覆盖路径供测试。
- **防复发**：cron `TDX板块成分股K线增量补齐`（job `49cdd3277d44`，工作日 21:00，
  wrapper `~/.hermes/scripts/qing_fetch_tdx_sector_klines.py`，subprocess timeout 5400s 兜底）。
- 诊断口诀：评分 samples=0 时先查 K 线新鲜度再查映射——
  `SELECT code, MAX(trade_date) FROM stocks_kline WHERE code IN (...)`
- 手动补单只（快、稳，兜底路径）：
  ```python
  from qing_investment.tdx_market import TdxMarket
  from qing_investment.kline_cache import save_klines, init_db
  init_db(db_path=Path("infra/data/kline_cache.db"))
  m = TdxMarket()
  kl = m.get_kline(code, category="daily", count=90)   # 内置 3 次重试也可自己包
  save_klines(code, kl, db_path=Path("infra/data/kline_cache.db"))
  ```
  7 只 ~10s；601088 这类全新 code 也能拉

## 五、test_daily.py 测试模式（TDD 参照）

`_run(monkeypatch, **overrides)` helper 全 mock：fake_predict 同时写 `{day}.json` 和
`{day}-pre.json`，`fake_attr` 记录调用到 `r["_attr_calls"]` 供断言 trigger/day/pred。
新增用例参照 `test_premarket_stage_miss_triggers_attribution`。

## 六、方向成分映射治本方案（2026-08-27 调研完毕，用户认可方向，待实施）

用户提出「直接查股票名所属板块」——实测四条数据源，结论如下：

| 数据源 | 可用性 | 粒度 | 结论 |
|--------|--------|------|------|
| **新浪行业分类**（`stock_sector_mapper.py` 已接入，缓存 `stock_sector_mapping.json` 每日 cron 自动刷新） | ✅ | 证监会行业名（中文）84 个 | **首选**：3313 条行业映射已在缓存，零新增依赖 |
| TDX `get_finance_info().industry` | ✅ | TDX 行业码（数字，需码表） | 全市场 144ms/只≈13 分钟；码表要自己维护，无 cron 链路 |
| 腾讯 qt.gtimg.cn | ✅ 但无行业字段 | — | 排除 |
| 东财 push2/F10 | ❌ 断连/400 | — | 排除（与既有反爬结论一致） |

**方案设计**（未实施）：`blindtest/score.py::_direction_members` 加第三级回退——
`中文名方向 → 同义词映射 yaml → stock_sector_mapping.json 反查行业成分股`。
同义词表（人工维护 ~20 行）：`银行→货币金融服务`、`煤炭→煤炭开采和洗选业`、
`医药→医药制造业`、`通信设备→计算机、通信和其他电子设备制造业`。

**权衡要点**：证监会二级行业比 TDX 概念粗（通信设备并入计算机通信电子 100 只），
方向评算是均值超额，粗粒度只稀释信号不系统性偏移；缓存行业覆盖 3313 条 vs 概念
8090 条，边缘股缺标签可接受。实测样本：货币金融服务 44 只（601998/601988/600036…）、
煤炭开采和洗选业 25 只、医药制造业 100 只。

其余遗留：

1. prompt 约束 direction_id 到映射集合（与上面回退方案二选一或并用——回退方案更稳，不依赖 LLM 遵守）
2. test_qing_review pre-existing 失败：daily_review_summary.json 17:10 cron 刷新出
   STAGE_MAP 未映射新标签（缩量冰点/等右侧确认、退潮期（调整期）、弱修复/磨底）

已解决（2026-08-27 从遗留移除）：§四 K 线停更（硬编码阈值 + --only bug 已修，
cron 49cdd3277d44 防复发）；原遗留 3（--only bug）随 a5c3120 落地。

## 七、direction_miss 重评后注意事项

- 重评回填 due_scores 后，`_direction_missed` 用同一 `direction_details` 口径判定；
  重评结果改变 direction_miss 结论时**无需**追溯补归因（归因文件以 stage_miss 为主时，
  direction_miss 只影响新增缺归因日的判断）。
- 成分 n=1~2 的方向评分仅供参考（康希诺单股 +44% 拉高 8-20 医药均值即为实例），
  `_rescore_note` 必须带上口径声明。
