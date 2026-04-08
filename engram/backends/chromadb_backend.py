"""ChromaDB vector backend — the default château storage engine.

ChromaDB handles both embedding and storage locally (no API key needed).
Data is persisted under ~/.engram/chroma_db/.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from engram.backends.base import VectorBackend


class ChromaDBBackend(VectorBackend):
    """Wraps ChromaDB's local persistent client.

    Args:
        collection_name: Name of the ChromaDB collection to use.
        persist_directory: Path where ChromaDB stores its data.
    """

    def __init__(
        self,
        collection_name: str = "engram_drawers",
        persist_directory: str | Path = "~/.engram/chroma_db",
    ) -> None:
        import chromadb  # imported here — no network call at import time

        self._collection_name = collection_name
        self._persist_dir = str(Path(persist_directory).expanduser())
        Path(self._persist_dir).mkdir(parents=True, exist_ok=True)

        self._client = chromadb.PersistentClient(path=self._persist_dir)
        self._col = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    # ------------------------------------------------------------------

    def add(self, id: str, text: str, metadata: dict) -> None:
        self._col.upsert(ids=[id], documents=[text], metadatas=[_sanitise(metadata)])

    def search(self, query: str, n: int = 10, where: dict | None = None) -> list[dict]:
        kwargs: dict[str, Any] = {
            "query_texts": [query],
            "n_results": min(n, max(1, self.count())),
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where
        try:
            res = self._col.query(**kwargs)
        except Exception:
            return []

        results = []
        ids = res.get("ids", [[]])[0]
        docs = res.get("documents", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        dists = res.get("distances", [[]])[0]
        for rid, doc, meta, dist in zip(ids, docs, metas, dists):
            results.append(
                {
                    "id": rid,
                    "text": doc,
                    "metadata": meta or {},
                    "score": 1.0 - dist,  # cosine distance → similarity
                }
            )
        return results

    def delete(self, id: str) -> None:
        try:
            self._col.delete(ids=[id])
        except Exception:
            pass

    def count(self) -> int:
        try:
            return self._col.count()
        except Exception:
            return 0

    def update(self, id: str, text: str, metadata: dict) -> None:
        self._col.update(ids=[id], documents=[text], metadatas=[_sanitise(metadata)])


# ---------------------------------------------------------------------------

def _sanitise(metadata: dict) -> dict:
    """ChromaDB only accepts str/int/float/bool metadata values."""
    out: dict = {}
    for k, v in metadata.items():
        if isinstance(v, (str, int, float, bool)):
            out[k] = v
        else:
            out[k] = str(v)
    return out


if __name__ == "__main__":
    backend = ChromaDBBackend()
    print(f"ChromaDB collection '{backend._collection_name}' — {backend.count()} entries")
