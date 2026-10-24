# M3 回写实施计划（2026-10-24）

设计：docs/superpowers/specs/2026-10-24-m3-outcome-writeback.md

## 执行状态（2026-10-24 21:00 更新：全部完成）

- ✅ 任务 1-4：三模块 + 26/11/5 测试全绿（commit `9801a3af` +  Writer 修复）
- ✅ 任务 5-6：脚本三件套 + evaluate_vs_market 出数
- ✅ 任务 7 判向：1499 条全量判向（两轮：926+573，中断于非常规 YAML 块定位，
  已修复并加回归测试）；settle 689 条（hit 221 / miss 299 / neutral 36 /
  insufficient 23 / pending 109）
- ✅ 验收-1/2：测试全绿；判向覆盖 1499/1499
- ✅ 验收-3：画像 logs/claims-vs-market-2026-10-24.md（青枫浦上Q 40.6%）+
  evaluate_vs_market --report（up 桶 42.1% n=518 首出数）
- ✅ 验收-4：30 条判向人审——明确错向 1/30（3.3%，<10% 门槛通过）；
  系统性偏差记录：利好叙事型陈述被标 bullish（稀释方向纯度，画像解读时
  注意；v2 可考虑 assertion/narrative 分标）
- 🐛 事故与修复（已 TDD 固化）：① write_block_to_yaml 未引号化字符串，
   `reason: |x%|` 被解析为块标量炸 30 文件 → 字符串统一 JSON 双引号；
   ② 字典格式（无 claims 列表）+ 顶层列表值时块尾误判定 → 方向块插进
   related_stocks → 字典格式块 = 至 EOF；修复后全库 safe_load 校验
   bad=0 / claims=6029
- ⏳ 后续：109 条 pending_data 于窗口到点后重跑
  `settle_claim_outcomes.py` 自动转终态；confidence 调整规则待画像积累

## 任务清单（TDD：每任务先红后绿）

1. **claim_outcome 核心**（`src/investment_engine/claim_outcome.py`）
   - T：test_claim_outcome.py — 合成 sqlite kline（sh000300 日线 10 根 +
     000001.SZ 10 根），覆盖：t0/t5 定位、fwd 计算、hit/miss/neutral 边界
     （±0.9%/±1.0%/±1.1%）、pending_data（t5 缺失）、insufficient_data
     （无 basis）、股票代码规范化（600xxx→.SH/000xxx→.SZ/已有后缀原样）
   - C：`load_series(db_path, code)`、`settle_claim(claim, db_path)`、
     `HIT_THRESHOLD = 1.0`、`WINDOW_DAYS = 5`

2. **outcome 块回写**（同模块）
   - T：YAML roundtrip — dict 格式/claims 列表格式/缺 confidence 行，回写后
     yaml.safe_load 可解析、原字段无损、二次回写覆盖不残留旧键
   - C：`write_outcome_to_yaml(path, claim_id, outcome)`（仿
     discover write_results_to_yaml 的块定位+缩进保留）

3. **claim_direction 判向**（`src/investment_engine/claim_direction.py`）
   - T：test_claim_direction.py — prompt 含 statement/source_date/
     related_stocks；parse 容错（```fence、越界 value 降级 neutral、缺键）、
     股票代码规范化进 basis_code、annotate_claim 写回字段结构
   - C：`DIRECTION_PROMPT`、`parse_direction_response`、
     `annotate_claim(claim, llm)` → direction dict

4. **up_hit_profile 聚合**（`src/investment_engine/up_hit_profile.py`）
   - T：test_up_hit_profile.py — hit_rate=hit/(hit+miss)（neutral/pending/
     insufficient 不入分子分母）、按 UP × claim_type × 月分组、渲染 markdown
     表含样本数 <10 标「样本不足」
   - C：`aggregate_profile(claims)`、`render_markdown(stats)`

5. **脚本三件套**
   - `scripts/annotate_claim_direction.py`：scope 过滤、逐条落盘（每条约写
     一次 YAML 再下一条，防中断丢失）、--limit/--dry-run/--claim-id、
     跳过已有 annotated_at；产出 logs/claim_direction_*.log
   - `scripts/settle_claim_outcomes.py`：全量扫描有 direction 的 claim，
     settle+回写，终端汇总各 result 计数
   - `scripts/build_up_hit_profile.py`：读全部 claims →
     logs/claims-vs-market-YYYYMMDD.md

6. **evaluate_vs_market.py 出数**：bucket_stats 加 outcome 命中率列
   （settled/hit/miss/hit_rate），数据就绪后替换 NO_OUTCOME_NOTE

7. **跑批与验收**
   - 判向：先 --limit 20 人工 eyeball → 全量（后台）→ 抽 30 条人审记录
   - 结算 + 画像报告 + evaluate_vs_market --report
   - 全量 pytest + 提交 + m-series 状态页更新
