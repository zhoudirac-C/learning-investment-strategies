# Qing-Agent 输出来源标注规范

## 背景

用户同时与两个 Agent 交互：
- **Hermes Agent**：通用 AI 助手，具备代码执行、文件操作、系统管理能力
- **Qing-Agent**：项目内的专用投资分析 Agent，封装了博主框架、实时数据、知识库检索

当 Hermes Agent 调用 Qing-Agent 的 `/chat` 端点回答投资问题时，用户需要明确知道**这个结论来自 Qing-Agent 还是 Hermes Agent 自己的判断**。

## 强制规范

### 1. Qing-Agent 输出必须自标注

Qing-Agent 的 `/chat` 端点 prompt 中必须包含：

```
【输出格式】回复开头必须标注：'[Qing-Agent 分析]'，然后空一行再写正文
```

所有 `/chat` 回复必须以如下格式开头：

```
[Qing-Agent 分析]

第一步：...
```

### 2. Hermes Agent 必须透传来源

当 Hermes Agent 调用 `/chat` 并将结果返回给用户时：

- ✅ **正确做法**：保留 `[Qing-Agent 分析]` 前缀，让用户知道这是 Qing-Agent 的结论
- ❌ **错误做法**：去掉前缀，让用户误以为是 Hermes Agent 自己的分析
- ❌ **错误做法**：Hermes Agent 在 Qing-Agent 输出后面追加自己的判断但不加标注

### 3. Hermes Agent 补充判断时的标注

如果 Hermes Agent 需要在 Qing-Agent 输出之外补充自己的判断（如读取 positions.yaml 计算盈亏），必须明确区分：

```
---
[Qing-Agent 分析]

（Qing-Agent 的原始分析内容）

---

我（Hermes）补充一下持仓数据：
- 你的成本是 X.XX 元
- 当前浮亏 X%
- 结合 Qing-Agent 的"若跌破 Y 则减仓"建议...
```

## 为什么重要

1. **责任归属**：Qing-Agent 基于博主框架和实时数据，Hermes Agent 基于通用知识，两者可能结论不同
2. **可追溯性**：用户知道某个判断来自哪个系统，便于排查和验证
3. **风格一致性**：Qing-Agent 有特定的"犀利但不劝赌"风格，Hermes Agent 不应稀释或改变这种风格
4. **用户信任**：用户明确说"是否可以标注，使用 qing agent 的回复，这样我可以知道你是调用它得到的结论"

## 触发场景

以下场景必须标注来源：
- 用户问个股分析（"分析一下中国长城"）
- 用户问大盘/板块（"今天大盘怎么样"）
- 用户问持仓建议（"我需要割肉吗"）
- 用户问观察池/量化策略
- 任何 Hermes Agent 选择调用 Qing-Agent `/chat` 端点的场景

## 常见错误

1. **不标注来源**：直接输出 Qing-Agent 的回复但不说明来源
2. **来源混淆**：把 Qing-Agent 的结论说成是自己的判断
3. **前缀丢失**：在格式化/精简回复时意外删除 `[Qing-Agent 分析]`
4. **混合输出不区分**：Qing-Agent 输出 + Hermes 补充混在一起，没有分界线
