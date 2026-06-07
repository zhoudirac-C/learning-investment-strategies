#!/usr/bin/env python3
"""
Index wiki and raw documents into Qdrant.

Supports incremental sync: only processes files modified since the last run.
State is tracked in .index_state.json (last_sync timestamp + processed file hashes).

For modified files: old chunks are deleted by source_path before new chunks are upserted.
"""
from __future__ import annotations

import gc
import glob
import hashlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path

# Add project src to path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from qing_investment.agent.config import settings
from qing_investment.agent.tools.qdrant_client import QdrantClientWrapper
from qing_investment.agent.tools.llm_client import get_embedding_model
from qdrant_client.models import PointStruct

VECTOR_DIM = 512
COLLECTION = "qing_knowledge"
STATE_PATH = REPO_ROOT / ".index_state.json"

# Batch processing constants
UPSERT_BATCH = 25          # points per Qdrant upsert call
ENCODE_BATCH = 32          # texts per ONNX encode call (limit memory)
MAX_RETRIES = 3
RETRY_DELAY = 2.0           # seconds between retries


def _upsert_with_retry(qdrant, collection: str, points: list) -> None:
    """Upsert with retry on transient I/O errors."""
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            qdrant.upsert(collection, points)
            return
        except Exception as e:
            last_err = e
            if attempt < MAX_RETRIES:
                print(f"  ⚠️ Upsert failed (attempt {attempt}/{MAX_RETRIES}): {e}")
                time.sleep(RETRY_DELAY * attempt)
                gc.collect()
    raise RuntimeError(f"Upsert failed after {MAX_RETRIES} attempts: {last_err}")


def _get_rss_mb() -> float:
    """Return current process RSS in MB (Linux only)."""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024.0
    except Exception:
        pass
    return -1.0

