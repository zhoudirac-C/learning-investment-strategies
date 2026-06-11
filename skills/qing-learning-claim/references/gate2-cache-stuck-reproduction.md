# Gate 2 缓存卡死复现与修复（2026-06-11 案例）

## 场景

提取 7 条 claims（半导体材料对日替代主线），Gate 2 失败。

## 复现步骤

1. 写 `step2_enriched.json`，其中 **claim-003 interpretation** 含未标注代码的公司名：
   ```
   "UP将中船特气和江丰电子归为同一涨价主线"
   ```
2. 运行 `python scripts/extract_claims_pipeline.py continue`
3. Gate 2 报错：`'特气和江丰电子' 在文本中出现但未标注 6 位代码`
4. 修正 interpretation 为：
   ```
   "UP将中船特气(688146)和江丰电子(300666)归为同一涨价主线"
   ```
5. 再运行 `continue` → **仍报同样的错误**
6. 又改了 subject 和 topic → 还在报 → `continue` 计数器到第 3 次

## 根因

`extract_claims_pipeline.py:313` 的 gate 跳过逻辑：

```python
if step2_file.exists() and not (sess_dir / "gate2_result.json").exists():
```

第一次 `continue` 时 gate2 失败 → 写了 `gate2_result.json`。后续每次 `continue`
**读这个缓存文件**返回失败结果，不再重新执行 gate。pipeline 不比较时间戳。

## 修复

```bash
rm temp/claims/20260611_171554_19f0e0/gate2_result.json
python scripts/extract_claims_pipeline.py continue
```

删除缓存后重跑 → Pipeline 检测到 `gate2_result.json` 不存在 → 重新执行 Gate 2
→ 用修正后的 `step2_enriched.json` → **通过**。

## 教训

- 每次修改 step 产物后，如遇 gate 仍报相同错误，**先删缓存后重试**
- 不是你的修正不对——是 pipeline 没看到你的改动
- 三条 cache file：`gate1_result.json` / `gate2_result.json` / `gate3_result.json`
- `continue` 不会告诉你"使用了缓存"——它静默读取
