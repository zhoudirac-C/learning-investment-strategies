"""个股板块映射与板块内地位判断（多接口降级）。

支持从新浪、东方财富等接口获取：
1. 个股所属板块（概念+行业）
2. 板块内成分股实时排名
3. 个股在板块内的量化地位判断

缓存策略：
- 个股→板块映射缓存为本地 JSON（每日自动过期重建）
- 板块成分股数据实时获取（带 30s 内存缓存）
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

# ── 配置 ──
_CACHE_DIR = Path(__file__).resolve().parents[4] / "config" / "stock_monitor"
_CACHE_FILE = _CACHE_DIR / "stock_sector_mapping.json"
_CACHE_TTL_SECONDS = 86400  # 24小时

_SINA_BOARD_LIST_URL = {
    "concept": "http://money.finance.sina.com.cn/q/view/newFLJK.php?param=class",
    "industry": "http://money.finance.sina.com.cn/q/view/newFLJK.php?param=industry",
}

_SINA_CONSTITUENTS_URL = (
    "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php"
    "/Market_Center.getHQNodeData"
    "?page=1&num={page_size}&sort=changepercent&asc=0&node={node}"
)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://finance.sina.com.cn/",
    "Accept": "*/*",
}

# 内存缓存：板块成分股（60秒）
_constituents_cache: dict[str, tuple[list[dict], float]] = {}
_CONSTITUENTS_CACHE_TTL = 60.0

# 请求间隔（秒）——新浪 getHQNodeData 有频率限制
_REQUEST_DELAY = 1.5
_last_request_time: float = 0.0


# ── 数据模型 ──
@dataclass(frozen=True, slots=True)
class SectorInfo:
    node: str
    name: str
    board_type: Literal["concept", "industry"]
    stock_count: int
    leader_code: str
    leader_name: str


@dataclass
class StockSectorPosition:
    """个股在单个板块内的定位。"""

    sector_node: str
    sector_name: str
    board_type: Literal["concept", "industry"]
    rank: int
    total: int
    changepercent: float
    mktcap: float | None
    turnoverratio: float | None
    # 量化判断
    position_tag: str = ""  # 日内龙头/前排强势/中军/趋势/跟风/弱势
    position_reason: str = ""


@dataclass
class StockPositioningResult:
    """个股综合定位结果。"""

    stock_code: str
    up_position: str = ""  # UP知识库中的标注
    up_position_source: str = ""
    sector_positions: list[StockSectorPosition] = field(default_factory=list)
    # 综合判断（优先UP标注，其次量化判断）
    final_position: str = ""
    final_reason: str = ""


# ── HTTP 工具 ──
_HTTP_RETRY_COUNT = 3
_HTTP_RETRY_BACKOFF_BASE = 5.0  # 5s, 10s, 20s 退避


def _http_get(
    url: str, timeout: float = 30.0, encoding: str = "utf-8", retries: int = _HTTP_RETRY_COUNT,
) -> str:
    global _last_request_time
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            # 频率限制保护
            elapsed = time.time() - _last_request_time
            if elapsed < _REQUEST_DELAY:
                time.sleep(_REQUEST_DELAY - elapsed)
            _last_request_time = time.time()

            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                # 新浪接口多为 GBK
                if encoding == "auto":
                    for enc in ("gbk", "gb2312", "utf-8"):
                        try:
                            return raw.decode(enc, errors="ignore")
                        except Exception:
                            continue
                    return raw.decode("utf-8", errors="ignore")
                return raw.decode(encoding, errors="ignore")
        except Exception as e:
            last_err = e
            if attempt < retries:
                wait = _HTTP_RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
                print(f"  [RETRY] {url[:80]}... attempt {attempt} failed ({e}), waiting {wait}s")
                time.sleep(wait)
    raise last_err  # type: ignore[misc]


def _http_get_json(url: str, timeout: float = 10.0) -> list | dict:
    text = _http_get(url, timeout=timeout, encoding="auto")
    return json.loads(text)


# ── 板块列表 ──
def fetch_sina_sector_list(
    board_type: Literal["concept", "industry"] = "concept",
) -> list[SectorInfo]:
    """从新浪获取板块列表。"""
    url = _SINA_BOARD_LIST_URL[board_type]
    text = _http_get(url, encoding="auto")

    # 提取 JSON
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return []

    data = json.loads(text[start : end + 1])
    results: list[SectorInfo] = []
    for node, value in data.items():
        parts = value.split(",")
        if len(parts) < 9:
            continue
        results.append(
            SectorInfo(
                node=node,
                name=parts[1],
                board_type=board_type,
                stock_count=int(parts[2]) if parts[2].isdigit() else 0,
                leader_code=parts[8].replace("sh", "").replace("sz", ""),
                leader_name=parts[13] if len(parts) > 13 else "",
            )
        )
    return results


# ── 板块成分股 ──
def fetch_sector_constituents(
    sector_node: str,
    page_size: int = 500,
    timeout: float = 10.0,
) -> list[dict]:
    """获取板块内所有成分股，按涨幅降序排列。

    返回字段: code, name, changepercent, mktcap, turnoverratio, trade, volume, amount...
    """
    cache_key = f"{sector_node}:{page_size}"
    now = time.time()
    if cache_key in _constituents_cache:
        cached, ts = _constituents_cache[cache_key]
        if now - ts < _CONSTITUENTS_CACHE_TTL:
            return cached

    url = _SINA_CONSTITUENTS_URL.format(node=sector_node, page_size=page_size)
    try:
        items = _http_get_json(url, timeout=timeout)
    except Exception:
        return []

    if not isinstance(items, list):
        return []

    # 统一 code 格式（纯数字）
    for item in items:
        code = item.get("code", "")
        if code:
            item["code"] = code.replace("sh", "").replace("sz", "").replace(".", "")

    _constituents_cache[cache_key] = (items, now)
    return items


# ── 个股→板块映射缓存 ──
def _load_mapping_cache() -> dict[str, list[dict]]:
    """加载本地映射缓存，如果过期返回空。"""
    if not _CACHE_FILE.exists():
        return {}
    try:
        data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        ts = data.get("_built_at", 0)
        if time.time() - ts > _CACHE_TTL_SECONDS:
            return {}  # 过期
        return data.get("mapping", {})
    except Exception:
        return {}


def _save_mapping_cache(mapping: dict[str, list[dict]]) -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"_built_at": time.time(), "mapping": mapping}
    _CACHE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_stock_sector_mapping(
    max_sectors: int | None = None,
    progress_callback: callable | None = None,
    save_cache: bool = True,
) -> dict[str, list[dict]]:
    """全量建立个股→板块映射。

    遍历所有板块，获取成分股，反向建立映射。
    概念+行业约259个板块，全量请求约需6-10分钟（含1.5秒间隔）。

    Args:
        max_sectors: 限制处理的板块数量（用于测试，会覆盖全量缓存！）
        progress_callback: (current, total, sector_name) -> None
        save_cache: 是否写入本地缓存文件（测试时设为 False）
    """
    sectors: list[SectorInfo] = []
    for bt in ("concept", "industry"):
        try:
            sectors.extend(fetch_sina_sector_list(bt))
        except Exception:
            continue

    if max_sectors:
        sectors = sectors[:max_sectors]

    mapping: dict[str, list[dict]] = {}
    total = len(sectors)
    failed_sectors: list[str] = []

    for idx, sector in enumerate(sectors, 1):
        if progress_callback:
            progress_callback(idx, total, sector.name)
        try:
            constituents = fetch_sector_constituents(sector.node, page_size=500)
            if not constituents:
                failed_sectors.append(sector.name)
                continue
            for item in constituents:
                code = item.get("code", "")
                if not code:
                    continue
                if code not in mapping:
                    mapping[code] = []
                mapping[code].append({
                    "node": sector.node,
                    "name": sector.name,
                    "board_type": sector.board_type,
                    "leader_code": sector.leader_code,
                })
        except Exception:
            failed_sectors.append(sector.name)
            continue

    if save_cache:
        _save_mapping_cache(mapping)
    if failed_sectors:
        print(f"[WARN] {len(failed_sectors)} 个板块获取失败: {failed_sectors[:5]}...")
    return mapping


def get_stock_sectors(code: str, max_lookup_sectors: int = 20) -> list[dict]:
    """获取个股所属板块列表（多接口降级）。

    降级顺序：
    1. 本地缓存（O(1)，首选）
    2. 快速反查：遍历最热门的 N 个板块（用于缓存未命中时的应急）
    3. 返回空列表

    注意：全量映射缓存建议通过 `build_stock_sector_mapping()` 定时重建，
    实时反查只适合应急，且受新浪频率限制（每个板块请求间隔 1.5 秒）。
    """
    pure_code = code.replace("sh", "").replace("sz", "").replace(".", "")

    # 1. 本地缓存（O(1)）
    cache = _load_mapping_cache()
    if pure_code in cache:
        return cache[pure_code]

    # 2. 快速反查：只遍历最热门的板块（限制请求量，避免超时）
    try:
        all_sectors = []
        for bt in ("concept", "industry"):
            all_sectors.extend(fetch_sina_sector_list(bt))
        # 按股票数排序，优先大板块（更可能包含目标个股）
        all_sectors.sort(key=lambda s: s.stock_count, reverse=True)
        found: list[dict] = []
        for sector in all_sectors[:max_lookup_sectors]:
            try:
                constituents = fetch_sector_constituents(sector.node, page_size=200)
                for item in constituents:
                    if item.get("code") == pure_code:
                        found.append({
                            "node": sector.node,
                            "name": sector.name,
                            "board_type": sector.board_type,
                            "leader_code": sector.leader_code,
                        })
                        break
            except Exception:
                continue
        return found
    except Exception:
        return []


# ── 板块内排名与地位判断 ──
def get_stock_rank_in_sector(
    code: str,
    sector_node: str,
) -> StockSectorPosition | None:
    """获取个股在指定板块内的排名和量化地位。"""
    pure_code = code.replace("sh", "").replace("sz", "").replace(".", "")
    constituents = fetch_sector_constituents(sector_node, page_size=500)
    if not constituents:
        return None

    # 找到目标个股
    target = None
    for item in constituents:
        if item.get("code") == pure_code:
            target = item
            break

    if not target:
        return None

    # 计算排名
    total = len(constituents)
    rank = 0
    for idx, item in enumerate(constituents, 1):
        if item.get("code") == pure_code:
            rank = idx
            break

    changepercent = float(target.get("changepercent", 0) or 0)
    mktcap = float(target.get("mktcap", 0) or 0)
    turnoverratio = float(target.get("turnoverratio", 0) or 0)

    # 量化地位判断（基于UP定义 + 实时数据）
    position_tag, position_reason = _classify_position(
        rank=rank,
        total=total,
        changepercent=changepercent,
        mktcap=mktcap,
        turnoverratio=turnoverratio,
    )

    # 获取板块名称
    sector_name = sector_node
    for bt in ("concept", "industry"):
        try:
            for s in fetch_sina_sector_list(bt):
                if s.node == sector_node:
                    sector_name = s.name
                    break
        except Exception:
            continue

    return StockSectorPosition(
        sector_node=sector_node,
        sector_name=sector_name,
        board_type="concept",  # 简化，实际应从 sector_node 前缀推断
        rank=rank,
        total=total,
        changepercent=changepercent,
        mktcap=mktcap if mktcap > 0 else None,
        turnoverratio=turnoverratio if turnoverratio > 0 else None,
        position_tag=position_tag,
        position_reason=position_reason,
    )


def _classify_position(
    rank: int,
    total: int,
    changepercent: float,
    mktcap: float,
    turnoverratio: float | None,
) -> tuple[str, str]:
    """根据实时数据量化判断个股地位。

    基于UP对中军/趋势/龙头/情绪载体的定义：
    - 龙头/情绪载体：小市值+连板+高换手+日内涨幅最高
    - 中军：大市值(500亿+)+机构主导+走势稳定+板块辨识度最高
    - 趋势：大市值(300亿+)+独立趋势+非连板+均线缓慢上行
    - 跟风：排名靠后+涨幅低+无独立逻辑
    """
    mktcap = mktcap or 0
    turnover = turnoverratio or 0
    ratio = rank / total if total > 0 else 1.0

    # 龙头判定（日内最强）
    if rank <= 3 and changepercent >= 5.0:
        return (
            "日内龙头",
            f"板块内排名第{rank}/{total}，涨幅{changepercent:.2f}%，日内最强标的之一",
        )

    # 前排强势
    if rank <= 5 and changepercent >= 3.0:
        return (
            "前排强势",
            f"板块内排名第{rank}/{total}，涨幅{changepercent:.2f}%，处于板块前排",
        )

    # 中军判定（大市值+稳定+板块核心）
    if mktcap >= 500_0000:  # 500亿（新浪mktcap单位是万）
        if ratio <= 0.3 and changepercent > 0:
            return (
                "中军/板块稳定器",
                f"市值{mktcap/10000:.0f}亿，板块内排名前{ratio*100:.0f}%，"
                f"涨幅{changepercent:.2f}%，大市值机构票，起到板块稳定作用",
            )

    # 趋势判定（大市值+趋势上行+非游资）
    if mktcap >= 300_0000:  # 300亿
        if changepercent > 0 and turnover < 8.0:
            return (
                "趋势/趋势容量票",
                f"市值{mktcap/10000:.0f}亿，涨幅{changepercent:.2f}%，"
                f"换手{turnover:.2f}%（非爆量），走趋势而非连板",
            )

    # 跟风
    if ratio > 0.5 and changepercent > 0:
        return (
            "跟风",
            f"板块内排名{rank}/{total}（后50%），涨幅{changepercent:.2f}%，"
            "无独立领涨逻辑，跟随板块情绪",
        )

    # 弱势
    if changepercent <= 0:
        return (
            "弱势",
            f"板块内排名{rank}/{total}，涨幅{changepercent:.2f}%（下跌或平盘），"
            "跑输板块",
        )

    # 默认
    return (
        "中性",
        f"板块内排名{rank}/{total}，涨幅{changepercent:.2f}%，"
        f"市值{mktcap/10000:.0f}亿",
    )


# ── 综合定位 API ──
def get_stock_positioning(
    code: str,
    up_position: str = "",
    up_position_source: str = "",
) -> StockPositioningResult:
    """三层定位法：获取个股综合定位。

    第一层：UP知识库定位（最可靠，如果存在）
    第二层：板块排名定位（实时验证）
    第三层：综合判断
    """
    result = StockPositioningResult(
        stock_code=code,
        up_position=up_position,
        up_position_source=up_position_source,
    )

    # 第二层：获取板块内排名
    sectors = get_stock_sectors(code)
    sector_positions: list[StockSectorPosition] = []

    for sector in sectors[:3]:  # 最多取前3个关联板块
        pos = get_stock_rank_in_sector(code, sector["node"])
        if pos:
            sector_positions.append(pos)

    result.sector_positions = sector_positions

    # 第三层：综合判断
    if up_position:
        # UP有标注 → 优先使用，但用实时数据验证
        if sector_positions:
            best = sector_positions[0]
            result.final_position = up_position
            result.final_reason = (
                f"【UP定位】{up_position}"
                f"（来源：{up_position_source}）\n"
                f"【实时验证】在{best.sector_name}板块内排名"
                f"{best.rank}/{best.total}，涨幅{best.changepercent:.2f}%，"
                f"量化标签：{best.position_tag}"
            )
        else:
            result.final_position = up_position
            result.final_reason = (
                f"【UP定位】{up_position}"
                f"（来源：{up_position_source}）\n"
                f"【实时验证】无法获取板块排名数据，UP定位为唯一参考"
            )
    else:
        # UP无标注 → 完全依赖量化判断
        if sector_positions:
            best = sector_positions[0]
            result.final_position = best.position_tag
            result.final_reason = (
                f"【无UP标注】基于{best.sector_name}板块实时数据判断：\n"
                f"排名{best.rank}/{best.total}，涨幅{best.changepercent:.2f}%，"
                f"{best.position_reason}"
            )
        else:
            result.final_position = "未知"
            result.final_reason = "无法获取UP标注，也无法获取板块排名数据"

    return result


def to_agent_format(result: StockPositioningResult) -> dict:
    """转换为 agent 可用的字典格式。"""
    return {
        "stock_code": result.stock_code,
        "up_position": result.up_position,
        "up_position_source": result.up_position_source,
        "final_position": result.final_position,
        "final_reason": result.final_reason,
        "sector_details": [
            {
                "sector_name": p.sector_name,
                "board_type": p.board_type,
                "rank": f"{p.rank}/{p.total}",
                "changepercent": p.changepercent,
                "mktcap": round(p.mktcap / 10000, 2) if p.mktcap else None,
                "turnoverratio": p.turnoverratio,
                "position_tag": p.position_tag,
                "position_reason": p.position_reason,
            }
            for p in result.sector_positions
        ],
    }
