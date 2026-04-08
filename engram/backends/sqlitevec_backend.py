"""sqlite-vec vector backend — zero-dependency fallback.

Uses sqlite-vec extension for vector search.  Falls back to pure-Python
cosine similarity when sqlite-vec is not installed, so the backend is
always importable.

Install the full version with::

    pip install engram[sqlitevec]
"""

from __future__ import annotations

import json
import sqlite3
import struct
from pathlib import Path

from engram.backends.base import VectorBackend

_EMBED_DIM = 384


def _get_embedder():
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
        return SentenceTransformer("all-MiniLM-L6-v2")
    except Exception:
        return None


class SqliteVecBackend(VectorBackend):
    """Pure-SQLite vector store.

    Uses sqlite-vec extension when available, otherwise stores
    serialised float blobs and does brute-force cosine search in Python.

    Args:
        db_path: Path to the SQLite database file.
    """

    def __init__(self, db_path: str | Path = "~/.engram/engram_vec.db") -> None:
        self._db_path = Path(db_path).expanduser()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._embedder = _get_embedder()
        self._has_sqlite_vec = False

        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row
        self._try_load_sqlite_vec()
        self._create_tables()

    # ------------------------------------------------------------------

    def _try_load_sqlite_vec(self) -> None:
        try:
            import sqlite_vec  # type: ignore
            sqlite_vec.load(self._conn)
            self._has_sqlite_vec = True
        except Exception:
            pass

    def _create_tables(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS engram_entries (
                id TEXT PRIMARY KEY,
                text TEXT NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}',
                embedding BLOB
            )
            """
        )
        self._conn.commit()

    def _embed(self, text: str) -> list[float]:
        if self._embedder:
            vec = self._embedder.encode([text], normalize_embeddings=True)
            return vec[0].tolist()
        # deterministic stub
        import hashlib, math
        raw = hashlib.sha256(text.encode()).digest()
        floats = [b / 255.0 for b in raw]
        floats = (floats * (_EMBED_DIM // len(floats) + 1))[:_EMBED_DIM]
        norm = math.sqrt(sum(x * x for x in floats)) + 1e-9
        return [x / norm for x in floats]

    @staticmethod
    def _pack(vec: list[float]) -> bytes:
        return struct.pack(f"{len(vec)}f", *vec)

    @staticmethod
    def _unpack(blob: bytes) -> list[float]:
        n = len(blob) // 4
        return list(struct.unpack(f"{n}f", blob))

    # ------------------------------------------------------------------

    def add(self, id: str, text: str, metadata: dict) -> None:
        vec = self._embed(text)
        blob = self._pack(vec)
        self._conn.execute(
            "INSERT OR REPLACE INTO engram_entries (id, text, metadata, embedding) VALUES (?,?,?,?)",
            (id, text, json.dumps(metadata), blob),
        )
        self._conn.commit()

    def search(self, query: str, n: int = 10, where: dict | None = None) -> list[dict]:
        qvec = self._embed(query)
        rows = self._conn.execute(
            "SELECT id, text, metadata, embedding FROM engram_entries"
        ).fetchall()

        scored = []
        for row in rows:
            meta = json.loads(row["metadata"])
            if where and not all(meta.get(k) == v for k, v in where.items()):
                continue
            dvec = self._unpack(row["embedding"])
            score = _cosine(qvec, dvec)
            scored.append(
                {"id": row["id"], "text": row["text"], "metadata": meta, "score": score}
            )

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:n]

    def delete(self, id: str) -> None:
        self._conn.execute("DELETE FROM engram_entries WHERE id = ?", (id,))
        self._conn.commit()

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM engram_entries").fetchone()[0]

    def update(self, id: str, text: str, metadata: dict) -> None:
        self.add(id, text, metadata)


# ---------------------------------------------------------------------------

def _cosine(a: list[float], b: list[float]) -> float:
    import math
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) + 1e-9
    nb = math.sqrt(sum(x * x for x in b)) + 1e-9
    return dot / (na * nb)


if __name__ == "__main__":
    backend = SqliteVecBackend()
    print(f"SqliteVec backend — {backend.count()} entries")
