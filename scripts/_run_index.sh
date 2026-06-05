#!/bin/bash
# Wrapper to run Qdrant index with proper output flushing
cd /home/ubuntu/learning-investment-strategies
rm -rf .qdrant_data .index_state.json
PYTHONUNBUFFERED=1 .venv/bin/python scripts/index_documents_to_qdrant.py > /tmp/qdrant_index.log 2>&1
echo "EXIT_CODE=$?" >> /tmp/qdrant_index.log
