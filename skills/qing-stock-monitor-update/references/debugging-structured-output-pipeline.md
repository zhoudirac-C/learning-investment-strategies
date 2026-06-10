# 调试 LLM 结构化输出管线（通用模式）

> 当 sync scanner 已注册、代码已写，但目标文件始终未生成时的诊断方法论。
> 从 daily_state 链路断裂案例（2026-06-10）抽象出的通用调试框架。

## 症状

- `sync_xxx.py` 已存在且已注册 cron job
- 手动运行 scanner 正常（`--dry-run` 能发现代码块）
- 但目标文件（如 `daily_state.json`）从未被创建

## 诊断框架：四层断裂模型

任何 LLM→文件 的管线都可以抽象为四层：

```
┌─────────────────────────────────────────┐
│  Layer 1: Producer（LLM 输出）           │
│  LLM 是否按 prompt 要求输出了结构化标记？  │
├─────────────────────────────────────────┤
│  Layer 2: Transport（传输/存储）          │
│  LLM 输出是否被正确捕获并写入文件？        │
├─────────────────────────────────────────┤
│  Layer 3: Consumer（扫描器）              │
│  Scanner 是否能从文件中解析到结构化标记？  │
├─────────────────────────────────────────┤
│  Layer 4: Persistence（持久化）           │
│  解析后的数据是否被正确写入最终目标？      │
└─────────────────────────────────────────┘
```

**核心原则**：不要假设某一层正常——逐层验证，从下游往上游追溯。

## 逐层诊断命令

### Layer 4: Persistence（最终目标）

```bash
# 目标文件是否存在？
ls -la <target_file>
# 文件最近修改时间？
stat <target_file>
# 内容结构是否正确？
cat <target_file> | python3 -c "import sys,json; d=json.load(sys.stdin); print(list(d.keys()))"
```

### Layer 3: Consumer（Scanner）

```bash
# Scanner 是否能发现代码块？
python3 scripts/sync_xxx.py --dry-run
# Scanner 对实际 cron 输出文件的解析结果？
python3 scripts/sync_xxx.py --input <latest_cron_output.md>
# Scanner 日志（如果有）
tail -n 50 /tmp/sync_xxx.log
```

### Layer 2: Transport（Cron 输出文件）

```bash
# 最新 cron 输出文件内容
latest=$(ls -t ~/.hermes/cron/output/<job_id>/*.md 2>/dev/null | head -1)
# 是否含结构化标记？
grep -c "\`\`\`<marker_name>" "$latest"
# 标记内容是否完整？
grep -A 20 "\`\`\`<marker_name>" "$latest"
# Cron 输出是否被截断？（文件大小异常小）
ls -la "$latest"
```

### Layer 1: Producer（LLM 输出源头）

```bash
# 如果是 Qing-Agent 路径：测试端点直接输出
curl -s --max-time 30 -X POST http://localhost:8000/analyze/trigger \
  -H "Content-Type: application/json" \
  -d '{"query":"测试","session_id":"test","analysis_type":"market"}' \
  | grep -c "<marker_name>"

# 如果是 Hermes fallback 路径：检查 cron prompt 是否要求输出标记
grep -c "<marker_name>" ~/.hermes/cron/jobs/<job_id>/prompt.md

# 检查 Qing-Agent 是否实际被调用（非 fallback）
grep -c "Qing-Agent ✓" "$latest"
```

## 常见断裂模式与修复

### 模式 A: Producer 未输出标记

**症状**：Layer 1 测试无标记。
**根因**：
- Prompt 未要求输出标记
- LLM 不遵守 prompt（尤其是 GPT-4o 对代码块格式不敏感）
- 分析类型不匹配（如 `stock_analyst` 节点未要求 daily_state）

**修复**：
1. 在 prompt 中明确要求 ````marker_name` 代码块
2. 在 system prompt 中加入 Few-Shot 示例
3. 在节点返回前增加 fallback 推导（从 JSON 规范化字段生成）

### 模式 B: Transport 丢失标记

**症状**：Layer 1 有标记，Layer 2 文件无标记。
**根因**：
- Cron 脚本超时，输出被截断
- 输出重定向丢失（如 `>` 覆盖了 `>>`）
- 多进程竞争写入同一文件

**修复**：
1. 检查 cron 超时层级（Hermes scheduler → wrapper → 脚本内 → HTTP）
2. 确保超时递增：LLM < worker < HTTP < wrapper < scheduler
3. 使用原子写入（写临时文件后 rename）

### 模式 C: Consumer 解析失败

**症状**：Layer 2 文件有标记，Layer 3 scanner 解析不到。
**根因**：
- 正则表达式不匹配（如 `
` vs `
`）
- 标记格式变异（如 ````marker_name` 后多了空格）
- JSON 解析失败（标记内内容不是合法 JSON）

**修复**：
1. 用 `--dry-run` 打印 scanner 看到的原始内容
2. 放宽正则表达式（允许空格、大小写不敏感）
3. 增加 JSON 解析错误处理（try/except + 日志）

### 模式 D: Persistence 未调用

**症状**：Layer 3 scanner 能解析，Layer 4 文件未生成。
**根因**：
- Scanner 解析后未调用 save 函数
- save 函数路径错误（相对路径 vs 绝对路径）
- 权限问题（目录不可写）

**修复**：
1. 在 scanner 中加入 `--verbose` 模式，打印 save 调用参数
2. 使用绝对路径（`os.path.expanduser()`）
3. 检查目录权限：`ls -ld $(dirname <target_file>)`

## 从 daily_state 案例映射

| 断裂层 | daily_state 具体表现 | 修复 |
|--------|---------------------|------|
| Layer 1 | `market_analyst` 节点未要求输出 ````daily_state` | 在 prompt 中明确要求 |
| Layer 1b | 即使要求了，节点只解析 JSON，丢弃代码块 | 在 return 前插入 `_extract_daily_state_block()` |
| Layer 2 | Qing-Agent 未启动 → cron 走 fallback → Hermes 直接生成 | 启动 Qing-Agent + gunicorn |
| Layer 2b | Cron 超时导致输出截断 | 调大 `HERMES_CRON_SCRIPT_TIMEOUT` |
| Layer 3 | `sync_daily_state.py` 正则正常，但扫描不到 | 实际是因为 Layer 2 无标记 |
| Layer 4 | `save_daily_state()` 从未被调用 | 在 `market_analyst` 节点内调用 |

## 快速检查清单

遇到"scanner 存在但文件未生成"时，按顺序执行：

1. [ ] `ls -la <target_file>` — 文件是否存在？
2. [ ] `python3 scripts/sync_xxx.py --dry-run` — scanner 是否正常？
3. [ ] `grep -c "<marker>" <latest_cron_output>` — cron 输出是否含标记？
4. [ ] `curl .../analyze/trigger | grep -c "<marker>"` — Qing-Agent 是否输出标记？
5. [ ] `grep -c "Qing-Agent ✓" <latest_cron_output>` — 是否走了 Qing-Agent 路径？
6. [ ] `grep -c "<marker>" <cron_prompt>` — cron prompt 是否要求标记？
7. [ ] 检查超时层级是否对齐

## 相关参考

- `references/daily-state-pipeline-root-cause.md` — daily_state 专属案例
- `references/daily-state-persist-implementation.md` — 具体代码实现
- `references/cron-script-timeout-diagnosis.md` — 超时诊断
- `references/qing-agent-service-operations.md` — 服务运维
