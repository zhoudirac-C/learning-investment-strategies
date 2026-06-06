# Hermes Agent 与 Qing-Agent 交互约定

## 背景

Hermes Agent（当前AI助手）和 Qing-Agent（项目后端服务）是两个独立的AI系统。用户需要清楚区分两者的输出。

## 交互模式

### 模式1：Hermes 直接调用 Qing-Agent（推荐）

当用户问股票/市场/持仓问题时，Hermes 直接调 Qing-Agent 的 `/chat` 端点：

```bash
curl -s -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "用户问题", "session_id": "user-xxx"}'
```

**特点**：
- Qing-Agent 自动获取实时数据 + 历史K线
- 回复自动带 `[Qing-Agent 分析]` 前缀
- Hermes 直接呈现，不做额外包装

### 模式2：Hermes 自身分析 + Qing-Agent 补充

当问题涉及持仓配置（positions.yaml）等私有数据时：

1. Hermes 先读取本地配置文件
2. Hermes 调用 Qing-Agent 获取市场分析
3. Hermes 结合持仓数据给出具体建议

**呈现格式**：
```
[Qing-Agent 分析]

（Qing-Agent 的市场分析...）

---

**持仓分析**（Hermes Agent）：
- 成本：18.07，当前：17.05，浮亏：5.7%
- 仓位：400股，约1%总资产
- 建议：按计划执行
```

### 模式3：纯 Hermes 分析

当问题不涉及市场判断（如代码修改、部署、git操作）时，Hermes 直接回答，不调用 Qing-Agent。

## 用户偏好

### 来源标注要求（硬性）

- Qing-Agent 输出 → 必须带 `[Qing-Agent 分析]` 前缀
- Hermes 自身分析 → 不加前缀，或明确标注"（Hermes Agent）"
- 混合场景 → 用 `---` 分隔两部分

### 持仓分析时的数据读取

当用户问"要不要割肉"且持仓配置已知时：

1. **先读 positions.yaml**：获取成本、仓位、清仓线
2. **再调 Qing-Agent**：获取市场技术面分析
3. **结合两者**：给出具体操作建议（不是"取决于你"的模糊回答）

**禁止**：
- 不读持仓配置就说"取决于你的成本"
- 不调用 Qing-Agent 就给出市场判断
- 把 Qing-Agent 的分析当作自己的分析呈现

## 代码位置

- Qing-Agent `/chat` 端点：`src/qing_investment/agent/main.py`
- 持仓配置：`config/stock_monitor/positions.yaml`
- 来源标注 prompt：`main.py` 中 `prompt_lines` 第7条

## 故障排查

### Qing-Agent 回复没有前缀

1. 检查服务是否重启
2. 检查 `main.py` 中 prompt 是否包含格式要求
3. 验证：`curl /chat` 后检查 `reply[:20]`

### 持仓数据读取失败

1. 检查文件路径：`config/stock_monitor/positions.yaml`
2. 检查权限：文件是否可读
3. 检查格式：YAML 是否有效

### 混合分析时用户困惑

如果用户问"这是你说的还是 Qing-Agent 说的"，说明来源区分不够清晰。应该：
1. 明确标注每部分的来源
2. 用 `---` 或标题分隔
3. 必要时口头说明"以上是 Qing-Agent 的分析，以下是我基于你持仓的补充"
