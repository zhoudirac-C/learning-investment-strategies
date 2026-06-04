from __future__ import annotations

from neo4j import GraphDatabase

from qing_investment.agent.config import settings


class Neo4jClient:
    def __init__(self):
        self.driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )

    def get_claims_about_stock(self, stock_code: str, limit: int = 10) -> list[dict]:
        query = """
        MATCH (c:Claim)-[:ABOUT]->(s:Stock {code: $stock_code})
        WHERE c.status IN ['active', 'superseded']
        RETURN c.id as id, c.statement as statement,
               c.confidence as confidence, c.source_date as source_date,
               c.status as status
        ORDER BY c.source_date DESC
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
               c.confidence as confidence, c.source_date as source_date,
               c.status as status
        ORDER BY c.source_date DESC
        LIMIT $limit
        """
        with self.driver.session() as session:
            return session.run(query, keyword=keyword, limit=limit).data()

    def close(self):
        self.driver.close()
