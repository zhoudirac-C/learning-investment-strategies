from __future__ import annotations

from datetime import datetime, timedelta

from neo4j import GraphDatabase

from qing_investment.agent.config import settings


class Neo4jClient:
    def __init__(self):
        self.driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )

    def get_claims_about_stock(self, stock_code: str, limit: int = 10, min_intensity: str | None = None) -> list[dict]:
        """Get claims about a stock by code.

        Tries multiple code formats: '000534', '000534.SZ', 'sh600000'.
        """
        # Normalize code format for matching
        codes_to_try = [stock_code]
        pure = stock_code.replace(".SZ", "").replace(".SH", "").replace("sh", "").replace("sz", "")
        if pure != stock_code:
            codes_to_try.append(pure)
        if "." not in stock_code and len(stock_code) == 6:
            # Add exchange suffix for common formats
            if stock_code.startswith("6"):
                codes_to_try.extend([f"{stock_code}.SH", f"sh{stock_code}"])
            else:
                codes_to_try.extend([f"{stock_code}.SZ", f"sz{stock_code}"])

        query = """
        MATCH (c:Claim)-[:ABOUT]->(s:Stock)
        WHERE s.code IN $stock_codes AND c.status IN ['active']
        """
        params = {"stock_codes": codes_to_try, "limit": limit}

        if min_intensity == "medium":
            query += " AND c.intensity IN ['high', 'medium']\n"
        elif min_intensity == "high":
            query += " AND c.intensity = 'high'\n"
        query += """
        RETURN c.id as id, c.statement as statement,
               c.confidence as confidence, coalesce(c.source_date, '') as source_date,
               c.status as status, coalesce(c.subject, '') as subject,
               c.claim_type as claim_type, coalesce(c.intensity, 'medium') as intensity
        ORDER BY source_date DESC
        LIMIT $limit
        """
        with self.driver.session() as session:
            return session.run(query, **params).data()

    def get_claim_evolution(self, claim_id: str) -> list[dict]:
        """Get a claim and its evolution (supersedes, superseded_by, contradicts).

        Returns a single-row list with the claim fields and evolution arrays,
        or an empty list if the claim is not found.
        """
        query = """
        MATCH (c:Claim {id: $claim_id})
        OPTIONAL MATCH (c)-[:SUPERSEDES]->(old:Claim)
        OPTIONAL MATCH (new:Claim)-[:SUPERSEDES]->(c)
        OPTIONAL MATCH (c)-[:CONTRADICTS]->(opp:Claim)
        RETURN c.id as id, c.statement as statement, c.subject as subject,
               c.confidence as confidence, c.source_date as source_date,
               c.status as status, c.claim_type as claim_type,
               coalesce(c.intensity, 'medium') as intensity,
               collect(DISTINCT old.id) as supersedes,
               collect(DISTINCT new.id) as superseded_by,
               collect(DISTINCT opp.id) as contradicts
        """
        with self.driver.session() as session:
            return session.run(query, claim_id=claim_id).data()

    def get_claims_by_keyword(self, keyword: str, limit: int = 10) -> list[dict]:
        """Search claims where statement or subject contains the keyword."""
        query = """
        MATCH (c:Claim)
        WHERE c.subject CONTAINS $keyword OR c.statement CONTAINS $keyword
        RETURN c.id as id, c.statement as statement,
               c.confidence as confidence, coalesce(c.source_date, '') as source_date,
               c.status as status, coalesce(c.subject, '') as subject,
               c.claim_type as claim_type
        ORDER BY source_date DESC
        LIMIT $limit
        """
        with self.driver.session() as session:
            return session.run(query, keyword=keyword, limit=limit).data()

    def get_claims_with_evolution(self, stock_code: str, limit: int = 10, min_intensity: str | None = None) -> list[dict]:
        """Get claims about a stock, including their evolution (superseded/contradicted status)."""
        query = """
        MATCH (c:Claim)-[:ABOUT]->(s:Stock {code: $stock_code})
        WHERE c.status IN ['active']
        """
        if min_intensity == "medium":
            query += " AND c.intensity IN ['high', 'medium']\n"
        elif min_intensity == "high":
            query += " AND c.intensity = 'high'\n"
        query += """
        OPTIONAL MATCH (c)-[:SUPERSEDES]->(old:Claim)
        OPTIONAL MATCH (new:Claim)-[:SUPERSEDES]->(c)
        OPTIONAL MATCH (c)-[:CONTRADICTS]->(opp:Claim)
        RETURN c.id as id, c.statement as statement, c.subject as subject,
               c.confidence as confidence, c.source_date as source_date,
               c.status as status, c.claim_type as claim_type,
               coalesce(c.intensity, 'medium') as intensity,
               collect(DISTINCT old.id) as supersedes,
               collect(DISTINCT new.id) as superseded_by,
               collect(DISTINCT opp.id) as contradicts
        ORDER BY c.source_date DESC
        LIMIT $limit
        """
        with self.driver.session() as session:
            return session.run(query, stock_code=stock_code, limit=limit).data()

    def get_related_claims(self, claim_id: str, limit: int = 10) -> list[dict]:
        """Get claims related to a given claim through entity or claim relationships."""
        query = """
        MATCH (c:Claim {id: $claim_id})-[:ABOUT]->(e)<-[:ABOUT]-(related:Claim)
        WHERE related.id <> c.id
        RETURN related.id as id, related.statement as statement,
               related.subject as subject, related.confidence as confidence,
               related.source_date as source_date, related.claim_type as claim_type,
               labels(e)[0] as entity_type, e.name as entity_name
        ORDER BY related.source_date DESC
        LIMIT $limit
        """
        with self.driver.session() as session:
            return session.run(query, claim_id=claim_id, limit=limit).data()

    def get_stock_by_name(self, name: str) -> list[dict]:
        """Search Stock nodes whose name CONTAINS the given string.

        Returns list of dicts with code, name, and optionally a count of
        associated claims.
        """
        query = """
        MATCH (s:Stock)
        WHERE s.name CONTAINS $name
        OPTIONAL MATCH (c:Claim)-[:ABOUT]->(s)
        RETURN s.code as code, s.name as name, count(DISTINCT c) as claim_count
        ORDER BY s.code
        """
        with self.driver.session() as session:
            return session.run(query, name=name).data()

    def get_recent_claims(self, claim_type: str | None = None, days: int = 7, limit: int = 50) -> list[dict]:
        """Get recent claims, optionally filtered by type.

        Args:
            claim_type: Filter by claim_type (e.g., 'operation', 'methodology')
            days: How many days back to look
            limit: Max results
        """
        query = """
        MATCH (c:Claim)
        WHERE c.source_date >= $cutoff_date
        """
        params = {"cutoff_date": (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d"), "limit": limit}

        if claim_type:
            query += " AND c.claim_type = $claim_type\n"
            params["claim_type"] = claim_type

        query += """
        RETURN c.id as id, c.statement as statement,
               c.confidence as confidence, coalesce(c.source_date, '') as source_date,
               c.status as status, coalesce(c.subject, '') as subject,
               c.claim_type as claim_type, coalesce(c.intensity, 'medium') as intensity
        ORDER BY source_date DESC
        LIMIT $limit
        """
        with self.driver.session() as session:
            return session.run(query, **params).data()

    def get_sector_themes(self, days: int = 30, limit: int = 100) -> list[dict]:
        """Get all unique sector-theme directions from recent claims.

        Extracts direction keywords from sector-theme claims' subject and statement fields.
        Returns deduplicated list of direction names with their latest mention date
        and mention count.

        Args:
            days: How many days back to look for themes
            limit: Max claims to scan
        """
        query = """
        MATCH (c:Claim)
        WHERE c.claim_type = 'sector-theme'
          AND c.source_date >= $cutoff_date
          AND c.status IN ['active']
        RETURN c.subject as subject, c.statement as statement,
               c.source_date as source_date, c.intensity as intensity
        ORDER BY source_date DESC
        LIMIT $limit
        """
        with self.driver.session() as session:
            rows = session.run(
                query,
                cutoff_date=(datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d"),
                limit=limit
            ).data()

        # Extract direction keywords from subject and statement
        import re
        direction_counts: dict[str, dict] = {}

        # Common direction keywords to extract from statements
        # These are known sector/theme keywords in Chinese A-share market
        known_directions = [
            "燃气轮机", "机器人", "半导体", "光互连", "光通信", "PCB", "存储",
            "电力", "煤炭", "创新药", "工程机械", "MLCC", "CCL", "树脂",
            "光纤", "硅片", "模拟芯片", "连接器", "算力", "AI", "商业航天",
            "卫星通信", "洁净室", "芯片", "上游材料", "辅材", "电子树脂",
            "人形机器人", "消费级机器人", "NPO", "直流",
        ]

        for row in rows:
            subject = row.get("subject", "")
            statement = row.get("statement", "")
            source_date = row.get("source_date", "")
            intensity = row.get("intensity", "medium")

            # Strategy 1: Extract from subject
            # Subjects for sector-theme claims often contain direction names
            # Try to extract the core direction name (before "——", "-", "：")
            clean_subject = re.split(r'[——\-:：]', subject)[0].strip()
            # Remove common prefixes
            clean_subject = re.sub(r'^(方向|板块|主题|行业|主线)[\-:]?', '', clean_subject).strip()
            # Remove suffixes like "方向", "板块"
            clean_subject = re.sub(r'(方向|板块)$', '', clean_subject).strip()

            if clean_subject and len(clean_subject) >= 2:
                _add_direction(direction_counts, clean_subject, source_date, intensity)

            # Strategy 2: Match known direction keywords in statement
            for kw in known_directions:
                if kw in statement or kw in subject:
                    _add_direction(direction_counts, kw, source_date, intensity)

        # Sort by mention count (desc) then by date (desc)
        result = sorted(
            direction_counts.values(),
            key=lambda x: (x["count"], x["latest_date"]),
            reverse=True
        )
        return result

    def close(self):
        self.driver.close()


def _add_direction(
    direction_counts: dict[str, dict],
    direction: str,
    source_date: str,
    intensity: str,
) -> None:
    """Helper to add/update a direction in the counts dict."""
    if direction not in direction_counts:
        direction_counts[direction] = {
            "direction": direction,
            "count": 0,
            "latest_date": source_date,
            "latest_intensity": intensity,
        }
    direction_counts[direction]["count"] += 1
    if source_date > direction_counts[direction]["latest_date"]:
        direction_counts[direction]["latest_date"] = source_date
        direction_counts[direction]["latest_intensity"] = intensity