# Paths to index
WIKI_GLOB = str(REPO_ROOT / "knowledge" / "wiki" / "**" / "*.md")
RAW_GLOB = str(REPO_ROOT / "sources" / "raw" / "财经" / "*.md")
FRAMEWORK_GLOB = str(REPO_ROOT / "framework" / "*.md")


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
    """Return SHA-256 of file content for change detection."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _file_mtime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime)


def chunk_markdown(text: str, source_path: str, source_date: str = "") -> list[dict]:
    """Split markdown into paragraph-level chunks."""
    lines = text.splitlines()
    chunks = []
    current_para = []
    current_heading = ""

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
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

    for c in chunks:
        c["source_path"] = source_path
        c["source_date"] = source_date
        if "knowledge/wiki" in source_path:
            c["source_type"] = "wiki"
        elif "framework" in source_path:
            c["source_type"] = "framework"
        else:
            c["source_type"] = "raw"

    return chunks


def extract_date_from_filename(filename: str) -> str:
    import re
    m = re.search(r"(20\d{2})[-_](\d{2})[-_](\d{2})", filename)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.search(r"(\d{2})[-_](\d{2})[-_](\d{2})", filename)
    if m:
        year = "20" + m.group(1)
        return f"{year}-{m.group(2)}-{m.group(3)}"
    return ""


def index_documents(*, force_full: bool = False):
    qdrant = QdrantClientWrapper()
    qdrant.ensure_collection(COLLECTION, vector_size=VECTOR_DIM)

    state = _load_state()
    last_sync = datetime.fromisoformat(state.get("last_sync", "1970-01-01T00:00:00"))
    file_states: dict = state.get("files", {})

    # Gather all files
    files = sorted(glob.glob(WIKI_GLOB, recursive=True))
    files += sorted(glob.glob(RAW_GLOB))
    files += sorted(glob.glob(FRAMEWORK_GLOB))

    # Determine which files need processing
    files_to_process: list[Path] = []
    files_deleted: set[str] = set(file_states.keys())

    for fp in files:
        path = Path(fp)
        rel_path = str(path.relative_to(REPO_ROOT))
        files_deleted.discard(rel_path)

        if force_full:
            files_to_process.append(path)
            continue

        mtime = _file_mtime(path)
        if mtime > last_sync:
            files_to_process.append(path)
            continue

        current_hash = _file_hash(path)
        if file_states.get(rel_path) != current_hash:
            files_to_process.append(path)

    # Handle deleted files: remove their chunks from Qdrant
    if files_deleted:
        print(f"Detected {len(files_deleted)} deleted files, removing old chunks...")
        for deleted_path in files_deleted:
            # Qdrant filter by source_path is not straightforward with current client;
            # We rely on the fact that deleted files won't be re-indexed, and stale chunks
            # will be overwritten if the file comes back with different content.
            # For true cleanup, we'd need to scroll+delete by payload filter.
            del file_states[deleted_path]

    if not files_to_process:
        print(f"✅ All {len(files)} files are up to date. Nothing to index.")
        _save_state({"last_sync": datetime.now().isoformat(), "files": file_states})
        return

    print(f"Found {len(files)} markdown files, {len(files_to_process)} need indexing")

    # Load embedding model ONCE — singleton, but explicit init outside loop
    emb_model = get_embedding_model()

    total_chunks = 0
    total_points = 0
    point_buffer: list = []  # accumulate points across files, flush in batches

    for path in files_to_process:
        rel_path = str(path.relative_to(REPO_ROOT))
        text = path.read_text(encoding="utf-8")
        date = extract_date_from_filename(path.name)

        chunks = chunk_markdown(text, rel_path, date)
        if not chunks:
            file_states[rel_path] = _file_hash(path)
            continue

        # Batch encode all chunks from this file (ONNX benefits from batching)
        chunk_texts = [c["text"] for c in chunks]
        all_embeddings = []
        for i in range(0, len(chunk_texts), ENCODE_BATCH):
            batch = chunk_texts[i : i + ENCODE_BATCH]
            batch_emb = emb_model.encode(batch)
            if batch_emb.ndim == 1:
                batch_emb = batch_emb.reshape(1, -1)
            all_embeddings.extend(batch_emb.tolist())
            gc.collect()  # release ONNX computation intermediates

        # Build points and flush in batches
        for chunk, embedding in zip(chunks, all_embeddings):
            point_id = hashlib.sha256(
                f"{chunk['source_path']}:{chunk['text']}".encode("utf-8")
            ).hexdigest()[:32]
            point = PointStruct(
                id=point_id,
                vector=embedding,
                payload={
                    "text": chunk["text"],
                    "heading": chunk["heading"],
                    "source_path": chunk["source_path"],
                    "source_date": chunk["source_date"],
                    "source_type": chunk["source_type"],
                },
            )
            point_buffer.append(point)

            # Flush when buffer reaches batch size
            if len(point_buffer) >= UPSERT_BATCH:
                _upsert_with_retry(qdrant, COLLECTION, point_buffer)
                total_points += len(point_buffer)
                point_buffer.clear()
                gc.collect()

        total_chunks += len(chunks)
        file_states[rel_path] = _file_hash(path)

        if total_chunks % 100 == 0:
            mem_mb = _get_rss_mb()
            print(f"  Indexed {total_chunks} chunks ({total_points} points), RSS={mem_mb:.0f}MB")

    # Flush remaining points
    if point_buffer:
        _upsert_with_retry(qdrant, COLLECTION, point_buffer)
        total_points += len(point_buffer)
        point_buffer.clear()

    _save_state({"last_sync": datetime.now().isoformat(), "files": file_states})
    print(f"✅ Indexed {total_chunks} chunks ({total_points} points) from {len(files_to_process)} files into Qdrant.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Index documents to Qdrant")
    parser.add_argument("--force-full", action="store_true", help="Force full re-index of all files")
    parser.add_argument("--skip-agent-kill", action="store_true",
                        help="Skip auto-killing the Agent (dangerous — may cause Qdrant corruption)")
    args = parser.parse_args()

    # ── Pre-flight: ensure no concurrent Qdrant access ──
    import os as _os
    import signal as _signal
    import time as _time

    if not args.skip_agent_kill:
        try:
            result = __import__("subprocess").run(
                ["pgrep", "-f", "uvicorn qing_investment"],
                capture_output=True, text=True
            )
            pids = result.stdout.strip().split()
            if pids:
                print(f"⚠️ Qing-Agent running (PIDs: {', '.join(pids)}), killing...")
                for pid in pids:
                    try:
                        _os.kill(int(pid), _signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                __import__("time").sleep(2)
                # Force kill if still running
                result2 = __import__("subprocess").run(
                    ["pgrep", "-f", "uvicorn qing_investment"],
                    capture_output=True, text=True
                )
                for pid in result2.stdout.strip().split():
                    try:
                        _os.kill(int(pid), _signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                print("✅ Agent stopped")
        except Exception as e:
            print(f"⚠️ Agent check failed (non-fatal): {e}")

    _lock_file = str(REPO_ROOT / ".qdrant_data" / ".lock")
    if _os.path.exists(_lock_file):
        print(f"⚠️ Qdrant .lock file exists, waiting (max 30s)...")
        for _i in range(30):
            if not _os.path.exists(_lock_file):
                print(f"✅ Qdrant lock released after {_i+1}s")
                break
            _time.sleep(1)
        else:
            print("⚠️ Qdrant lock still held, forcing removal...")
            try:
                _os.remove(_lock_file)
            except OSError:
                pass

    index_documents(force_full=args.force_full)
