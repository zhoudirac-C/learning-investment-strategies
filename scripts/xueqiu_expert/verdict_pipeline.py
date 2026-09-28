#!/usr/bin/env python3
"""雪球大牛回测 P4+P5：命中判定与评分管线。

设计：docs/design/xueqiu-expert-backtest-design.md §4.4（2026-09-24 拍板 B/B/A）
  B① 判定文本 = 抓全文再判（www.xueqiu.com 帖子页匿名可抓，article__bd__detail）
  B② 相关性 = 板块关键词/持股映射硬层 + LLM 行业标签兜底（保召回）
  A③ 36 个高产用户缺老帖本轮接受（verdicts 可重算）

LLM 兜底链（2026-09-24 用户拍板）：
  workbuddy deepseek-v4.1-flash → glm-5.3-flash → deepseek-v4-flash
  → OpenRouter 免费模型（运行时读 ~/.hermes/config.yaml fallback_providers，
    由 cron 每 2h 探活刷新）→ sensenova（.env）
  每次调用从主模型开始尝试：429/5xx 快速失败切下一个，主通道恢复自动回切。
  任务为一次性批量，结束后无需恢复任何全局配置。

用法：
  python verdict_pipeline.py --select-only           # 只跑候选帖选择（纯函数+LLM标签兜底）
  python verdict_pipeline.py --fetch-only            # 只抓全文快照（断点续跑）
  python verdict_pipeline.py --judge-only            # 只跑 LLM 判定（断点续跑）
  python verdict_pipeline.py --judge-only --redo-judge --concurrency 6  # 归档旧判定并并发重判
  python verdict_pipeline.py                         # 全流程 select → tag → fetch → judge
  python verdict_pipeline.py --rank                  # P5：读 verdicts/ 评 TOP20
  python verdict_pipeline.py --sample-review         # 生成 TOP20+中腰部人工复核清单
  python verdict_pipeline.py --limit 3 --uid 123     # 试跑
产出：
  data/xueqiu/candidates_posts.json     # 窗口内候选帖（含命中板块与来源层）
  data/xueqiu/verdicts/{uid}.json       # 每人命中明细
  data/xueqiu/verdicts/_sample_review.json
  data/xueqiu/expert_acceptance_review.md
  data/xueqiu/expert_ranking.json       # P5 TOP20
  sources/raw/xueqiu/{date}-{uid}-{id}.md   # 命中帖全文快照
  logs/llm_calls_p4.jsonl               # LLM 调用落账
"""
from __future__ import annotations

import argparse
import html as html_mod
import json
import random
import re
import subprocess
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

DATA = REPO / "data" / "xueqiu"
POSTS_DIR = DATA / "posts"
VERDICTS_DIR = DATA / "verdicts"
SNAP_DIR = REPO / "sources" / "raw" / "xueqiu"
CAND_OUT = DATA / "candidates_posts.json"
RANKING_OUT = DATA / "expert_ranking.json"
REVIEW_MD_OUT = DATA / "expert_acceptance_review.md"
LLM_LOG = REPO / "logs" / "llm_calls_p4.jsonl"
_LLM_LOG_LOCK = threading.Lock()
SAMPLE_TOP_N = 20
SAMPLE_MID_N = 10
SAMPLE_SEED = 20260927
JUDGE_PROMPT_VERSION = "2026-09-28-strict2"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36")
FETCH_SLEEP = 2.0          # www 域匿名详情页限速（实测连发 4-5 次后出现 987B 存根）
FETCH_RETRIES = 4          # 存根呈突发性：5s/10s/15s 退避重试
WAF_SLEEP = 60
MISS_COOLDOWN = 60         # 连续 2 次抓取失败 → 冷却，等限流窗口过去
LLM_BATCH = 15             # LLM 标签兜底：每批帖子数
JUDGE_SLEEP = 0.4
STOCK_RE = re.compile(r"(?<![0-9])(?:SZ|SH|BJ)?(\d{6})(?![0-9])")
RISK_TAIL_RE = re.compile(r"风险提示：用户发表的所有文章.*$", re.S)
SOURCE_LINE_RE = re.compile(r"^来源：雪球App[^）]*）", re.S)

WORKBUDDY_CHAIN = [
    # 2026-09-24 用户拍板：主模型切 glm-5.3-flash（全局默认一致），deepseek 系降为兜底
    "workbuddy:glm-5.3-flash",
    "workbuddy:deepseek-v4.1-flash",
    "workbuddy:deepseek-v4-flash",
    "workbuddy:deepseek-v4-pro",
]


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ============================ 纯函数层 ============================


def parse_post_date(value) -> date | None:
    """created_at(ms epoch) / 'YYYY-MM-DD[ ...]' → 本地日期。"""
    if isinstance(value, (int, float)) and value > 0:
        return datetime.fromtimestamp(value / 1000).date()
    if isinstance(value, str) and value:
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", value)
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def is_original(post: dict) -> bool:
    """原创帖：非转发，且非回复（P3 实测回复帖 description 以'回复'开头）。"""
    if post.get("retweet"):
        return False
    desc = (post.get("description") or "").lstrip()
    return not desc.startswith("回复")


def build_event_index(events: list[dict]) -> dict[str, list[dict]]:
    idx: dict[str, list[dict]] = {}
    for e in events:
        idx.setdefault(e["sector"], []).append(e)
    for v in idx.values():
        v.sort(key=lambda e: e["launch_date"])
    return idx


def find_window_hits(event_index: dict, sector: str, post_day: date) -> list[dict]:
    """帖日期 vs 该板块启动事件：提前 3~21 天为窗口（强=7~21 / 中=3~6）。"""
    out = []
    for e in event_index.get(sector, []):
        launch = parse_post_date(e["launch_date"])
        if launch is None:
            continue
        lead = (launch - post_day).days
        if 3 <= lead <= 21:
            out.append({
                "sector": sector,
                "launch_date": e["launch_date"],
                "lead_days": lead,
                "tier": "strong" if lead >= 7 else "mid",
                "max_gain_20d": e.get("max_gain_20d"),
            })
    return out


