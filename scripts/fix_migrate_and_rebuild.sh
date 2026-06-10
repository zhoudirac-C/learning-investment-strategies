#!/bin/bash
# Re-run Neo4j migration + Qdrant rebuild (the process was killed at 200/270)
set -e
cd ~/learning-investment-strategies

echo "=== 1. Neo4j full migration ==="
PYTHONPATH=src .venv/bin/python scripts/migrate_claims_to_neo4j.py --force-full 2>&1 | tail -20
echo ""

echo "=== 2. Qdrant rebuild (index_claims_to_qdrant) ==="
# Find the index script
if [ -f scripts/index_claims_to_qdrant.py ]; then
    PYTHONPATH=src .venv/bin/python scripts/index_claims_to_qdrant.py 2>&1 | tail -10
elif [ -f scripts/sync_stock_monitor.py ]; then
    # Check if rebuild is embedded
    PYTHONPATH=src .venv/bin/python -c "
from src.tools.neo4j_retriever.migrate_claims_to_neo4j import rebuild_qdrant
rebuild_qdrant()
print('Qdrant rebuild complete')
" 2>&1 | tail -10
else
    echo "No Qdrant rebuild script found — check pipeline"
fi

echo ""
echo "=== 3. Verify Neo4j counts ==="
PYTHONPATH=src .venv/bin/python -c "
from src.tools.neo4j_retriever.neo4j_retriever import Neo4jRetriever
r = Neo4jRetriever()
session = r.driver.session()
result = session.run('MATCH (c:Claim) RETURN count(c) as claim_count, count(DISTINCT c.claim_id) as unique_claims')
record = result.single()
print(f'Neo4j Claim nodes: {record[\"claim_count\"]} total, {record[\"unique_claims\"]} unique')
result2 = session.run('MATCH (s:Stock) RETURN count(s) as stocks')
print(f'Neo4j Stock nodes: {result2.single()[\"stocks\"]}')
result3 = session.run('MATCH ()-[r:ABOUT]->() RETURN count(r) as rels')
print(f'Neo4j ABOUT relations: {result3.single()[\"rels\"]}')
result4 = session.run('MATCH ()-[r:SUPERSEDES]->() RETURN count(r) as rels')
print(f'Neo4j SUPERSEDES relations: {result4.single()[\"rels\"]}')
result5 = session.run('MATCH ()-[r:CONTRADICTS]->() RETURN count(r) as rels')
print(f'Neo4j CONTRADICTS relations: {result5.single()[\"rels\"]}')
session.close()
r.close()
" 2>&1
