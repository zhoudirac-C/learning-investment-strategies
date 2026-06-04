from __future__ import annotations

import glob
import re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
RAW_DIR = REPO_ROOT / "sources" / "raw" / "财经"

# Sector keyword lexicon distilled from UP's raw documents.
# Each sector can have multiple surface forms.
_SECTOR_KEYWORDS: dict[str, list[str]] = {
    "光互连/CPO": ["光互连", "光互联", "光模块", "CPO", "光纤", "光通信", "光芯片", "光引擎"],
    "半导体": ["半导体", "芯片", "存储", "封测", "光刻", "清洗设备", "刻蚀", "薄膜沉积"],
    "PCB/铜材": ["PCB", "MLCC", "陶瓷基板", "ABF", "铜材", "电子布", "覆铜板", "机架母线", "再生铜"],
    "AI/算力": ["AI", "算力", "大模型", "智能体", "Agent", "AIPC", "CPU", "GPU", "昇腾"],
    "液冷/散热": ["液冷", "散热", "温控", "高导精密铜排"],
    "先进封装": ["SiP", "先进封装", "CoWoS", "Chiplet", "封装基板"],
    "机器人": ["机器人", "具身智能", "人形机器人", "Optimus", "Tesla Bot"],
    "电力/煤炭": ["电力", "煤炭", "火电", "绿电", "红利", "高股息"],
    "新能源": ["新能源", "光伏", "锂电", "储能", "风电", "海风"],
    "资源/周期": ["铜", "铝", "锂", "稀土", "黄金", "硫磺", "磷化工", "钛合金"],
    "军工": ["军工", "国防", "航天", "船舶"],
    "消费/地产": ["消费", "白酒", "地产", "房地产", "建材"],
    "港股": ["港股", "恒生科技", "中概"],
}


def _parse_date_from_filename(filename: str) -> datetime | None:
    """Extract YYYY-MM-DD from filenames like '复盘：26-06-03：...' or '早盘：26-06-04：...'."""
    m = re.search(r"(20\d{2})[-_](\d{2})[-_](\d{2})", filename)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    # Short year form: 26-06-03
    m = re.search(r"(\d{2})[-_](\d{2})[-_](\d{2})", filename)
    if m:
        try:
            year = 2000 + int(m.group(1))
            return datetime(year, int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def extract_sectors_from_docs(
    days_back: int = 7,
    top_k: int = 8,
    min_hits: int = 2,
) -> list[dict]:
    """Scan recent raw/财经 documents and return ranked sector mentions.

    Returns a list of dicts:
        [{"sector": "光互连/CPO", "hits": 12, "keywords": ["CPO", "光纤", ...]}, ...]
    """
    cutoff = datetime.now() - timedelta(days=days_back)
    sector_counter: Counter = Counter()
    keyword_map: dict[str, list[str]] = {}

    for fp in glob.glob(str(RAW_DIR / "*.md")):
        path = Path(fp)
        file_date = _parse_date_from_filename(path.name)
        if file_date is None or file_date < cutoff:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        for sector, kws in _SECTOR_KEYWORDS.items():
            hits = 0
            matched = []
            for kw in kws:
                count = text.count(kw)
                if count:
                    hits += count
                    matched.append(kw)
            if hits:
                sector_counter[sector] += hits
                keyword_map.setdefault(sector, []).extend(matched)

    results = []
    for sector, hits in sector_counter.most_common(top_k):
        if hits < min_hits:
            continue
        keywords = sorted(set(keyword_map.get(sector, [])))
        results.append({"sector": sector, "hits": hits, "keywords": keywords})

    return results


def search_sector_news(sector: str, keywords: list[str], limit: int = 3) -> list[dict]:
    """Search the web for recent news about a sector.

    Falls back to an empty list if the search tool is unavailable.
    """
    try:
        from .web_search import search_web_simple
    except Exception:
        return []

    query = f"{' '.join(keywords[:3])} 板块 最新消息 2025"
    try:
        results = search_web_simple(query, limit=limit)
    except Exception:
        results = []

    return [{"sector": sector, "query": query, **r} for r in results]


def build_sector_context(days_back: int = 7, top_k: int = 5) -> list[dict]:
    """High-level helper: extract sectors + fetch news for each."""
    sectors = extract_sectors_from_docs(days_back=days_back, top_k=top_k)
    context: list[dict] = []
    for s in sectors:
        news = search_sector_news(s["sector"], s["keywords"], limit=3)
        context.append({
            "sector": s["sector"],
            "hits": s["hits"],
            "keywords": s["keywords"],
            "news": news,
        })
    return context