def extract_stock_mentions(text: str) -> set[str]:
    """$代码$、SZ/SH/BJ 前缀码、裸 6 位码 → 集合（防日期/长数字误提）。"""
    return set(STOCK_RE.findall(text or ""))


def stock_to_sectors(mapping: dict) -> dict[str, set[str]]:
    """stock_sector_mapping.json → {code: {板块名}}。"""
    out: dict[str, set[str]] = {}
    for code, boards in (mapping or {}).items():
        if code.startswith("_"):
            continue
        names = {b.get("name", "") for b in boards or [] if b.get("name")}
        if names:
            out[str(code)] = names
    return out


def keyword_hit_sectors(text: str, sectors) -> set[str]:
    """板块名硬匹配：全文包含 或 板块的≥2字子串出现在文中（双向，宁多召回）。
    单字板块名跳过（防误召回，测试口径）。"""
    text = text or ""
    hits = set()
    for sec in sectors:
        if len(sec) < 2:
            continue
        if sec in text:
            hits.add(sec)
            continue
        found = False
        for i in range(len(sec)):
            for j in range(i + 2, len(sec) + 1):
                if sec[i:j] in text:
                    found = True
                    break
            if found:
                break
        if found:
            hits.add(sec)
    return hits


def parse_llm_json(raw: str) -> dict | None:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    # glm-5.3-flash 偶尔先推理后给 JSON：提取第一个平衡大括号对象。
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    data = json.loads(text[start:i + 1])
                    return data if isinstance(data, dict) else None
                except json.JSONDecodeError:
                    return None
    return None


POSITIVE_HIT_RE = re.compile(
    r"看好|看涨|买入|买够|买了|加仓|加到|建仓|布局|追高|换了一些|二次拉升|不确定性消除|推荐|受益|受益更明显|"
    r"超预期|中标|目标价|龙头已定|跨年龙头|一哥|刚刚开始|核心主线|贝塔行情|景气|上修|产能|订单覆盖|订单已覆盖|"
    r"需求没有转弱|长牛|底部区域|买点|接单|抄底|看多|做多|资本开支|投资约|投入|扩建|建设人工智能数据中心|"
    r"信仰|便宜|没有最高|出货量第一|预期很好|刚需|紧缺|基本面没啥问题|打破海外垄断|应用于|市占率|"
    r"合同负债|存货大幅增长|进入十大股东|协同效应|替代概念|产能指引|财务自由|起来了|应当涨|在涨|算力！|翻了好几倍|风投仓|预期足够低|长期持有")
NEGATIVE_HINT_RE = re.compile(
    r"自然寻底|等企稳|弱转强|壮胆|盲猜|拉涨停|登基|王爷|亏麻|无力回天|边际向差|"
    r"指数编制|分红率|派息率|股利支付率|中证红利|嘉年华|访谈|对话|活动预告")


def hit_postfilter_ok(rec: dict, sector: str) -> bool:
    """LLM 判定后的确定性降噪：宁可漏不可错。

    规则来源：2026-09-28 strict2 抽样误差（无快照、短句情绪、科普/名单罗列、
    指数/分红规则解释、谨慎跟踪话术）。只在 LLM 已判 bullish 后调用。
    """
    snap = (rec or {}).get("snapshot") or ""
    if not snap:
        return False
    sp = SNAP_DIR / snap
    if not sp.exists():
        return False
    text = sp.read_text(errors="replace")[:4000]
    if not text.strip():
        return False
    # 强负向/规则解释话术一票否决（即使后文有零散正向词）。
    if re.search(r"亏麻|无力回天|边际向差|自然寻底|等企稳|弱转强|指数编制|中证红利|分红率|股利支付率", text):
        return False
    # 纯名单罗列（大量顿号且没有投资动作/结论）不纳入。
    if text.count("、") >= 12 and not POSITIVE_HIT_RE.search(text):
        return False
    # 明确负向/谨慎/规则解释话术，且无正向动作结论 → 不纳入。
    if NEGATIVE_HINT_RE.search(text) and not POSITIVE_HIT_RE.search(text):
        return False
    # 必须至少有正向投资信号；纯讨论/摘录/感叹不纳入。
    return bool(POSITIVE_HIT_RE.search(text))


def score_expert(hits: list[dict], total_original_posts: int) -> dict:
    """设计 §4.4：眼力=强×3+中×1；持续力=命中跨板块数；密度=命中/总原创帖；
    综合=眼力×0.5+持续力×0.3+密度×0.2。"""
    strong = sum(1 for h in hits if h.get("tier") == "strong")
    mid = sum(1 for h in hits if h.get("tier") == "mid")
    eye = strong * 3 + mid
    persist = len({h.get("sector") for h in hits if h.get("sector")})
    density = (len(hits) / total_original_posts) if total_original_posts else 0.0
    composite = eye * 0.5 + persist * 0.3 + density * 0.2
    return {"eye_score": eye, "strong": strong, "mid": mid, "persist": persist,
            "density": round(density, 6), "composite": round(composite, 6)}


def rank_all(verdicts: list[dict], top_n: int = 20) -> list[dict]:
    """P5：verdicts 文档列表 → 综合分排序 TOP N。"""
    rows = []
    for v in verdicts:
        s = score_expert(v.get("hits", []), v.get("original_total", 0))
        rows.append({**{k: v.get(k) for k in ("uid", "screen_name", "source")},
                     "posts_total": v.get("posts_total", 0),
                     "original_total": v.get("original_total", 0),
                     "coverage_note": v.get("coverage_note", ""),
                     "hits": v.get("hits", []), **s})
    rows.sort(key=lambda r: r["composite"], reverse=True)
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows[:top_n]


