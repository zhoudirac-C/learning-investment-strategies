"""东财研报/公告日更管线（v2.2 §16.4 主力源，2026-08-15 spike 实测定案）。

数据源（公开源，无封号风险）：
- 研报：`reportapi.eastmoney.com/report/list`——qType=0 个股 / 1 行业 / 2 策略；
  `code=*` 全量列表；`industryCode` 行业过滤有效（如 459=元件）；
  beginTime/endTime 按发布日过滤；**自由关键词参数无效（实测忽略），不做关键词检索**；
  PDF 直链 `https://pdf.dfcfw.com/pdf/H3_<infoCode>_1.pdf`（实测 200 可下载）。
- 公告：akshare `stock_notice_report`（东财公告大全，按日按类型）。

落盘（infra/data 下，gitignored）：
- `infra/data/research/reports/<YYYY-MM-DD>.json`  研报元数据（按发布日分组）
- `infra/data/research/notices/<YYYY-MM-DD>.json`  公告（按公告日）

频率纪律：页间 sleep 0.3s；日报每日一次（cron）；回填用 --start/--end 范围拉取。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

REPORT_API = "https://reportapi.eastmoney.com/report/list"
PDF_TMPL = "https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf"
DEFAULT_ROOT = Path("infra/data/research")
QTYPES = ("0", "1", "2")  # 个股 / 行业 / 策略
QTYPE_NAMES = {"0": "个股研报", "1": "行业研报", "2": "策略报告"}
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")
_PAGE_INTERVAL = 0.3


class ResearchFeedError(Exception):
    """研报/公告拉取失败。"""


def _get_page(params: dict, *, session=None, retries: int = 2) -> dict:
    http = session or requests
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            r = http.get(REPORT_API, params=params, timeout=15,
                         headers={"User-Agent": _UA})
            return r.json()
        except Exception as e:  # noqa: BLE001 - 重试后如实报错
            last_err = e
            if attempt < retries:
                time.sleep(1.0 * (attempt + 1))
    raise ResearchFeedError(f"report/list 重试{retries}次后仍失败: {last_err}")


def _norm_row(d: dict, qtype: str) -> dict | None:
    info_code = d.get("infoCode")
    title = (d.get("title") or "").strip()
    if not info_code or not title:
        return None
    return {
        "info_code": info_code,
        "title": title,
        "org": d.get("orgSName") or "",
        "author": d.get("author") or "",
        "publish_date": str(d.get("publishDate") or "")[:10],
        "qtype": qtype,
        "qtype_name": QTYPE_NAMES.get(qtype, qtype),
        "industry_code": str(d.get("indvInduCode") or ""),
        "industry_name": d.get("indvInduName") or d.get("industryName") or "",
        "stock_code": str(d.get("stockCode") or ""),
        "stock_name": d.get("stockName") or "",
        "rating": d.get("emRatingName") or "",
        "pdf_url": PDF_TMPL.format(info_code=info_code),
        "pages": d.get("attachPages"),
    }


def fetch_reports_range(start: str, end: str, *, qtypes=QTYPES, session=None) -> list[dict]:
    """按发布日范围拉全量研报元数据，按 info_code 去重（先见先得）。"""
    seen: set[str] = set()
    out: list[dict] = []
    for qtype in qtypes:
        params = {
            "pageSize": "500", "pageNo": "1",
            "industryCode": "*", "industry": "*", "rating": "*", "ratingChange": "*",
            "beginTime": start, "endTime": end,
            "fields": "", "orgCode": "", "rcode": "",
            "p": "1", "pageNum": "1", "pageNumber": "1",
            "qType": qtype, "code": "*",
        }
        payload = _get_page(params, session=session)
        total_page = payload.get("TotalPage") or 1
        while True:
            rows = payload.get("data") or []
            for d in rows:
                row = _norm_row(d, qtype)
                if row and row["info_code"] not in seen:
                    seen.add(row["info_code"])
                    out.append(row)
            page_no = int(params["pageNo"])
            if page_no >= total_page or not rows:
                break
            params.update({k: str(page_no + 1)
                           for k in ("pageNo", "p", "pageNum", "pageNumber")})
            time.sleep(_PAGE_INTERVAL)
            payload = _get_page(params, session=session)
    return out


def group_by_date(rows: list[dict]) -> dict[str, list[dict]]:
    """按 publish_date 分组（无日期的行丢弃，防止脏数据落成幽灵日期文件）。"""
    out: dict[str, list[dict]] = {}
    for r in rows:
        day = r.get("publish_date") or ""
        if len(day) == 10 and day[4] == "-":
            out.setdefault(day, []).append(r)
    return out


def fetch_notices(day: str) -> list[dict]:
    """拉某日全量公告（akshare 东财公告大全）。day 格式 YYYYMMDD 或 YYYY-MM-DD。"""
    import akshare as ak

    d = day.replace("-", "")
    df = ak.stock_notice_report(symbol="全部", date=d)
    out = []
    for _, r in df.iterrows():
        title = str(r.get("公告标题") or "").strip()
        if not title:
            continue
        out.append({
            "code": str(r.get("代码") or ""),
            "name": str(r.get("名称") or ""),
            "title": title,
            "type": str(r.get("公告类型") or ""),
            "date": str(r.get("公告日期") or "")[:10],
            "url": str(r.get("网址") or ""),
        })
    return out


def reports_path(day: str, root: Path = DEFAULT_ROOT) -> Path:
    return Path(root) / "reports" / f"{day}.json"


def notices_path(day: str, root: Path = DEFAULT_ROOT) -> Path:
    return Path(root) / "notices" / f"{day}.json"


def save_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8")
    return path


def run_range(start: str, end: str, *, root: Path = DEFAULT_ROOT, force: bool = False,
              with_notices: bool = True, session=None) -> dict:
    """范围拉取并按日落盘。已存在且非 force 的日期跳过（幂等）。

    返回 {"reports": {day: n}, "notices": {day: n}, "skipped": [day...]}。
    """
    root = Path(root)
    rows = fetch_reports_range(start, end, session=session)
    by_day = group_by_date(rows)
    stats = {"reports": {}, "notices": {}, "skipped": []}
    for day, items in sorted(by_day.items()):
        path = reports_path(day, root)
        if path.exists() and not force:
            stats["skipped"].append(day)
            continue
        save_json(path, items)
        stats["reports"][day] = len(items)
    if with_notices:
        for day in _date_span(start, end):
            npath = notices_path(day, root)
            if npath.exists() and not force:
                continue
            try:
                items = fetch_notices(day)
            except Exception as e:  # noqa: BLE001 - 单日公告失败不阻断
                stats["notices"][day] = f"error: {str(e)[:80]}"
                continue
            save_json(npath, items)
            stats["notices"][day] = len(items)
            time.sleep(_PAGE_INTERVAL)
    return stats


def _date_span(start: str, end: str) -> list[str]:
    """[start, end] 每日日期列表（YYYY-MM-DD）；公告周末也有，不按交易日过滤。"""
    from datetime import date, timedelta

    s = date.fromisoformat(start)
    e = date.fromisoformat(end)
    days = []
    while s <= e:
        days.append(s.isoformat())
        s += timedelta(days=1)
    return days


def download_pdf(info_code: str, out_dir: Path, *, timeout: float = 30.0) -> Path:
    """按需下载单篇研报 PDF（日更只存元数据，PDF 在提取内容时才拉）。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{info_code}.pdf"
    url = PDF_TMPL.format(info_code=info_code)
    req = requests.get(url, timeout=timeout, headers={"User-Agent": _UA})
    if req.status_code != 200 or not req.content.startswith(b"%PDF"):
        raise ResearchFeedError(f"PDF 下载失败 {info_code}: status={req.status_code}")
    path.write_bytes(req.content)
    return path
