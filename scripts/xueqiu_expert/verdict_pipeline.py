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
  python verdict_pipeline.py                         # 全流程 select → tag → fetch → judge
  python verdict_pipeline.py --rank                  # P5：读 verdicts/ 评 TOP20
  python verdict_pipeline.py --sample-review         # 生成 20 条人工复核清单
  python verdict_pipeline.py --limit 3 --uid 123     # 试跑
产出：
  data/xueqiu/candidates_posts.json     # 窗口内候选帖（含命中板块与来源层）
  data/xueqiu/verdicts/{uid}.json       # 每人命中明细
  data/xueqiu/verdicts/_sample_review.json
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
import time
import urllib.request
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
LLM_LOG = REPO / "logs" / "llm_calls_p4.jsonl"

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
    "workbuddy:deepseek-v4.1-flash",
    "workbuddy:glm-5.3-flash",
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
        return None


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
    with LLM_LOG.open("a") as f:
        f.write(json.dumps({"ts": datetime.now().isoformat(timespec="seconds"),
                            **record}, ensure_ascii=False) + "\n")


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
                "以下每条是雪球用户帖子的开头片段。判断每条主要讨论的行业/主题，"
                "从候选板块清单中选（可多选，精确匹配清单原文；与清单都无关则空数组）。\n"
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


def step_judge(client, candidates: list[dict], limit: int = 0,
               uid: str | None = None) -> None:
    """LLM 看多/中性/看空（按帖 × 其候选板块）→ verdicts/{uid}.json。"""
    VERDICTS_DIR.mkdir(parents=True, exist_ok=True)
    event_index, _ = load_inputs()
    todo = [c for c in candidates
            if c.get("sectors") and (uid is None or c["uid"] == uid)]
    if limit:
        todo = todo[:limit]
    # 断点：已判定 target 集合（含无命中帖，避免重跑重复判定）
    prog_file = VERDICTS_DIR / "_judge_progress.json"
    done_targets: set[str] = set()
    if prog_file.exists():
        try:
            done_targets = set(json.loads(prog_file.read_text()))
        except Exception:  # noqa: BLE001
            done_targets = set()
    for f in VERDICTS_DIR.glob("[0-9]*.json"):
        try:
            done_targets |= {h["target"] for h in json.loads(f.read_text()).get("hits", [])}
        except Exception:  # noqa: BLE001
            continue
    by_uid: dict[str, dict] = {}
    n_hit = n_no = 0
    for i, c in enumerate(todo, 1):
        if c["target"] in done_targets:
            continue
        sp = snapshot_path(c["target"], c["date"])
        if c.get("judged_on") != "trunc" and sp.exists():
            text = sp.read_text(errors="replace")[:6000]
        else:
            text = ((c["title"] + " ") + c["description"])[:1000]
            c["judged_on"] = "trunc"
        secs = "、".join(c["sectors"])
        prompt = (
            f"以下是雪球用户 {c['date']} 的帖子全文。针对板块【{secs}】：\n"
            "判断作者在发帖时对每个板块（或其核心个股/产业链）的态度：\n"
            "- bullish=明确看多/看好/看涨/建议买入布局\n"
            "- bearish=明确看空/看淡/提示风险卖出\n"
            "- neutral=仅提及、讨论事实、态度不明\n\n"
            f"帖子：\n{text}\n\n"
            '只输出 JSON：{"stance": {"板块名": "bullish|bearish|neutral"}}')
        raw = call_llm(client, prompt, kind="judge")
        data = parse_llm_json(raw) if raw else None
        stances = (data or {}).get("stance") or {}
        rec = by_uid.setdefault(c["uid"], {
            "uid": c["uid"], "screen_name": c["screen_name"], "source": c["source"],
            "posts_total": 0, "original_total": 0, "hits": []})
        done_targets.add(c["target"])
        if i % 50 == 0:
            prog_file.write_text(json.dumps(sorted(done_targets)))
        hit_any = False
        post_day = parse_post_date(c["date"])
        for sec in c["sectors"]:
            if str(stances.get(sec, "")).lower() == "bullish" and post_day:
                for h in find_window_hits(event_index, sec, post_day):
                    rec["hits"].append({**h, "target": c["target"], "date": c["date"],
                                        "judged_on": c["judged_on"],
                                        "snapshot": sp.name if sp.exists() else ""})
                    hit_any = True
        n_hit += hit_any
        n_no += not hit_any
        if i % 100 == 0:
            log(f"判定进度 {i}/{len(todo)}（有命中帖 {n_hit} / 无 {n_no}）")
        time.sleep(JUDGE_SLEEP)

    prog_file.write_text(json.dumps(sorted(done_targets)))
    # 汇总落盘（补 posts 统计）
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
    for uid_, rec in by_uid.items():
        st = stats.get(uid_, {})
        rec["posts_total"] = st.get("posts_total", 0)
        rec["original_total"] = st.get("original_total", 0)
        rec["coverage_note"] = st.get("status", "")
        rec["hit_posts"] = len({h["target"] for h in rec["hits"]})
        (VERDICTS_DIR / f"{uid_}.json").write_text(
            json.dumps(rec, ensure_ascii=False, indent=1))
    log(f"判定完成：判定帖 {len(todo)}，覆盖 {len(by_uid)} 人 → verdicts/")


def step_sample_review(n: int = 20) -> Path:
    """人工复核清单：分层抽样（bullish 判定 + 各渠道）。"""
    hits = []
    for f in VERDICTS_DIR.glob("[0-9]*.json"):
        d = json.loads(f.read_text())
        for h in d.get("hits", []):
            hits.append({**h, "uid": d["uid"], "screen_name": d["screen_name"]})
    random.seed(42)
    sample = random.sample(hits, min(n, len(hits)))
    out = []
    for h in sample:
        sp = SNAP_DIR / h["snapshot"]
        excerpt = sp.read_text(errors="replace")[:600] if sp.exists() else "(无快照)"
        out.append({"uid": h["uid"], "screen_name": h["screen_name"],
                    "date": h["date"], "sector": h["sector"], "tier": h["tier"],
                    "target": h["target"], "excerpt": excerpt,
                    "machine_verdict": "bullish", "human_verdict": ""})
    path = VERDICTS_DIR / "_sample_review.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    log(f"人工复核清单 {len(out)} 条 → {path}")
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
        judged = [r for r in rows if r.get("human_verdict")]
        errors = sum(1 for r in judged if r["human_verdict"] != r["machine_verdict"])
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
        candidates = step_select(client)
    if args.select_only:
        return
    if not args.judge_only:
        step_fetch(candidates, limit=args.limit, uid=args.uid)
    if args.select_only or args.fetch_only:
        return
    step_judge(client, candidates, limit=args.limit, uid=args.uid)
    step_rank()


if __name__ == "__main__":
    main()
