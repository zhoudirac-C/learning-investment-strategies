#!/usr/bin/env python3
"""
Migrate claims from knowledge/claims/*.yaml into Neo4j.

Supports incremental sync: only processes files modified since the last run.
State is tracked in .migrate_state.json.

For modified files: old Claim nodes and relationships are deleted before re-insertion
to ensure property updates are applied.

Creates:
- (:Claim) nodes
- (:Stock | :Sector | :Theme | :Macro | :Methodology) entity nodes
- (:SourceDocument) nodes
- Relationships: ABOUT, SUPERSEDES, CONTRADICTS, CITED_IN, EXTRACTED_FROM
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import yaml
from neo4j import GraphDatabase

# Add project src to path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from qing_investment.agent.config import settings

CLAIMS_DIR = REPO_ROOT / "knowledge" / "claims"
STATE_PATH = REPO_ROOT / ".migrate_state.json"

# Regex for Chinese stock codes (6 digits, optionally with .SH/.SZ suffix)
STOCK_CODE_RE = re.compile(r"\b(\d{6})(?:\.SH|\.SZ|\.sh|\.sz)?\b")
# Also match stock names that might be in positions.yaml
STOCK_NAME_TO_CODE: dict[str, str] = {}
STOCK_CODE_TO_NAME: dict[str, str] = {}

def _load_stock_name_mapping() -> dict[str, str]:
    """
    Build stock name→code mapping from positions.yaml + watchlist.yaml.

    Priority: positions.yaml entries overwrite watchlist.yaml entries for
    same stock name with different codes (with a warning).
    Also populates STOCK_NAME_TO_CODE and STOCK_CODE_TO_NAME module globals.
    Returns name→code dict.
    """
    mapping: dict[str, str] = {}
    config_dir = REPO_ROOT / "config" / "stock_monitor"

    # 1. Read positions.yaml (highest priority, private file — silent skip)
    try:
        positions_path = config_dir / "positions.yaml"
        if positions_path.exists():
            data = yaml.safe_load(positions_path.read_text(encoding="utf-8"))
            for account in data.get("accounts", []):
                for pos in account.get("positions", []):
                    name = pos.get("name", "")
                    code = pos.get("code", "").replace(".SZ", "").replace(".SH", "").replace(".sz", "").replace(".sh", "")
                    if name and code:
                        if name in mapping and mapping[name] != code:
                            print(f"  ⚠️ positions.yaml: 股票名 '{name}' 已存在(code={mapping[name]}), 覆盖为 {code}")
                        mapping[name] = code
    except Exception:
        pass

    # 2. Read watchlist.yaml (public config file — silent skip if missing)
    try:
        watchlist_path = config_dir / "watchlist.yaml"
        if watchlist_path.exists():
            data = yaml.safe_load(watchlist_path.read_text(encoding="utf-8"))
            for theme in data.get("themes", []):
                for stock in theme.get("stocks", []):
                    name = stock.get("name", "")
                    code = stock.get("code", "").replace(".SZ", "").replace(".SH", "").replace(".sz", "").replace(".sh", "")
                    if name and code:
                        if name in mapping and mapping[name] != code:
                            print(f"  ⚠️ watchlist.yaml: 股票名 '{name}' 已存在(code={mapping[name]}), 覆盖为 {code}")
                        mapping[name] = code
    except Exception:
        pass

    # 3. Supplemental mapping for common UP-mentioned stocks not in positions/watchlist
    supplemental = {
        "协创数据": "300857", "宏景科技": "301396", "网宿科技": "300017",
        "润泽科技": "300442", "烽火通信": "600498", "智微智能": "001339",
        "润和软件": "300339", "富创精密": "688409", "珂玛科技": "301611",
        "京仪装备": "688652", "润建股份": "002929", "北方华创": "002371",
        "兆易创新": "603986", "领益智造": "002600", "中科飞测": "688361",
        "柏诚股份": "601133", "北自科技": "603082", "中天精装": "002989",
        "上峰水泥": "000672", "华峰测控": "688200", "英维克": "002837",
        "深科技": "000021", "新易盛": "300502", "通富微电": "002156",
        "茂莱光学": "688502", "澜起科技": "688008",
    }
    for name, code in supplemental.items():
        if name not in mapping:
            mapping[name] = code

    # 4. Build reverse mapping (code→name) for backfill use
    code_to_name: dict[str, str] = {}
    for name, code in mapping.items():
        if code in code_to_name and code_to_name[code] != name:
            print(f"  ⚠️ 代码 {code} 对应多个名称: '{code_to_name[code]}' vs '{name}', 保留 '{name}'")
        code_to_name[code] = name

    # Update module-level globals for downstream consumers
    global STOCK_NAME_TO_CODE, STOCK_CODE_TO_NAME
    STOCK_NAME_TO_CODE = mapping
    STOCK_CODE_TO_NAME = code_to_name

    return mapping


def extract_stock_codes(text: str) -> set[str]:
    """Extract stock codes from text, including .SH/.SZ suffixes and known names."""
    codes = set(STOCK_CODE_RE.findall(text))
    
    # Also check for known stock names
    mapping = _load_stock_name_mapping()
    for name, code in mapping.items():
        if name in text:
            codes.add(code)
    
    return codes
SECTOR_KEYWORDS = [
    "半导体", "AI", "算力", "存储", "新能源", "光伏", "锂电", "电力", "军工",
    "商业航天", "机器人", "CPO", "光模块", "通信", "消费电子", "医药", "化工",
    "资源", "周期", "红利", "燃气轮机", "核电", "芯片", "国产替代", "数据中心",
    "光互连", "PCB", "MLCC", "ABF", "设备", "材料", "电池", "发动机",
]


def _load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"last_sync": "1970-01-01T00:00:00", "files": {}}


def _save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _file_mtime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime)


def parse_claims_file(path: Path) -> list[dict]:
    """Parse a claims YAML file, handling multiple formats."""
    text = path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        print(f"  ⚠️ YAML parse error in {path.name}: {e}")
        return []
    if data is None:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if "claims" in data:
            claims = data["claims"]
            return claims if isinstance(claims, list) else [claims]
        return [data]
    return []


def extract_sectors(subject: str, statement: str) -> set[str]:
    """Extract sector/theme mentions from text."""
    found = set()
    combined = subject + " " + statement
    for kw in SECTOR_KEYWORDS:
        if kw in combined:
            found.add(kw)
    return found


def get_entity_type(claim_type: str, subject: str) -> str:
    """Map claim_type to entity node label."""
    mapping = {
        "stock-view": "Stock",
        "sector-theme": "Sector",
        "macro": "Macro",
        "market-cycle": "Macro",
        "methodology": "Methodology",
        "operation": "Methodology",
    }
    return mapping.get(claim_type, "Theme")


def migrate():
    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )

    state = _load_state()
    last_sync = datetime.fromisoformat(state.get("last_sync", "1970-01-01T00:00:00"))
    file_states: dict = state.get("files", {})

    # Constraints & indexes
    with driver.session() as session:
        session.run("CREATE CONSTRAINT claim_id IF NOT EXISTS FOR (c:Claim) REQUIRE c.id IS UNIQUE")
        session.run("CREATE CONSTRAINT entity_name IF NOT EXISTS FOR (e:Entity) REQUIRE e.name IS UNIQUE")
        session.run("CREATE CONSTRAINT source_path IF NOT EXISTS FOR (s:SourceDocument) REQUIRE s.path IS UNIQUE")
        session.run("CREATE INDEX claim_status IF NOT EXISTS FOR (c:Claim) ON (c.status)")
        session.run("CREATE INDEX claim_type IF NOT EXISTS FOR (c:Claim) ON (c.claim_type)")
        session.run("CREATE INDEX claim_intensity IF NOT EXISTS FOR (c:Claim) ON (c.intensity)")

    # Collect files and determine which need processing
    yaml_files = sorted(glob.glob(str(CLAIMS_DIR / "*.yaml")))
    files_to_process: list[tuple[Path, list[dict]]] = []
    files_deleted: set[str] = set(file_states.keys())

    for fp in yaml_files:
        path = Path(fp)
        fname = path.name
        files_deleted.discard(fname)

        claims = parse_claims_file(path)
        if not claims:
            continue

        mtime = _file_mtime(path)
        if mtime > last_sync:
            files_to_process.append((path, claims))
            continue

        current_hash = _file_hash(path)
        if file_states.get(fname) != current_hash:
            files_to_process.append((path, claims))

    if not files_to_process and not files_deleted:
        print(f"✅ All {len(yaml_files)} claim files are up to date. Nothing to migrate.")
        _save_state({"last_sync": datetime.now().isoformat(), "files": file_states})
        driver.close()
        return

    print(f"Found {len(yaml_files)} YAML files, {len(files_to_process)} need migration")

    # For modified files: delete old claims first to ensure property updates
    with driver.session() as session:
        for path, claims in files_to_process:
            claim_ids = [c.get("id", "") for c in claims if isinstance(c, dict) and c.get("id")]
            if claim_ids:
                # Delete old claims from this file to allow re-creation with fresh properties
                session.run(
                    "MATCH (c:Claim) WHERE c.id IN $ids DETACH DELETE c",
                    {"ids": claim_ids},
                )

    # Collect all claims from files to process
    all_claims: list[dict] = []
    for path, claims in files_to_process:
        for c in claims:
            if not isinstance(c, dict):
                continue
            c["_file"] = path.name
            all_claims.append(c)

    print(f"Total claims to migrate: {len(all_claims)}")

    # Batch insert claims + entities + relationships
    batch_size = 50
    with driver.session() as session:
        for i in range(0, len(all_claims), batch_size):
            batch = all_claims[i : i + batch_size]
            for claim in batch:
                _migrate_single_claim(session, claim)
            print(f"  Migrated {min(i + batch_size, len(all_claims))}/{len(all_claims)} claims")

    driver.close()
    print("✅ Claims migration complete.")

    # Update state
    for path, _ in files_to_process:
        file_states[path.name] = _file_hash(path)
    for deleted in files_deleted:
        file_states.pop(deleted, None)
    _save_state({"last_sync": datetime.now().isoformat(), "files": file_states})


def _migrate_single_claim(session, claim: dict):
    cid = claim.get("id", "")
    if not cid:
        return

    # Merge Claim node (fresh properties after delete + recreate)
    session.run(
        """
        CREATE (c:Claim {
            id: $id,
            statement: $statement,
            evidence_quote: $evidence_quote,
            interpretation: $interpretation,
            confidence: $confidence,
            status: $status,
            claim_type: $claim_type,
            intensity: $intensity,
            time_frame: $time_frame,
            subject: $subject,
            source_date: $source_date,
            file: $file
        })
        """,
        {
            "id": cid,
            "statement": claim.get("statement", "") or claim.get("text", ""),
            "evidence_quote": claim.get("evidence_quote", ""),
            "interpretation": claim.get("interpretation", ""),
            "confidence": claim.get("confidence", "medium"),
            "status": claim.get("status", "active"),
            "claim_type": claim.get("claim_type", claim.get("type", "general")),
            "intensity": claim.get("intensity", "medium"),
            "time_frame": claim.get("time_frame", "") or claim.get("timeframe", ""),
            "subject": claim.get("subject", ""),
            "source_date": claim.get("source_date", ""),
            "file": claim.get("_file", ""),
        },
    )

    # Extract and link entities
    subject = claim.get("subject", "")
    statement = claim.get("statement", "") or claim.get("text", "")
    stock_codes = extract_stock_codes(subject + " " + statement)
    name = subject or statement[:100]
    for code in stock_codes:
        session.run(
            """
            MERGE (s:Stock {code: $code})
            SET s.name = $name
            WITH s
            MATCH (c:Claim {id: $cid})
            MERGE (c)-[:ABOUT {relation_type: 'mentions'}]->(s)
            """,
            {"code": code, "name": name, "cid": cid},
        )

    # Sectors / themes
    sectors = extract_sectors(subject, statement)
    for sec in sectors:
        session.run(
            """
            MERGE (sec:Sector {name: $name})
            WITH sec
            MATCH (c:Claim {id: $cid})
            MERGE (c)-[:ABOUT {relation_type: 'sector'}]->(sec)
            """,
            {"name": sec, "cid": cid},
        )

    # Primary entity (subject)
    entity_label = get_entity_type(claim.get("claim_type", claim.get("type", "")), subject)
    if subject:
        # For Stock entities, try to extract code from subject
        if entity_label == "Stock":
            stock_codes = extract_stock_codes(subject)
            if stock_codes:
                code = list(stock_codes)[0]
                session.run(
                    """
                    MERGE (e:Stock {code: $code})
                    SET e.name = $name
                    WITH e
                    MATCH (c:Claim {id: $cid})
                    MERGE (c)-[:ABOUT {relation_type: 'primary'}]->(e)
                    """,
                    {"code": code, "name": subject, "cid": cid},
                )
            else:
                session.run(
                    f"""
                    MERGE (e:{entity_label} {{name: $name}})
                    WITH e
                    MATCH (c:Claim {{id: $cid}})
                    MERGE (c)-[:ABOUT {{relation_type: 'primary'}}]->(e)
                    """,
                    {"name": subject, "cid": cid},
                )
        else:
            session.run(
                f"""
                MERGE (e:{entity_label} {{name: $name}})
                WITH e
                MATCH (c:Claim {{id: $cid}})
                MERGE (c)-[:ABOUT {{relation_type: 'primary'}}]->(e)
                """,
                {"name": subject, "cid": cid},
            )

    # Source document — YAML uses 'source_path', not 'source'
    source_path = claim.get("source_path", "") or claim.get("source", "")
    if source_path:
        session.run(
            """
            MERGE (s:SourceDocument {path: $path})
            WITH s
            MATCH (c:Claim {id: $cid})
            MERGE (c)-[:EXTRACTED_FROM]->(s)
            """,
            {"path": source_path, "cid": cid},
        )

    # Cited wiki pages — YAML uses links.wiki_pages
    links = claim.get("links", {}) or {}
    if isinstance(links, dict):
        wiki_pages = links.get("wiki_pages", []) or []
        if isinstance(wiki_pages, str):
            wiki_pages = [wiki_pages]
        for wiki_path in wiki_pages:
            session.run(
                """
                MERGE (w:WikiPage {path: $path})
                WITH w
                MATCH (c:Claim {id: $cid})
                MERGE (c)-[:CITED_IN]->(w)
                """,
                {"path": wiki_path, "cid": cid},
            )

        # Methodology pages — YAML uses links.methodology_pages
        methodology_pages = links.get("methodology_pages", []) or []
        if isinstance(methodology_pages, str):
            methodology_pages = [methodology_pages]
        for meth_path in methodology_pages:
            session.run(
                """
                MERGE (m:MethodologyPage {path: $path})
                WITH m
                MATCH (c:Claim {id: $cid})
                MERGE (c)-[:CITED_IN]->(m)
                """,
                {"path": meth_path, "cid": cid},
            )


def migrate_relations():
    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )

    yaml_files = sorted(glob.glob(str(CLAIMS_DIR / "*.yaml")))
    all_claims: list[dict] = []
    for fp in yaml_files:
        claims = parse_claims_file(Path(fp))
        if claims:
            all_claims.extend([c for c in claims if isinstance(c, dict)])

    # Build id -> claim map
    claim_map = {c.get("id"): c for c in all_claims if c.get("id")}

    with driver.session() as session:
        for claim in all_claims:
            cid = claim.get("id", "")
            if not cid:
                continue

            # SUPERSEDES
            supersedes = claim.get("supersedes", [])
            if isinstance(supersedes, str):
                supersedes = [supersedes]
            for opp_id in supersedes or []:
                if opp_id not in claim_map:
                    continue
                session.run(
                    """
                    MATCH (a:Claim {id: $a_id}), (b:Claim {id: $b_id})
                    MERGE (a)-[:SUPERSEDES {reason: $reason}]->(b)
                    """,
                    {
                        "a_id": cid,
                        "b_id": opp_id,
                        "reason": claim.get("supersedes_reason", "superseded"),
                    },
                )

            # CONTRADICTS
            contradicts = claim.get("contradicts", [])
            if isinstance(contradicts, str):
                contradicts = [contradicts]
            for opp_id in contradicts or []:
                if opp_id not in claim_map:
                    continue
                session.run(
                    """
                    MATCH (a:Claim {id: $a_id}), (b:Claim {id: $b_id})
                    MERGE (a)-[:CONTRADICTS {reason: $reason}]->(b)
                    """,
                    {
                        "a_id": cid,
                        "b_id": opp_id,
                        "reason": claim.get("contradicts_reason", "contradiction"),
                    },
                )

    driver.close()
    print("✅ Relations migration (SUPERSEDES/CONTRADICTS) complete.")


if __name__ == "__main__":
    migrate()
    migrate_relations()