# ============================ LLM 层 ============================
# 兜底链（2026-09-24 用户拍板）：workbuddy 便宜档 → deepseek-v4-pro →
# OpenRouter 免费模型（运行时读 ~/.hermes/config.yaml fallback_providers，
# cron 每 2h 探活刷新）→ sensenova（项目 .env）。
# 每次调用从主模型开始尝试：429/5xx 快速失败切下一个，主通道恢复自动回切。


def _load_env_file(path: Path) -> dict:
    out = {}
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def _env_get(key: str, envs: list[dict]) -> str | None:
    import os
    return os.environ.get(key) or next(
        (e[key] for e in envs if e.get(key)), None)


def build_chain_specs() -> list[dict]:
    """[{model, base_url, api_key, label}]——ChainClient 逐个尝试。"""
    envs = [_load_env_file(Path.home() / ".hermes" / ".env"),
            _load_env_file(REPO / ".env")]
    specs: list[dict] = []

    def add(model: str, base_url, api_key, label: str) -> None:
        if base_url and api_key:
            specs.append({"model": model, "base_url": base_url,
                          "api_key": api_key, "label": label})

    # 1. workbuddy（本地代理 8317）：三便宜档 + pro 质量兜底
    wb_base = _env_get("CUSTOM_WORKBUDDY_BASE_URL", envs) or "http://127.0.0.1:8317/v1"
    wb_key = _env_get("CUSTOM_WORKBUDDY_API_KEY", envs)
    for m in WORKBUDDY_CHAIN:
        add(m.split(":", 1)[1], wb_base, wb_key, m)

    # 2. OpenRouter 免费模型（config.yaml fallback_providers，探活排序即最新）
    try:
        import yaml
        cfg = yaml.safe_load((Path.home() / ".hermes" / "config.yaml").read_text())
        or_base = _env_get("CUSTOM_NEX_N25_BASE_URL", envs) or "https://openrouter.ai/api/v1"
        or_key = _env_get("CUSTOM_NEX_N25_API_KEY", envs) or _env_get("OPENROUTER_API_KEY", envs)
        for fb in cfg.get("fallback_providers") or []:
            if fb.get("provider") == "custom_nex-n25" and fb.get("model"):
                add(fb["model"], or_base, or_key, f"nex-n25:{fb['model']}")
    except Exception as e:  # noqa: BLE001
        log(f"⚠️ fallback_providers 读取失败（跳过 OpenRouter 兜底）: {e}")

    # 3. sensenova 末级兜底（项目 .env）
    sn_key = _env_get("SENSENOVA_API_KEY", envs)
    for m in ("deepseek-v4-flash", "glm-5.2"):
        add(m, "https://token.sensenova.cn/v1", sn_key, f"sensenova:{m}")

    return specs


class ChainClient:
    """逐个尝试的 LLM 客户端链：invoke 语义与 FallbackChatOpenAI 兼容。"""

    def __init__(self, specs: list[dict]):
        self.specs = specs
        self._clients: dict[int, Any] = {}
        self.model_name = specs[0]["model"] if specs else "chain(empty)"

    def _client(self, idx: int):
        if idx not in self._clients:
            from openai import OpenAI
            s = self.specs[idx]
            self._clients[idx] = OpenAI(api_key=s["api_key"], base_url=s["base_url"],
                                        timeout=120, max_retries=0)
        return self._clients[idx]

    def invoke(self, prompt: str, max_tokens: int = 2000, **_):
        last_err: Exception | None = None
        for idx, s in enumerate(self.specs):
            try:
                resp = self._client(idx).chat.completions.create(
                    model=s["model"],
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2, max_tokens=max_tokens)
                content = resp.choices[0].message.content or ""
                if content.strip():
                    self.model_name = s["model"]
                    return type("R", (), {"content": content})()
                last_err = RuntimeError(f"{s['label']}: 空响应")
            except Exception as e:  # noqa: BLE001
                last_err = e
        raise RuntimeError(f"全链失败（{len(self.specs)} 个通道）: {last_err}")


def make_llm_client() -> ChainClient:
    specs = build_chain_specs()
    log("LLM 兜底链: " + " → ".join(s["label"] for s in specs))
    return ChainClient(specs)


def _llm_log(record: dict) -> None:
    LLM_LOG.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"ts": datetime.now().isoformat(timespec="seconds"),
                       **record}, ensure_ascii=False) + "\n"
    with _LLM_LOG_LOCK:
        with LLM_LOG.open("a") as f:
            f.write(line)


def call_llm(client, prompt: str, *, kind: str, max_tokens: int = 2000,
             attempts: int = 3) -> str | None:
    """invoke 全链 → 失败整体重试（15s 退避）；落账。"""
    for attempt in range(1, attempts + 1):
        t0 = time.time()
        model = getattr(client, "model_name", "unknown")
        try:
            resp = client.invoke(prompt, max_tokens=max_tokens)
            content = resp.content if hasattr(resp, "content") else str(resp)
            _llm_log({"kind": kind, "model": model, "ok": True,
                      "latency_ms": int((time.time() - t0) * 1000),
                      "attempt": attempt, "chars": len(prompt)})
            return content
        except Exception as e:  # noqa: BLE001
            _llm_log({"kind": kind, "model": model, "ok": False,
                      "latency_ms": int((time.time() - t0) * 1000),
                      "attempt": attempt, "err": str(e)[:200]})
            if attempt < attempts:
                time.sleep(15)
    return None


# ============================ 抓取层 ============================


def _extract_detail(raw: str) -> str | None:
    """article__bd__detail div 正文（标签平衡法，容嵌套 div）。"""
    m = re.search(r'<div class="article__bd__detail">', raw)
    if not m:
        return None
    body_start = m.end()
    depth = 1
    end = None
    for tag in re.finditer(r"<div\b|</div>", raw[body_start:body_start + 120000]):
        if tag.group(0).startswith("<div"):
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                end = body_start + tag.start()
                break
    if end is None:
        return None
    txt = re.sub(r"<[^>]+>", " ", raw[body_start:end])
    txt = html_mod.unescape(re.sub(r"\s+", " ", txt)).strip()
    txt = SOURCE_LINE_RE.sub("", txt)
    txt = RISK_TAIL_RE.sub("", txt).strip()
    return txt or None


