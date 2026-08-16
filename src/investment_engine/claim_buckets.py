"""claims 五桶分桶与双格式解析（主计划 §12 / §16.6，M3 代码基建先行）。

仓库 claims 两种存储格式：
- 独立 YAML（``claim-*.yaml``）：顶层 ``claims:`` 列表，或单 claim 字典；
- 聚合 Markdown（``*.md``）：``## claim: <id>`` 块 + ``- key: `value` `` 行。

桶定义（主计划 §12）：``up``（UP 教材）/ ``agent``（AI 自产）/
``research``（研报）/ ``announcement``（公告）/ ``data``（量价数据回写）。
当前存量几乎全为 up + 少量 research；agent/announcement/data 为机制预留桶，
命中 0 属预期。映射只做在读侧（本模块），不回写改动 claims 原文件。
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

BUCKETS = ("up", "agent", "research", "announcement", "data", "other")

# md 块内顶层字段行：`- key: `value``（嵌套 links 子项有缩进，不匹配）
_MD_FIELD_RE = re.compile(r"^-\s*(?P<key>[a-z_]+):\s*(?P<val>.*)$")
_MD_HEAD_RE = re.compile(r"^##\s+claim:\s*(?P<id>\S+)")

_FIELDS = (
    "id", "source_path", "source_date", "source_type", "extracted_at",
    "claim_type", "subject", "timeframe", "statement", "confidence", "status",
)


def bucket_of(source_type: str | None, source_path: str | None) -> str:
    """source_type / source_path → 五桶之一；兜底 other（报告中单列，强制评审）。

    source_path 存量有三种形态：相对路径（sources/raw/...）、绝对路径
    （含仓库根前缀）、单 claim 独立 YAML 里的相对路径——统一用包含匹配。
    """
    st = (source_type or "").strip()
    sp = (source_path or "").strip()
    st_lower = st.lower()
    if "研报" in st or "institution-report" in st_lower or "sources/research" in sp:
        return "research"
    if "公告" in st or "announcement" in st_lower:
        return "announcement"
    if st_lower == "agent" or "evals/shadow" in sp:
        return "agent"
    if st_lower in {"data", "数据"} or "infra/data" in sp:
        return "data"
    # 缠论课程卡片（sources/chanlun）与 UP 内容同为教材性质，并入 up 桶；
    # 全部为 technical-knowledge 类，不参与市场命中率，桶权重不受其影响。
    if any(k in sp for k in ("sources/raw", "sources/incoming", "sources/original",
                             "sources/chanlun")):
        return "up"
    return "other"


def parse_yaml_claims(path: Path) -> list[dict]:
    """解析 YAML claims；兼容两种结构（顶层 claims 列表 / 单 claim 字典）。

    坏文件返回空列表由调用方计数。
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("claims"), list):
        items = data["claims"]
    elif isinstance(data, dict) and data.get("id"):
        items = [data]  # 单 claim 独立文件（claim-YYYYMMDD-NNN-x.yaml）
    elif isinstance(data, list):
        items = data
    else:
        return []
    return [{k: ("" if c.get(k) is None else str(c.get(k))) for k in _FIELDS}
            for c in items if isinstance(c, dict) and c.get("id")]


def parse_md_claims(path: Path) -> list[dict]:
    """解析聚合 Markdown：`## claim:` 开块，顶层 `- key: `value`` 行取字段。"""
    claims: list[dict] = []
    cur: dict | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        head = _MD_HEAD_RE.match(line)
        if head:
            cur = {k: "" for k in _FIELDS}
            cur["id"] = head.group("id")
            claims.append(cur)
            continue
        if cur is None:
            continue
        if line.startswith("## "):  # 下一个非 claim 标题，封块
            cur = None
            continue
        m = _MD_FIELD_RE.match(line)
        if m and m.group("key") in _FIELDS:
            val = m.group("val").strip()
            if len(val) >= 2 and val.startswith("`") and val.endswith("`"):
                val = val[1:-1]
            cur[m.group("key")] = val
    return claims


# 目录内的说明/索引文档，非 claim 数据文件，跳过且不计入解析失败
_SKIP_FILES = {"readme.md", "index.md"}


def load_claims(claims_dir: Path) -> tuple[list[dict], int]:
    """加载目录下全部 claims，附 bucket；返回 (记录列表, 跳过文件数)。"""
    claims_dir = Path(claims_dir)
    records: list[dict] = []
    skipped = 0
    if not claims_dir.exists():
        return records, skipped
    for path in sorted(claims_dir.iterdir()):
        if path.name.lower() in _SKIP_FILES:
            continue
        if path.suffix == ".yaml":
            parsed = parse_yaml_claims(path)
        elif path.suffix == ".md":
            parsed = parse_md_claims(path)
        else:
            continue
        if not parsed and path.stat().st_size > 0:
            skipped += 1
        for rec in parsed:
            rec["bucket"] = bucket_of(rec.get("source_type"), rec.get("source_path"))
            rec["file"] = path.name
            records.append(rec)
    return records, skipped
