"""Standalone probe: seed-essay inventory from the Chroma store, as JSON.

Run as a subprocess by the GUI (never imported into the server process —
chromadb is a heavy import). Reads metadata only via chromadb directly, so
the sentence-transformers embedding model is NOT loaded.

Output (stdout, single JSON object):
  {"available": true, "total": N, "unused": N,
   "by_genre":  {genre:  {"total": n, "unused": n}, ...},
   "by_source": {domain: {"total": n, "unused": n}, ...}}
"""

from __future__ import annotations

import json
import os
import sys
from urllib.parse import urlparse

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PERSIST_DIR = os.path.join(PROJECT_ROOT, "essay_rc_db")


def main() -> int:
    if not os.path.isdir(PERSIST_DIR):
        print(json.dumps({"available": False,
                          "reason": "essay_rc_db/ not found — run a feed sync first"}))
        return 0
    try:
        import chromadb
    except ImportError:
        print(json.dumps({"available": False,
                          "reason": "chromadb not installed (RAG extras)"}))
        return 0
    try:
        client = chromadb.PersistentClient(path=PERSIST_DIR)
        # langchain's Chroma wrapper stores everything in this collection
        coll = client.get_collection("langchain")
        data = coll.get(include=["metadatas"])
    except Exception as e:
        print(json.dumps({"available": False, "reason": str(e)}))
        return 0

    by_genre: dict = {}
    by_source: dict = {}
    total = unused = 0
    for meta in data.get("metadatas") or []:
        meta = meta or {}
        total += 1
        is_unused = not meta.get("used", False)
        unused += is_unused
        genre = meta.get("genre") or "unknown"
        domain = urlparse(meta.get("url") or "").netloc or "unknown"
        for bucket, key in ((by_genre, genre), (by_source, domain)):
            slot = bucket.setdefault(key, {"total": 0, "unused": 0})
            slot["total"] += 1
            slot["unused"] += is_unused

    print(json.dumps({"available": True, "total": total, "unused": unused,
                      "by_genre": by_genre, "by_source": by_source}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
