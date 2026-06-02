# Patch 工具歧义匹配陷阱

> 记录更新 watchlist.yaml / strategy_pack.yaml 时，patch 工具因匹配到多处而失败的场景和解决方法。

---

## 问题描述

`watchlist.yaml` 和 `strategy_pack.yaml` 中，**同一个 stock 名称可能出现在多个位置**：

1. `today_snapshot.stocks_with_data` — 收盘数据摘要列表
2. `themes[].stocks` — 各 theme 下的观察标的列表
3. `sector_groups[].members` — 板块分组成员列表

当使用 patch 工具更新某个 stock 的字段时，如果 `old_string` 只包含 `name: "万通发展"` 这样的简短文本，patch 会匹配到多处，导致失败。

---

## 复现示例

### 失败：匹配到多处

```yaml
# today_snapshot.stocks_with_data 中也有万通发展
- code: "600246.SH"
  name: "万通发展"
  latest: 16.81

# themes 下也有万通发展
themes:
  - name: "CPU自研链"
    stocks:
      - code: "600246.SH"
        name: "万通发展"
        role: "pcie_switch_core"
```

Patch 尝试：
```
old_string: '  name: "万通发展"'
new_string: '  name: "万通发展"\n  new_field: "value"'
```
→ 失败：`Could not find a unique match`

---

## 解决方法

### 方法 1：增加上下文行（推荐）

在 `old_string` 中包含该 stock 的 `code:` 行和相邻字段，确保唯一匹配：

```
old_string: |
      - code: "600246.SH"
        name: "万通发展"
        role: "pcie_switch_core"
new_string: |
      - code: "600246.SH"
        name: "万通发展"
        role: "pcie_switch_core"
        new_field: "value"
```

**要点**：包含 `code:` + `name:` + 至少一个相邻字段（如 `role:`），这样即使 `name` 重复，`code` 也能确保唯一性。

### 方法 2：使用列表索引上下文

如果知道目标 stock 在列表中的位置，可以包含前后 stock 的 `name` 作为锚点：

```
old_string: |
      - code: "002055.SZ"
        name: "得润电子"
      - code: "600246.SH"
        name: "万通发展"
      - code: "688256.SH"
        name: "寒武纪"
```

### 方法 3：先读取再定位

使用 `read_file` 读取目标文件，确认 stock 出现的具体位置（行号），然后构造足够长的上下文。

---

## 纪律

- **Patch 前先用 `read_file` 确认目标位置**，尤其是同一 stock 名出现多次的文件。
- **old_string 至少包含 3 行**：`code:`、`name:`、以及一个相邻字段或前后条目。
- **避免只匹配 `name:` 单行**，这是最常见的失败原因。
- **如果 stock 在 today_snapshot 和 themes 中都有**，明确指定要更新的是哪个区域（通过包含区域特有的字段如 `role:` 或 `latest:` 来区分）。
