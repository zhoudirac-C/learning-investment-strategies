"""Quick script to show file → chunk count."""
import glob, sys, re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

def chunk_markdown(text: str, source_path: str, source_date: str = "") -> list:
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
                    chunks.append({"text": chunk_text, "heading": current_heading})
                current_para = []
            current_heading = stripped.lstrip("# ").strip()
        elif stripped == "":
            if current_para:
                chunk_text = "\n".join(current_para).strip()
                if len(chunk_text) > 20:
                    chunks.append({"text": chunk_text, "heading": current_heading})
                current_para = []
        else:
            current_para.append(line)
    if current_para:
        chunk_text = "\n".join(current_para).strip()
        if len(chunk_text) > 20:
            chunks.append({"text": chunk_text, "heading": current_heading})
    return chunks

WIKI = sorted(glob.glob(str(REPO_ROOT / 'knowledge/wiki/**/*.md'), recursive=True))
RAW = sorted(glob.glob(str(REPO_ROOT / 'sources/raw/财经/*.md')))
FW = sorted(glob.glob(str(REPO_ROOT / 'framework/*.md')))
files = WIKI + RAW + FW

cumulative = 0
for fp in files:
    path = Path(fp)
    try:
        text = path.read_text(encoding='utf-8')
    except:
        continue
    chunks = chunk_markdown(text, str(path.relative_to(REPO_ROOT)), '')
    cumulative += len(chunks)
    if len(chunks) > 0:
        print(f"{cumulative:5d} | {len(chunks):4d} | {path.relative_to(REPO_ROOT)}")
print(f"\nTotal: {cumulative} chunks from {len(files)} files")
