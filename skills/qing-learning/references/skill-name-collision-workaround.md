# Skill 命名冲突处理

## 问题

当 skill 同时存在于以下两个位置时，`skill_view("skill-name")` 会报歧义错误：

1. `~/.hermes/skills/<skill-name>/` （Hermes 全局 skill 目录）
2. `~/learning-investment-strategies/skills/<skill-name>/` （项目 skill 目录）

Hermes 的 `external_dirs` 配置同时扫描两者：

```yaml
skills:
  external_dirs:
  - ~/.agents/skills
  - ~/learning-investment-strategies/skills
```

## 修复

项目版本是主要维护版本，重命名全局副本：

```bash
cd ~/.hermes/skills
mv <skill-name> <skill-name>-hermes-copy
```

然后 `skill_view("<skill-name>")` 自动解析到项目版本。

## 涉及的 skill

- `qing-learning-claim`
- `qing-learning-ingestion`
- `qing-learning-review`
- `qing-learning-sync`

如果发现其他同名 skill，同样的处理方法。
