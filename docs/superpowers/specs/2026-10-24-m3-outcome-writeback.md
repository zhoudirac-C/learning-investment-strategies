# M3 剩余：市场结果回写 + UP 命中率画像（设计）

date: 2026-10-24
status: approved（方案 C + outcome 块 + 5 日口径，用户已拍板）
related: [docs/tasks/m-series-status-and-usage.md（M3 剩余行）,
  scripts/evaluate_vs_market.py, src/investment_engine/claim_buckets.py]

## 背景

M3 基建（claim_buckets + evaluate_vs_market，2026-08-16）落地时 claims 库无
市场结果字段，命中率一律 insufficient_data。现影子数据已满 8 周、毕业判决
（10-10）not_yet，第三判据明确「待 M3 claims 分桶落地后定义」。本设计落地
回写机制 + UP 画像，让 evaluate_vs_market 出数。

## 已拍板决策

1. **方向来源**：LLM 批量判向（标注落 claim `direction` 字段，一次标注长期
   复用），forward 收益机械结算。抽 30 条人审判向质量。
2. **回写落点**：新增 `outcome` 块，**不动 confidence 原字段**。
3. **结算口径**：5 交易日 forward，|收益|≥1% 计 hit/miss，以下计
   neutral_window；market-regime→沪深300(sh000300)、stock-view→
   related_stocks 首标的；无法定价诚实标 insufficient_data。

## 数据现实（2026-10-24 盘点）

- 存量 6029 claims：stance 已填 1030（10 月起新 claim，旧 4999 条无）；
  related_stocks 非空 1798；kline 缓存 5384 股（2026-02-12 起）+ 11 指数
  日 K（sh000300 等，2026-01-05 起）——覆盖率远超 8 月文档记录（217 股）。
- 判向范围：stance ∈ {view, market-regime}，或 claim_type=stock-view 且
  related_stocks 非空（旧 stock-view 补判）。估 1100-1300 条。

## 新增 claim 字段

```yaml
direction:                     # LLM 判向（annotate 阶段写入）
  value: bullish|bearish|neutral
  basis_kind: stock|index
  basis_code: "600519.SH"      # 规范化带交易所后缀
  rationale: <30字>
  annotated_at: 2026-10-24
  annotator: m3-direction-v1
outcome:                       # 机械结算（settle 阶段写入/覆盖）
  evaluated_at: 2026-10-24
  window_days: 5
  basis_code: "sh000300"
  t0_date: "2026-10-17"        # 首个 >= source_date 交易日
  t5_date: "2026-10-24"
  t0_close: 4036.3
  t5_close: 4101.2
  fwd_return_pct: 1.61
  result: hit|miss|neutral_window|pending_data|insufficient_data
  reason: <缺数说明>
```

result 规则：basis 无 K 线 → insufficient_data；t5 不存在（source_date 距今
不足 5 交易日）→ pending_data；bullish 且 ret≥1% → hit，ret≤-1% → miss，
否则 neutral_window；bearish 对称。结算幂等，重跑覆盖 outcome 块。

## 管线

```
scripts/annotate_claim_direction.py  →  scripts/settle_claim_outcomes.py
  （LLM 判向，逐条落盘，--limit/--dry-run/--claim-id，断点续跑）   （机械结算+回写，
                                                                    逐条落盘）
        ↓
  scripts/build_up_hit_profile.py → logs/claims-vs-market-YYYYMMDD.md
  （UP × claim_type × 月聚合 hit_rate） + evaluate_vs_market.py 命中率列出数
```

LLM 通道：hermes_global（deepseek-v4-flash）+ openrouter 兜底，与 discover
同款 `get_llm_client_with_fallback`。

## 模块与文件

- `src/investment_engine/claim_direction.py` — 判向 prompt/parse/annotate_claim
- `src/investment_engine/claim_outcome.py` — kline 读取、结算、outcome 块回写
- `src/investment_engine/up_hit_profile.py` — 聚合 + markdown 渲染
- 脚本三件套（见管线）；`scripts/evaluate_vs_market.py` 命中率列出数
- 测试：`tests/investment_engine/test_claim_direction.py`、
  `test_claim_outcome.py`、`test_up_hit_profile.py`

## 边界与诚实原则

- 判向质量门槛：抽 30 条人工核对，错向 >10% 则停线调 prompt 重来。
- 旧 stance-None 的 4999 条不在本次判向范围（LLM 判 5000 条旧观点的方向
  既贵又偏离 M3 目标——画像聚焦当前活跃观点；旧 claim 保持
  insufficient_data）。
- neutral 不计入 hit_rate 分母；pending_data 到结算日后由 cron/手动重跑
  settle 自动转终态。
- 不碰 confidence；画像数据积累后再定 confidence 调整规则（后续任务）。

## 验收

1. 三个新测试文件全绿（hit 边界 ±1%、forward 计算、缺数分支、YAML 回写
   roundtrip、聚合口径）。
2. 判向跑完：scope 内 claim 全有 direction；30 条人审记录写入报告。
3. 结算跑完：outcome 块落盘；`logs/claims-vs-market-*.md` 出数；
   evaluate_vs_market --report 五桶命中率列出数（up 桶非 N/A）。
4. 全量 pytest 无新增失败。
