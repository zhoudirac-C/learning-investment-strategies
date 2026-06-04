#!/usr/bin/env python3
"""
Index wiki and raw documents into Qdrant.

Chunks markdown files by paragraph, generates embeddings, and upserts into
Qdrant collection "qing_knowledge".

Embedding fallback: if sentence-transformers is unavailable, uses a simple
character-bigram hashing embedding (sufficient for basic similarity filtering).
This is a temporary measure until a proper embedding model is installed.
"""
from __future__ import annotations

import glob
import hashlib
import sys
import uuid
from pathlib import Path

# Add project src to path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from qing_investment.agent.config import settings
from qing_investment.agent.tools.qdrant_client import QdrantClientWrapper
from qing_investment.agent.tools.embedding_utils import simple_hash_embedding
from qdrant_client.models import PointStruct

VECTOR_DIM = 1024
COLLECTION = "qing_knowledge"

# Paths to index
WIKI_GLOB = str(REPO_ROOT / "knowledge" / "wiki" / "**" / "*.md")
RAW_GLOB = str(REPO_ROOT / "sources" / "raw" / "财经" / "*.md")


def chunk_markdown(text: str, source_path: str, source_date: str = "") -> list[dict]:
    """Split markdown into paragraph-level chunks."""
    lines = text.splitlines()
    chunks = []
    current_para = []
    current_heading = ""

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            # Flush previous paragraph
            if current_para:
                chunk_text = "\n".join(current_para).strip()
                if len(chunk_text) > 20:
                    chunks.append({
                        "text": chunk_text,
                        "heading": current_heading,
                    })
                current_para = []
            current_heading = stripped.lstrip("# ").strip()
        elif stripped == "":
            if current_para:
                chunk_text = "\n".join(current_para).strip()
                if len(chunk_text) > 20:
                    chunks.append({
                        "text": chunk_text,
                        "heading": current_heading,
                    })
                current_para = []
        else:
            current_para.append(line)

    if current_para:
        chunk_text = "\n".join(current_para).strip()
        if len(chunk_text) > 20:
            chunks.append({
                "text": chunk_text,
                "heading": current_heading,
            })

    # Add metadata
    for c in chunks:
        c["source_path"] = source_path
        c["source_date"] = source_date
        c["source_type"] = "wiki" if "knowledge/wiki" in source_path else "raw"

    return chunks


def extract_date_from_filename(filename: str) -> str:
    """Try to extract YYYY-MM-DD from filenames like '2026-05-17.md' or '26-05-17'."""
    import re
    # Full year pattern
    m = re.search(r"(20\d{2})[-_](\d{2})[-_](\d{2})", filename)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    # Short year pattern
    m = re.search(r"(\d{2})[-_](\d{2})[-_](\d{2})", filename)
    if m:
        year = "20" + m.group(1)
        return f"{year}-{m.group(2)}-{m.group(3)}"
    return ""


def index_documents():
    qdrant = QdrantClientWrapper()
    qdrant.ensure_collection(COLLECTION, vector_size=VECTOR_DIM)

    # Gather all files
    files = sorted(glob.glob(WIKI_GLOB, recursive=True))
    files += sorted(glob.glob(RAW_GLOB))
    print(f"Found {len(files)} markdown files to index")

    total_chunks = 0
    total_points = 0

    for fp in files:
        path = Path(fp)
        text = path.read_text(encoding="utf-8")
        date = extract_date_from_filename(path.name)
        rel_path = str(path.relative_to(REPO_ROOT))

        chunks = chunk_markdown(text, rel_path, date)
        if not chunks:
            continue

        points = []
        for chunk in chunks:
            embedding = simple_hash_embedding(chunk["text"])
            point = PointStruct(
                id=str(uuid.uuid4()),
                vector=embedding,
                payload={
                    "text": chunk["text"],
                    "heading": chunk["heading"],
                    "source_path": chunk["source_path"],
                    "source_date": chunk["source_date"],
                    "source_type": chunk["source_type"],
                },
            )
            points.append(point)

        if points:
            qdrant.upsert(COLLECTION, points)
            total_points += len(points)

        total_chunks += len(chunks)
        if total_chunks % 100 == 0:
            print(f"  Indexed {total_chunks} chunks ({total_points} points)")

    print(f"✅ Indexed {total_chunks} chunks ({total_points} points) from {len(files)} files into Qdrant.")


if __name__ == "__main__":
    index_documents()
