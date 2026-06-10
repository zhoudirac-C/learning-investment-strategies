# Skill Document Maintenance Hygiene

## 背景

`qing-stock-monitor-update/SKILL.md` 经过 10+ 次增量 patch 后，出现了以下文档腐败问题：
- 陷阱编号跳跃（8 之后直接 10，缺失 9）
- 陷阱 10/11/12 在文档末尾**重复出现两次**
- Markdown 代码块闭合符号 ` ``` ` 后残留未清理的文本碎片

这些问题导致：
1. 新 Agent 阅读技能文档时被重复内容干扰
2. 陷阱编号不连续，引用时产生歧义
3. 文档体积膨胀（24KB → 应控制在 20KB 以内）

## 根因

多次使用 `patch` 工具的 `replace_all=True` 或模糊匹配时，未验证替换结果的唯一性。当旧字符串在文档中出现多次时，patch 会替换所有匹配位置，导致重复。

## 修复流程（标准操作）

当发现技能文档存在重复/缺失/碎片时：

```bash
# 1. 读取完整文件（不要用 offset/limit 分页，会遗漏上下文）
cat skills/<name>/SKILL.md > /tmp/skill_full.md

# 2. 检查陷阱编号连续性
grep -n "^### 陷阱 [0-9]" /tmp/skill_full.md

# 3. 检查重复段落（以陷阱标题为锚点）
for n in $(seq 1 20); do
  count=$(grep -c "^### 陷阱 $n:" /tmp/skill_full.md)
  [ "$count" -gt 1 ] && echo "陷阱 $n 重复 $count 次"
done

# 4. 检查 Markdown 代码块是否正确闭合
grep -n "^\`\`\`" /tmp/skill_full.md | tail -5
# 每对 ``` 之间应有成对出现
```

## 预防措施

1. **Patch 前先用 `read_file` 读取完整文件**（不用分页），确认旧字符串唯一性
2. **Patch 后立即用 `read_file` 验证**陷阱编号连续性和重复段落
3. **定期整理**：当技能文档 >20KB 时，将详细案例迁移到 `references/*.md`，SKILL.md 只保留摘要和链接
4. **新增陷阱时**：先 `grep -n "^### 陷阱"` 确认当前最大编号，避免跳跃

## 验证命令

```bash
cd ~/learning-investment-strategies
# 陷阱编号连续性
python3 -c "
import re
content = open('skills/qing-stock-monitor-update/SKILL.md').read()
traps = [int(m.group(1)) for m in re.finditer(r'^### 陷阱 (\d+):', content, re.M)]
print(f'Found traps: {traps}')
missing = [i for i in range(1, max(traps)+1) if i not in traps]
if missing:
    print(f'MISSING: {missing}')
dupes = [t for t in traps if traps.count(t) > 1]
if dupes:
    print(f'DUPLICATES: {set(dupes)}')
print('OK' if not missing and not dupes else 'NEEDS FIX')
"
```