def fetch_full_text(target: str) -> str | None:
    """www.xueqiu.com/<uid>/<id> 详情页 → 正文纯文本。

    2026-09-24 实测：匿名可抓但存根突发（连发 4-5 次后 987B 短响应），
    退避重试可恢复；detail div 有嵌套，须标签平衡法提取。"""
    url = "https://www.xueqiu.com" + target
    for attempt in range(1, FETCH_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA, "Referer": "https://www.xueqiu.com/"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            raw = ""
        if raw and "aliyun_waf" not in raw[:2000]:
            txt = _extract_detail(raw)
            if txt:
                return txt
        if attempt < FETCH_RETRIES:
            time.sleep(WAF_SLEEP if "aliyun_waf" in raw[:2000] else 5 * attempt)
    return None


def snapshot_path(target: str, day: str) -> Path:
    status_id = target.rstrip("/").split("/")[-1]
    return SNAP_DIR / f"{day}-{status_id}.md"


# ============================ 管线步骤 ============================


def load_inputs() -> tuple[dict, dict]:
    launches = json.loads((DATA / "sector_launches.json").read_text())
    events = launches if isinstance(launches, list) else (
        launches.get("launches") or launches.get("events"))
    mapping = json.loads(
        (REPO / "config" / "stock_monitor" / "stock_sector_mapping.json").read_text())
    return build_event_index(events), mapping


def iter_user_posts():
    """[(uid, screen_name, source, post)]，按 uid 遍历 posts/*.json。"""
    for f in sorted(POSTS_DIR.glob("*.json")):
        d = json.loads(f.read_text())
        if "uid" not in d:
            continue
        for p in d.get("posts", []):
            yield str(d["uid"]), d.get("screen_name", ""), d.get("source", ""), p


def step_select(client) -> list[dict]:
    """候选帖选择：原创 + 窗口相关（关键词硬层 / 持股映射 / LLM 标签兜底）。"""
    event_index, mapping = load_inputs()
    s2s = stock_to_sectors(mapping.get("mapping", mapping))
    all_sectors = set(event_index.keys())
    # 日期 → 当日处于窗口的板块（快速预筛）
    date_sectors: dict[date, set[str]] = {}
    for sec in event_index:
        for e in event_index[sec]:
            launch = parse_post_date(e["launch_date"])
            if launch is None:
                continue
            for off in range(3, 22):
                date_sectors.setdefault(launch - timedelta(days=off), set()).add(sec)

    candidates: list[dict] = []
    tag_needed: list[dict] = []
    n_orig = n_inwin = 0
    for uid, name, source, p in iter_user_posts():
        if not is_original(p):
            continue
        n_orig += 1
        day = parse_post_date(p.get("created_at") or p.get("date"))
        if day is None or day not in date_sectors:
            continue
        n_inwin += 1
        text = (p.get("title") or "") + " " + (p.get("description") or "")
        window_secs = date_sectors[day]
        # 硬层 1：板块名关键词（∩ 当日窗口板块）
        hit_secs = keyword_hit_sectors(text, window_secs)
        src_layer = "keyword" if hit_secs else ""
        # 硬层 2：股票提及 → 板块
        mention_secs = set()
        for code in extract_stock_mentions(text):
            mention_secs |= s2s.get(code, set())
        mention_secs &= window_secs
        if mention_secs:
            src_layer = (src_layer + "+stock").strip("+")
            hit_secs |= mention_secs
        item = {"uid": uid, "screen_name": name, "source": source,
                "target": p.get("target"), "date": day.isoformat(),
                "title": p.get("title") or "", "description": p.get("description") or "",
                "sectors": sorted(hit_secs), "match_layer": src_layer or "llm_tag",
                "judged_on": "full"}
        if hit_secs:
            candidates.append(item)
        else:
            tag_needed.append(item)

    log(f"原创帖 {n_orig}，窗口内 {n_inwin}，硬层命中 {len(candidates)}，待 LLM 标签兜底 {len(tag_needed)}")

    # 兜底层：LLM 批量抽行业标签（决策 B：保召回）
    if client is not None and tag_needed:
        sector_list = "\n".join(sorted(all_sectors))
        done = 0
        for i in range(0, len(tag_needed), LLM_BATCH):
            batch = tag_needed[i:i + LLM_BATCH]
            lines = "\n".join(
                f"{j}. [{b['date']}] {(b['title'] + ' ' + b['description'])[:160]}"
                for j, b in enumerate(batch))
            prompt = (
                "以下每条是雪球用户帖子的开头片段。只允许给“明确讨论”的候选板块打标签：\n"
                "1) 精确出现候选板块名，或无歧义的核心产业链/核心标的；\n"
                "2) 禁止把泛AI/泛科技/泛制造/泛资源/国产替代/趋势方法论/指数研究映射到窄板块；\n"
                "3) 个股只有在帖子围绕其基本面/订单/景气/政策且该股是板块核心代表时才可映射；\n"
                "4) 拿不准一律空数组，宁可漏不可错。\n"
                f"候选板块清单：\n{sector_list}\n\n帖子：\n{lines}\n\n"
                '只输出 JSON：{"items": [{"i": 0, "sectors": ["板块名"]}]}')
            raw = call_llm(client, prompt, kind="tag")
            data = parse_llm_json(raw) if raw else None
            if data and isinstance(data.get("items"), list):
                for it in data["items"]:
                    try:
                        b = batch[int(it["i"])]
                    except (KeyError, ValueError, IndexError):
                        continue
                    tags = [t for t in (it.get("sectors") or [])
                            if isinstance(t, str) and t in all_sectors]
                    if tags:
                        b["sectors"] = sorted(set(b["sectors"]) | set(tags))
                        candidates.append(b)
                done += len(batch)
                log(f"LLM 标签兜底进度 {done}/{len(tag_needed)}")
            else:
                log(f"⚠️ 标签批次失败（{i}~{i+len(batch)}），跳过")
            time.sleep(JUDGE_SLEEP)

    CAND_OUT.write_text(json.dumps(candidates, ensure_ascii=False, indent=1))
    n_llm = sum(1 for c in candidates if c["match_layer"] == "llm_tag")
    log(f"候选帖落盘 {len(candidates)} 条（硬层 {len(candidates)-n_llm} / LLM兜底 {n_llm}）→ {CAND_OUT.name}")
    return candidates


def step_fetch(candidates: list[dict], limit: int = 0, uid: str | None = None) -> None:
    """全文快照（断点续跑：已有文件跳过）。"""
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    todo = [c for c in candidates
            if (uid is None or c["uid"] == uid) and c.get("target")]
    if limit:
        todo = todo[:limit]
    ok = miss = skip = 0
    consec_miss = 0
    for i, c in enumerate(todo, 1):
        sp = snapshot_path(c["target"], c["date"])
        if sp.exists() and sp.stat().st_size > 50:
            skip += 1
            continue
        txt = fetch_full_text(c["target"])
        if txt:
            sp.write_text(f"# {c['date']} {c['screen_name']}\n\n{txt}\n")
            ok += 1
            consec_miss = 0
        else:
            miss += 1
            consec_miss += 1
            c["judged_on"] = "trunc"  # 抓不到 → 退回 title+description 判定
            if consec_miss >= 2:
                log(f"连续 {consec_miss} 次失败，冷却 {MISS_COOLDOWN}s")
                time.sleep(MISS_COOLDOWN)
        if i % 50 == 0:
            log(f"全文进度 {i}/{len(todo)} (ok {ok} / miss {miss} / skip {skip})")
        time.sleep(FETCH_SLEEP + random.uniform(0, 0.6))
    log(f"全文完成：新增 {ok}，失败 {miss}（回退摘要判定），已有 {skip}")


def build_judge_prompt(candidate: dict, text: str) -> str:
    secs = "、".join(candidate["sectors"])
    return (
        f"以下是雪球用户 {candidate['date']} 的帖子全文。针对板块【{secs}】逐个严格判定。\n"
        "bullish：明确落在该板块本身/核心产业链/核心标的，且有前瞻看多/看好/看涨/买入/加仓/布局/景气向上/明确受益，"
        "或给出定价超预期、出货超预期、中标、产能上修、目标价等明确利好该板块的判断。转发研报但有明确看好结论也算 bullish。\n"
        "若文本只讨论个股，但该股业务/名称明显属于某候选板块（如锂矿股之于能源金属），按该板块表态判断；否则不要硬映射。\n"
        "neutral：只提及事实；泛AI/泛科技/泛制造/泛资源/国产替代/趋势方法论/指数研究；Token工厂/AI工厂/商业模式/护城河/估值方法等科普且无明确看多结论；"
        "会议、访谈、嘉年华、活动预告或单纯转述他人观点；指数/情绪/拥挤度/宏观周报罗列多行业但未单独强调候选板块；政策原文摘录或调侃而无作者投资结论；"
        "个股短句情绪但无明确买入加仓；看多的是别的板块；对个股质疑、相对强弱、兑现讨论；纯风控预案且不给方向；"
        "仅解释高股息/分红率/指数编制规则，或指出分红率超过净利润、不可持续、被指数剔除等，即使股息率高也按 neutral。\n"
        "明确说“大跌就加某板块ETF/标的”属于有方向的买入意向，不按纯风控处理。bearish 仅在明确看空/卖出/提示该板块风险时给出。拿不准一律 neutral。\n"
        "输出要求：第一个字符必须是 {，禁止任何思考、理由、英文、Markdown；只输出一行 JSON。\n"
        "示例：科普“什么是Token工厂”对算力租赁 → {\"stance\":{\"算力租赁\":\"neutral\"}}；"
        "“mate80定价超预期，出货将超预期”对鸿蒙概念 → {\"stance\":{\"鸿蒙概念\":\"bullish\"}}。\n\n"
        f"帖子：\n{text}\n\n"
        '只输出 JSON：{"stance": {"板块名": "bullish|bearish|neutral"}}')


def step_judge(client, candidates: list[dict], limit: int = 0,
               uid: str | None = None, redo: bool = False,
               concurrency: int = 1) -> None:
    """LLM 看多/中性/看空（按帖 × 其候选板块）→ verdicts/{uid}.json。

    可控并发版：每帖判定结果先落 `_judge_records.jsonl`，结束时按 records
    重建 verdicts；中断后不带 --redo-judge 续跑可从 records/progress 恢复。
    """
    VERDICTS_DIR.mkdir(parents=True, exist_ok=True)
    event_index, _ = load_inputs()
    prog_file = VERDICTS_DIR / "_judge_progress.json"
    records_file = VERDICTS_DIR / "_judge_records.jsonl"
    done_targets: set[str] = set()

    if redo:
        archive = VERDICTS_DIR / f"_archive_{datetime.now():%Y%m%d_%H%M%S}"
        old_files = list(VERDICTS_DIR.glob("[0-9]*.json"))
        for f in (records_file, prog_file):
            if f.exists():
                old_files.append(f)
        if old_files:
            archive.mkdir(parents=True, exist_ok=True)
            for f in old_files:
                f.rename(archive / f.name)
        log(f"redo-judge：归档旧判定产物 {len(old_files)} 个 → {archive.name}")
    else:
        if prog_file.exists():
            try:
                done_targets = set(json.loads(prog_file.read_text()))
            except Exception:  # noqa: BLE001
                done_targets = set()
        if records_file.exists():
            for line in records_file.read_text(errors="replace").splitlines():
                try:
                    done_targets.add(json.loads(line)["target"])
                except Exception:  # noqa: BLE001
                    continue
        for f in VERDICTS_DIR.glob("[0-9]*.json"):
            try:
                done_targets |= {h["target"] for h in json.loads(f.read_text()).get("hits", [])}
            except Exception:  # noqa: BLE001
                continue

    todo = [c for c in candidates
            if c.get("sectors") and (uid is None or c["uid"] == uid)
            and c.get("target") and c["target"] not in done_targets]
    if limit:
        todo = todo[:limit]

    stats: dict[str, dict] = {}
    for f in POSTS_DIR.glob("*.json"):
        d = json.loads(f.read_text())
        if "uid" not in d:
            continue
        ps = d.get("posts", [])
        stats[str(d["uid"])] = {
            "posts_total": len(ps),
            "original_total": sum(1 for p in ps if is_original(p)),
            "status": d.get("status", "")}

    specs = build_chain_specs()
    if not specs:
        raise RuntimeError("LLM 兜底链为空，无法 judge")
    log("judge LLM 兜底链: " + " → ".join(s["label"] for s in specs))
    log(f"judge 并发度: {max(1, concurrency)}；待判定 {len(todo)} 帖（跳过已完成 {len(done_targets)}）")

    tls = threading.local()

    def get_client() -> ChainClient:
        if not hasattr(tls, "client"):
            tls.client = ChainClient(specs)
        return tls.client

    record_lock = threading.Lock()
    state_lock = threading.Lock()
    counts = {"done": 0, "hit": 0, "no": 0}

    def judge_one(c: dict) -> dict:
        sp = snapshot_path(c["target"], c["date"])
        judged_on = c.get("judged_on", "full")
        if judged_on != "trunc" and sp.exists():
            text = sp.read_text(errors="replace")[:4000]
        else:
            text = ((c["title"] + " ") + c["description"])[:1000]
            judged_on = "trunc"
        stances: dict = {}
        try:
            raw = call_llm(get_client(), build_judge_prompt(c, text), kind="judge")
            data = parse_llm_json(raw) if raw else None
            stances = (data or {}).get("stance") or {}
            if not stances and isinstance(data, dict):
                stances = {k: v for k, v in data.items()
                           if str(v).lower() in {"bullish", "bearish", "neutral"}}
        except Exception:  # noqa: BLE001
            stances = {}
        time.sleep(JUDGE_SLEEP)
        return {"uid": c["uid"], "screen_name": c["screen_name"], "source": c["source"],
                "target": c["target"], "date": c["date"], "sectors": c["sectors"],
                "judged_on": judged_on, "snapshot": sp.name if sp.exists() else "",
                "stances": stances, "prompt_version": JUDGE_PROMPT_VERSION}

    def handle(rec: dict) -> None:
        with record_lock:
            with records_file.open("a") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        with state_lock:
            done_targets.add(rec["target"])
            counts["done"] += 1
            hit_any = any(str(rec["stances"].get(sec, "")).lower() == "bullish"
                          for sec in rec["sectors"])
            counts["hit"] += hit_any
            counts["no"] += not hit_any
            if counts["done"] % 50 == 0:
                prog_file.write_text(json.dumps(sorted(done_targets)))
            if counts["done"] % 100 == 0:
                log(f"判定进度 {counts['done']}/{len(todo)}（有命中帖 {counts['hit']} / 无 {counts['no']}）")

    workers = max(1, concurrency)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(judge_one, c) for c in todo]
        for fut in as_completed(futures):
            handle(fut.result())
    prog_file.write_text(json.dumps(sorted(done_targets)))

    # 按 records 重建 verdicts（可恢复：last record wins）
    records: dict[str, dict] = {}
    if records_file.exists():
        for line in records_file.read_text(errors="replace").splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("target"):
                records[r["target"]] = r

    by_uid: dict[str, dict] = {}
    for r in records.values():
        rec = by_uid.setdefault(r["uid"], {
            "uid": r["uid"], "screen_name": r["screen_name"], "source": r["source"],
            "posts_total": 0, "original_total": 0, "hits": []})
        post_day = parse_post_date(r["date"])
        if not post_day:
            continue
        for sec in r.get("sectors", []):
            if str((r.get("stances") or {}).get(sec, "")).lower() == "bullish":
                if not hit_postfilter_ok(r, sec):
                    continue
                for h in find_window_hits(event_index, sec, post_day):
                    rec["hits"].append({**h, "target": r["target"], "date": r["date"],
                                        "judged_on": r.get("judged_on", ""),
                                        "snapshot": r.get("snapshot", "")})
    for uid_, rec in by_uid.items():
        st = stats.get(uid_, {})
        rec["posts_total"] = st.get("posts_total", 0)
        rec["original_total"] = st.get("original_total", 0)
        rec["coverage_note"] = st.get("status", "")
        rec["hit_posts"] = len({h["target"] for h in rec["hits"]})
        (VERDICTS_DIR / f"{uid_}.json").write_text(
            json.dumps(rec, ensure_ascii=False, indent=1))
    log(f"判定完成：本轮判定帖 {counts['done']}，records {len(records)}，覆盖 {len(by_uid)} 人 → verdicts/")


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _hit_priority(hit: dict, prefer_tier: str = "strong") -> tuple:
    """复核样本优先级：指定档位 > 有快照 > 提前天数更长 > 板块涨幅更大。"""
    return (
        1 if hit.get("tier") == prefer_tier else 0,
        1 if hit.get("snapshot") else 0,
        int(hit.get("lead_days") or 0),
        _to_float(hit.get("max_gain_20d")),
        str(hit.get("date") or ""),
        str(hit.get("target") or ""),
    )


