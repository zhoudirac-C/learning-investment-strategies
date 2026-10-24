# M3 回写实施计划（2026-10-24）

设计：docs/superpowers/specs/2026-10-24-m3-outcome-writeback.md

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
