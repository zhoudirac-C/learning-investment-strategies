"""KPL 资讯本地初调层（v2.2 §16.4）：按关键词/股票池过滤当日落盘资讯，出每日初调摘要。

输入：`infra/data/kpl/news/<day>/index.json`（kpl_daily_fetch 日更落盘；
fetched=false 的付费条目只有标题，仍作线索保留）。
输出：`infra/data/kpl/digest/<day>.md`（人读摘要，分组：全文可读 / 仅标题线索）。

匹配口径 v1：只匹配标题（付费条目无正文，标题是唯一公平输入）；
关键词 = 产业词基表 + 股票池个股名（config/stock_monitor/stock_pool.yaml）。
"""
from __future__ import annotations

import json
from pathlib import Path

NEWS_ROOT = Path("infra/data/kpl/news")
DIGEST_ROOT = Path("infra/data/kpl/digest")
STOCK_POOL = Path("config/stock_monitor/stock_pool.yaml")

# 产业词基表：命中即值得初调阅读（宁宽勿漏，摘要是人读的）
BASE_KEYWORDS = [
    "产业链", "涨价", "提价", "调价", "涨价函",
    "扩产", "满产", "产能", "缺货", "断供",
    "订单", "定点", "中标", "认证", "供货",
    "调研", "拆解", "梳理", "深度",
]


def load_stock_names(pool_path: Path = STOCK_POOL) -> list[str]:
    """从股票池取个股名（标题点名观察池个股 = 高信号）。文件缺失返回空表。"""
    try:
        import yaml

        cfg = yaml.safe_load(Path(pool_path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - 缺文件/解析失败都不阻断
        return []
    return [s["name"] for s in (cfg or {}).get("stocks", []) if s.get("name")]


def load_index(day: str, news_root: Path = NEWS_ROOT) -> list[dict]:
    path = Path(news_root) / day / "index.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def match_articles(items: list[dict], keywords: list[str]) -> list[dict]:
    """标题命中任一关键词的条目，附命中词列表。空关键词表返回空。"""
    kws = [k for k in keywords if k]
    if not kws:
        return []
    hits = []
    for it in items:
        title = it.get("title") or ""
        matched = [k for k in kws if k in title]
        if matched:
            hits.append({"id": it.get("id"), "title": title,
                         "fetched": bool(it.get("fetched")),
                         "matched": matched,
                         "stocks": [s.get("name") for s in (it.get("stocks") or [])
                                    if isinstance(s, dict) and s.get("name")]})
    return hits


def render_digest(day: str, hits: list[dict], *, total: int) -> str:
    full = [h for h in hits if h["fetched"]]
    title_only = [h for h in hits if not h["fetched"]]
    lines = [
        f"# KPL 资讯初调摘要（{day}）",
        "",
        f"- 当日资讯 {total} 条，命中 {len(hits)} 条（全文可读 {len(full)} / 仅标题线索 {len(title_only)}）",
        "- 匹配口径：标题关键词（产业词基表 + 股票池个股名）；全文在同目录 news/<day>/<id>.md",
        "",
        "## 全文可读",
        "",
    ]
    for h in full:
        stocks = f"（关联：{'、'.join(h['stocks'][:3])}）" if h["stocks"] else ""
        lines.append(f"- [{h['id']}] {h['title']}　← 命中：{'、'.join(h['matched'])}{stocks}")
    lines += ["", "## 仅标题线索（付费/未取全文）", ""]
    for h in title_only:
        lines.append(f"- [{h['id']}] {h['title']}　← 命中：{'、'.join(h['matched'])}")
    lines.append("")
    return "\n".join(lines)


def run(day: str, *, news_root: Path = NEWS_ROOT, digest_root: Path = DIGEST_ROOT,
        stock_pool: Path = STOCK_POOL, extra_keywords: list[str] | None = None) -> Path | None:
    """生成某日初调摘要。当日无资讯落盘返回 None（节假日/拉取失败）。"""
    items = load_index(day, news_root)
    if not items:
        return None
    keywords = BASE_KEYWORDS + load_stock_names(stock_pool) + list(extra_keywords or [])
    hits = match_articles(items, keywords)
    out = Path(digest_root) / f"{day}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_digest(day, hits, total=len(items)), encoding="utf-8")
    return out
