# CLI 模块劫持完整排障记录（2026-08-24）

## 用户问题
"检查 ox alpha 的 provider，为什么我在 hermes agent 无法使用这个模型了，是不是 provider 被改坏了"

## 证据链（按排查顺序）

| 步骤 | 结果 |
|---|---|
| config.yaml model/providers 块 | ✅ 完好：custom_openrouter → openrouter.ai/api/v1，key 在 .env（73字符 sk-or- 前缀） |
| OpenRouter /models 列表 | ✅ 416 个模型，`stealth/ox-alpha` 存在 |
| 直连 curl（max_tokens=10） | ⚠️ 200 但 `content: null`，只有 reasoning 字段 → 误判陷阱 |
| 直连 curl（max_tokens=400） | ✅ 200，`content: "1+1等于2。"` |
| /auth/key | ✅ free tier，usage=0，key 有效 |
| errors.log | `Empty response (no content or reasoning) after 3 retries` × 多个会话；`Auxiliary: marking openrouter unhealthy for 60s (payment / credit error)` |
| `hermes chat -q "hi"` | ❌ `TypeError: main() got an unexpected keyword argument 'quiet'` |
| `hermes chat -m stealth/ox-alpha` | ❌ `TypeError: main() got an unexpected keyword argument 'model'` |

## 定位过程（含弯路）

1. **弯路 1**：`python3 -c "import cli; inspect.signature(cli.main)"` → 23 参数齐全 → 误判"没问题"。原因：预导入把正确 cli 塞进 sys.modules，掩盖了运行时劫持。
2. **弯路 2**：删 __pycache__ 重测 → 依然 TypeError，排除缓存问题。
3. **正解**：插桩入口（patch cmd_chat 打印运行时解析的 cli 模块）→
   ```
   >>> [cmd_chat] cli module file: /home/ubuntu/.hermes/plugins/self_evolution/cli.py
   >>> [cmd_chat] cli.main params: []
   TypeError: main() got an unexpected keyword argument 'quiet'
   ```
   坐实：运行时 `from cli import main` 拿到插件文件。

## 根因机制

```python
# ~/.hermes/plugins/self_evolution/__init__.py（修复前）
_SELF_EVO_DIR = str(Path(__file__).parent)      # .../self_evolution
if _SELF_EVO_DIR not in sys.path:
    sys.path.insert(0, _SELF_EVO_DIR)          # ← 污染源
```
插件目录含 `cli.py`（插件的 argparse 独立 CLI，docstring 用法 `python -m plugins.self_evolution.cli`）。目录插到 sys.path[0] 后，任何裸 `import cli`（hermes 核心多处 `from cli import ...`）都解析到插件文件。插件内部 24 处 import 全部是 `from self_evolution.*`，根本不需要自身目录在 sys.path 上。

## 修复 diff

```python
# 修复后
if _SELF_EVO_DIR not in sys.path:
    sys.path.append(_SELF_EVO_DIR)  # 末尾兜底，不影响解析优先级
# 并加注释说明原因，防回退
```

## 验证（三重）

1. 插桩入口 → `cli module file: /home/ubuntu/.hermes/hermes-agent/cli.py`，23 参数
2. `hermes chat -q "回复OK" --provider custom_openrouter` → 返回 OK
3. `hermes chat -q "1+1=?" -m stealth/ox-alpha` → 正常会话
4. `from self_evolution import _tool_status` → 插件不受影响

## 遗留问题（非本次故障，另记）

- **ox-alpha 空响应**：reasoning 模型 + 大上下文 → content=null → Hermes prefill 2 次 + retry 3 次后 `(empty)`；`fallback_providers: []` 无降级。直连能出 content 证明上游 OK。
- **auxiliary credit error**：free tier key 跑非免费辅助模型 → openrouter 熔断 60s。
