from __future__ import annotations

from neo4j import GraphDatabase

from qing_investment.agent.config import settings


class Neo4jClient:
    def __init__(self):
        self.driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )

    def get_claims_about_stock(self, stock_code: str, limit: int = 10, min_intensity: str | None = None) -> list[dict]:
        query = """
        MATCH (c:Claim)-[:ABOUT]->(s:Stock {code: $stock_code})
        WHERE c.status IN ['active']
        """
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
            return session.run(query, stock_code=stock_code, limit=limit).data()

    def get_claim_evolution(self, claim_id: str) -> list[dict]:
        query = """
        MATCH (c:Claim {id: $claim_id})
        OPTIONAL MATCH (c)-[:SUPERSEDES]->(old:Claim)
        OPTIONAL MATCH (c)-[:CONTRADICTS]->(opp:Claim)
        OPTIONAL MATCH (new:Claim)-[:SUPERSEDES]->(c)
        RETURN c, old, opp, new
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

    def close(self):
        self.driver.close()
