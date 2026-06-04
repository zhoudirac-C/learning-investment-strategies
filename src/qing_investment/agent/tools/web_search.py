from __future__ import annotations


def search_web_simple(query: str, limit: int = 3) -> list[dict]:
    """Search the web using DuckDuckGo and return simplified results."""
    try:
        from ddgs import DDGS
    except Exception:
        return []

    try:
        with DDGS() as ddgs:
            results = ddgs.text(query, max_results=limit)
    except Exception:
        return []

    out = []
    for r in results:
        out.append(
            {
                "title": r.get("title", ""),
                "url": r.get("href", ""),
                "snippet": r.get("body", ""),
            }
        )
    return out