def _pick_hit(hits: list[dict], used_targets: set[str],
              prefer_tier: str = "strong") -> dict | None:
    for hit in sorted(hits, key=lambda h: _hit_priority(h, prefer_tier), reverse=True):
        target = hit.get("target")
        if target and target not in used_targets:
            return hit
    return None


def _review_excerpt(hit: dict, limit: int = 600) -> str:
    snapshot = hit.get("snapshot") or ""
    if not snapshot:
        return "(无快照)"
    sp = SNAP_DIR / snapshot
    if not sp.exists():
        return "(快照缺失)"
    return sp.read_text(errors="replace")[:limit]


def _md_cell(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")


def _write_acceptance_review_md(rows: list[dict], top_rows: list[dict]) -> Path:
    """生成可勾选验收表：先专家级验收 TOP20，再逐条复核抽样命中。"""
    rid_by_uid = {str(r.get("uid")): r.get("review_id", "") for r in rows}
    lines = [
        "# 雪球大牛回测 TOP20 验收与抽样复核",
        "",
        f"- 生成时间：{datetime.now().isoformat(timespec='seconds')}",
        f"- 机器可读复核表：`data/xueqiu/verdicts/_sample_review.json`（填 `human_verdict` 后重跑 `--rank` 更新误差率）",
        "- 抽样口径：TOP20 每专家 1 条代表命中 + 21~80 名中腰部随机 10 人各 1 条；每 3 个专家优先抽 1 条中命中，固定随机种子 = 20260927",
        "",
        "## 一、TOP20 名单验收清单（专家级）",
        "",
        "- [ ] 逐项确认：排名是否符合直觉；若某专家明显不应进入 TOP20，在备注写原因并勾选“剔除/降权”。",
        "",
        "| 验收 | rank | 专家 | uid | source | coverage | 综合 | 强/中 | 跨板块 | 密度 | 命中帖 | 复核样本 | 处理 | 备注 |",
        "|---|---:|---|---|---|---|---:|---:|---:|---:|---:|---|---|---|",
    ]
    for r in top_rows:
        uid = str(r.get("uid"))
        lines.append(
            "| [ ] | "
            + " | ".join([
                str(r.get("rank", "")),
                _md_cell(r.get("screen_name", "")),
                _md_cell(uid),
                _md_cell(r.get("source", "")),
                _md_cell(r.get("coverage_note", "")),
                str(r.get("composite", "")),
                f"{r.get('strong', 0)}/{r.get('mid', 0)}",
                str(r.get("persist", "")),
                str(r.get("density", "")),
                str(len(r.get("hits", []))),
                _md_cell(rid_by_uid.get(uid, "")),
                "保留/降权/剔除",
                "",
            ])
            + " |"
        )

    lines += [
        "",
        "## 二、抽样复核表（逐条判定）",
        "",
        "填写规则：`human_verdict` 只填 `bullish` / `bearish` / `neutral`；与 `machine_verdict` 不一致即计 1 条误差。",
        "重点看 4 件事：①是否明确看多；②是否对应同一板块/核心产业链；③发帖日是否在启动前 3~21 天；④快照是否可用。",
        "",
        "| 完成 | review_id | bucket | rank | 专家 | date | sector | tier | lead | gain20d | machine | human | snapshot | 原文 |",
        "|---|---|---|---:|---|---|---|---|---:|---:|---|---|---|---|",
    ]
    for r in rows:
        url = r.get("url") or ""
        done = "[x]" if r.get("human_verdict") else "[ ]"
        lines.append(
            f"| {done} | "
            + " | ".join([
                _md_cell(r.get("review_id", "")),
                _md_cell(r.get("sample_bucket", "")),
                str(r.get("rank", "")),
                _md_cell(r.get("screen_name", "")),
                _md_cell(r.get("date", "")),
                _md_cell(r.get("sector", "")),
                _md_cell(r.get("tier", "")),
                str(r.get("lead_days", "")),
                str(r.get("max_gain_20d", "")),
                _md_cell(r.get("machine_verdict", "")),
                _md_cell(r.get("human_verdict", "")),
                _md_cell(r.get("snapshot", "")),
                f"[link]({url})" if url else "",
            ])
            + " |"
        )

    lines += [
        "",
        "## 三、摘录（复核时先看这里，不够再点原文/快照）",
        "",
    ]
    for r in rows:
        lines += [
            f"### {r.get('review_id')} | {r.get('screen_name')} | {r.get('date')} | {r.get('sector')} | {r.get('tier')}",
            "",
            f"机器：{r.get('machine_verdict', '')}；人工：{r.get('human_verdict', '') or '（未填）'}；备注：{r.get('human_notes', '')}",
            "",
            _md_cell(r.get("excerpt", ""))[:900],
            "",
        ]

    REVIEW_MD_OUT.write_text("\n".join(lines) + "\n")
    return REVIEW_MD_OUT


def step_sample_review(top_n: int = SAMPLE_TOP_N, mid_n: int = SAMPLE_MID_N,
                       seed: int = SAMPLE_SEED) -> Path:
    """人工复核清单：TOP20 全覆盖 + 中腰部随机补样，输出 JSON+Markdown。"""
    verdicts = [json.loads(f.read_text())
                for f in VERDICTS_DIR.glob("[0-9]*.json")]
    if not verdicts:
        raise RuntimeError("verdicts/ 为空，无法生成复核清单")
    ranked = rank_all(verdicts, top_n=len(verdicts))
    by_uid = {str(v.get("uid")): v for v in verdicts}
    review_path = VERDICTS_DIR / "_sample_review.json"
    existing_review: dict[tuple[str, str], dict] = {}
    if review_path.exists():
        try:
            for old in json.loads(review_path.read_text()):
                existing_review[(str(old.get("target") or ""),
                                 str(old.get("sector") or ""))] = old
        except Exception:  # noqa: BLE001
            existing_review = {}

    selected: list[tuple[dict, str]] = [(r, "top20") for r in ranked[:top_n]]
    mid_pool = [r for r in ranked[top_n:] if r.get("hits") and r.get("rank", 999) <= 80]
    if not mid_pool:
        mid_pool = [r for r in ranked[top_n:] if r.get("hits")]
    rng = random.Random(seed)
    selected += [(r, "mid_random")
                 for r in rng.sample(mid_pool, min(mid_n, len(mid_pool)))]

    rows: list[dict] = []
    used_targets: set[str] = set()
    for idx, (r, bucket) in enumerate(selected, 1):
        uid = str(r.get("uid"))
        expert = by_uid.get(uid, r)
        prefer_tier = "mid" if idx % 3 == 0 else "strong"
        hit = _pick_hit(expert.get("hits", []), used_targets, prefer_tier=prefer_tier)
        if not hit:
            continue
        target = str(hit.get("target") or "")
        if not target:
            continue
        used_targets.add(target)
        url = ("https://www.xueqiu.com" + target) if target.startswith("/") else target
        row = {
            "review_id": f"R{len(rows) + 1:02d}",
            "sample_bucket": bucket,
            "rank": r.get("rank"),
            "uid": uid,
            "screen_name": r.get("screen_name") or expert.get("screen_name", ""),
            "source": r.get("source") or expert.get("source", ""),
            "coverage_note": r.get("coverage_note") or expert.get("coverage_note", ""),
            "date": hit.get("date"),
            "sector": hit.get("sector"),
            "tier": hit.get("tier"),
            "lead_days": hit.get("lead_days"),
            "max_gain_20d": hit.get("max_gain_20d"),
            "target": target,
            "url": url,
            "snapshot": hit.get("snapshot", ""),
            "judged_on": hit.get("judged_on", ""),
            "excerpt": _review_excerpt(hit),
            "machine_verdict": "bullish",
            "prompt_version": JUDGE_PROMPT_VERSION,
            "human_verdict": "",
            "human_notes": "",
            "review_checks": {
                "direction_is_bullish": "",
                "sector_match": "",
                "date_in_window": "",
                "snapshot_usable": "",
            },
        }
        old = existing_review.get((target, str(hit.get("sector") or "")))
        if old and old.get("prompt_version") == JUDGE_PROMPT_VERSION:
            row["human_verdict"] = old.get("human_verdict", "")
            row["human_notes"] = old.get("human_notes", "")
            row["review_checks"] = old.get("review_checks", row["review_checks"])
        rows.append(row)

    path = VERDICTS_DIR / "_sample_review.json"
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    md_path = _write_acceptance_review_md(rows, ranked[:top_n])
    log(f"人工复核清单 {len(rows)} 条 → {path}；验收表 → {md_path}")
    return path


def step_rank() -> list[dict]:
    verdicts = [json.loads(f.read_text())
                for f in VERDICTS_DIR.glob("[0-9]*.json")]
    ranked = rank_all(verdicts)
    rows: list[dict] = []
    judged: list[dict] = []
    errors = 0
    human_file = VERDICTS_DIR / "_sample_review.json"
    if human_file.exists():
        rows = json.loads(human_file.read_text())
        current = [r for r in rows if r.get("prompt_version") == JUDGE_PROMPT_VERSION]
        judged = [r for r in current if r.get("human_verdict")]
        errors = sum(1 for r in judged if r["human_verdict"] != r["machine_verdict"])
        rows = current or rows
    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "experts_evaluated": len(verdicts),
        "sample_review": {"total": len(rows) if human_file.exists() else 20,
                          "judged": len(judged),
                          "machine_error_rate": (errors / len(judged) if judged else None),
                          "note": "human_verdict 填完后重跑 --rank 更新误差率"},
        "coverage_caveat": "名单 = 当前仍活跃且曾预判对的人；36 个高产用户仅覆盖最近~600帖（2026-09-24 拍板接受）",
        "top20": [{k: v for k, v in r.items() if k != "hits"} for r in ranked],
        "hits_detail": {r["uid"]: r["hits"] for r in ranked},
    }
    RANKING_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    log(f"TOP20 → {RANKING_OUT.name}（ evaluated {len(verdicts)} 人）")
    for r in ranked[:20]:
        log(f"  #{r['rank']:>2} {r['screen_name']:<14} 综合 {r['composite']:<7.2f} "
            f"眼力 {r['eye_score']:<4} 强{r['strong']}/中{r['mid']} 板块 {r['persist']}")
    return ranked


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--select-only", action="store_true")
    ap.add_argument("--fetch-only", action="store_true")
    ap.add_argument("--judge-only", action="store_true")
    ap.add_argument("--rank", action="store_true")
    ap.add_argument("--sample-review", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--uid", type=str, default=None)
    ap.add_argument("--no-llm", action="store_true", help="select 阶段跳过 LLM 兜底")
    ap.add_argument("--redo-select", action="store_true",
                    help="忽略已有 candidates_posts.json 强制重跑 select（含 LLM 标签兜底）")
    ap.add_argument("--redo-judge", action="store_true",
                    help="归档旧 verdicts 并按当前 prompt 强制重跑 judge")
    ap.add_argument("--concurrency", type=int, default=1,
                    help="judge 并发线程数（每线程独立 LLM client）")
    args = ap.parse_args()

    if args.rank:
        step_rank()
        return
    if args.sample_review:
        step_sample_review()
        return

    client = None
    if not (args.fetch_only or args.no_llm):
        client = make_llm_client()

    candidates = []
    if CAND_OUT.exists() and (args.fetch_only or args.judge_only):
        candidates = json.loads(CAND_OUT.read_text())
    if not (args.fetch_only or args.judge_only):
        if CAND_OUT.exists() and not args.redo_select:
            # 断点语义：select+标签兜底已完成（可能数千次 LLM 调用），不重跑
            candidates = json.loads(CAND_OUT.read_text())
            log(f"候选帖已存在，跳过 select/标签兜底（{len(candidates)} 条；--redo-select 强制重跑）")
        else:
            candidates = step_select(client)
    if args.select_only:
        return
    if not args.judge_only:
        step_fetch(candidates, limit=args.limit, uid=args.uid)
    if args.select_only or args.fetch_only:
        return
    step_judge(client, candidates, limit=args.limit, uid=args.uid,
               redo=args.redo_judge, concurrency=args.concurrency)
    step_rank()


if __name__ == "__main__":
    main()
