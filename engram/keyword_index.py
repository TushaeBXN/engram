"""Keyword index: a second, independent way to find memories.

Engram's main search finds text by meaning (embeddings). That misses some
memories outright, typically ones that share a rare word, a name or a number
with the question but are phrased differently. The keyword boost in
``Searcher`` can only reorder what the meaning search already found.

This module keeps a full-text index (SQLite FTS5 with BM25 ranking, part of
Python's standard library) of the same chunks the vector backend holds.
``Searcher`` runs both searches and merges the two rankings with reciprocal
rank fusion, the approach Hindsight uses for its recall.

It is off by default (``"keyword_search": false``). When on,
``backend_from_config`` wraps the vector backend in
``KeywordIndexedBackend``, which mirrors every add and delete into the index.
On first use an empty index is built from the drawers already on disk.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
import threading
from pathlib import Path
from typing import Optional

from engram.backends.base import VectorBackend

_COLUMNS = ("drawer_id", "wing", "room", "hall")
_WORD = re.compile(r"[\w']+", re.UNICODE)


class KeywordIndexUnavailable(RuntimeError):
    """SQLite was built without FTS5."""


def _match_query(query: str) -> Optional[str]:
    """An FTS5 query matching any content word of *query* (stopwords dropped)."""
    from engram.searcher import STOPWORDS

    words = []
    for w in _WORD.findall(query.lower()):
        w = w.strip("'")
        if w and w not in STOPWORDS and (len(w) >= 3 or any(c.isdigit() for c in w)) and w not in words:
            words.append(w)
    return " OR ".join('"' + w.replace('"', "") + '"' for w in words) or None


class KeywordIndex:
    """BM25 full-text index over chunks, stored in a SQLite file."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.created = not self.path.exists()
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        try:
            self._conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5("
                "id UNINDEXED, text, drawer_id UNINDEXED, wing UNINDEXED, room UNINDEXED, "
                "hall UNINDEXED, meta UNINDEXED, tokenize='porter unicode61')"
            )
        except sqlite3.OperationalError as exc:
            self._conn.close()
            raise KeywordIndexUnavailable(f"SQLite has no FTS5 support ({exc})") from exc

    def add_many(self, items: list[tuple[str, str, dict]]) -> None:
        rows = []
        for id, text, metadata in items:
            meta = metadata or {}
            rows.append((id, text, *(str(meta.get(c, "")) for c in _COLUMNS),
                         json.dumps(meta, default=str)))
        with self._lock, self._conn:
            self._conn.executemany("DELETE FROM chunks WHERE id = ?", [(r[0],) for r in rows])
            self._conn.executemany("INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?)", rows)

    def delete(self, id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM chunks WHERE id = ?", (id,))

    def delete_where(self, where: dict) -> None:
        clauses = {k: v for k, v in where.items() if k in _COLUMNS}
        if not clauses:
            return
        sql = " AND ".join(f"{k} = ?" for k in clauses)
        with self._lock, self._conn:
            self._conn.execute(f"DELETE FROM chunks WHERE {sql}", [str(v) for v in clauses.values()])

    def count(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT count(*) FROM chunks").fetchone()[0]

    def search(self, query: str, n: int = 10, where: Optional[dict] = None) -> list[dict]:
        """Best BM25 matches as ``{"id", "text", "metadata", "score"}`` (higher is better)."""
        match = _match_query(query)
        if not match:
            return []
        clauses = {k: v for k, v in (where or {}).items() if k in _COLUMNS}
        sql = "SELECT id, text, meta, bm25(chunks) FROM chunks WHERE chunks MATCH ?"
        params: list = [match]
        for k, v in clauses.items():
            sql += f" AND {k} = ?"
            params.append(str(v))
        sql += " ORDER BY bm25(chunks) LIMIT ?"
        params.append(int(n))
        with self._lock:
            try:
                rows = self._conn.execute(sql, params).fetchall()
            except sqlite3.OperationalError:
                return []
        return [{"id": id, "text": text, "metadata": json.loads(meta or "{}"), "score": -rank}
                for id, text, meta, rank in rows]

    def close(self) -> None:
        self._conn.close()


class KeywordIndexedBackend(VectorBackend):
    """A vector backend whose writes are mirrored into a ``KeywordIndex``.

    Every other attribute is passed through to the wrapped backend.
    """

    def __init__(self, inner: VectorBackend, index: KeywordIndex) -> None:
        self.inner = inner
        self.keywords = index

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def add(self, id: str, text: str, metadata: dict) -> None:
        self.inner.add(id, text, metadata)
        self.keywords.add_many([(id, text, metadata)])

    def add_many(self, items: list[tuple[str, str, dict]]) -> None:
        self.inner.add_many(items)
        self.keywords.add_many(items)

    def update(self, id: str, text: str, metadata: dict) -> None:
        self.inner.update(id, text, metadata)
        self.keywords.add_many([(id, text, metadata)])

    def delete(self, id: str) -> None:
        self.inner.delete(id)
        self.keywords.delete(id)

    def delete_where(self, where: dict) -> None:
        self.inner.delete_where(where)
        self.keywords.delete_where(where)

    def search(self, query: str, n: int = 10, where: Optional[dict] = None) -> list[dict]:
        return self.inner.search(query, n=n, where=where)

    def keyword_search(self, query: str, n: int = 10, where: Optional[dict] = None) -> list[dict]:
        return self.keywords.search(query, n=n, where=where)

    def count(self) -> int:
        return self.inner.count()


def build_from_chateau(index: KeywordIndex, chateau_path: Path) -> int:
    """Fill *index* with the chunks of every drawer on disk. Returns chunks added."""
    from engram.chateau import Chateau
    from engram.indexing import chunk_id, chunk_text

    items = []
    for drawer in Chateau(chateau_path=Path(chateau_path).expanduser()).iter_drawers():
        meta = {"wing": drawer.wing, "room": drawer.room, "hall": drawer.hall,
                "timestamp": drawer.timestamp, "pinned": drawer.pinned, "drawer_id": drawer.id}
        for n, chunk in enumerate(chunk_text(drawer.content)):
            items.append((chunk_id(drawer.id, n), chunk, {**meta, "chunk": n}))
    if items:
        index.add_many(items)
    return len(items)


def with_keyword_index(backend: VectorBackend, cfg: dict) -> VectorBackend:
    """Wrap *backend* with the keyword index named in *cfg*, building it on first
    use. Returns *backend* unchanged (with a warning) if FTS5 is unavailable."""
    from engram.config import ENGRAM_DIR

    path = Path(cfg.get("keyword_index_path") or ENGRAM_DIR / "keyword_index.db").expanduser()
    try:
        index = KeywordIndex(path)
    except KeywordIndexUnavailable as exc:
        print(f"engram: keyword search unavailable, using meaning search only ({exc})", file=sys.stderr)
        return backend
    if index.created and cfg.get("chateau_path"):
        n = build_from_chateau(index, cfg["chateau_path"])
        if n:
            print(f"engram: built the keyword index from {n} existing chunks", file=sys.stderr)
    return KeywordIndexedBackend(backend, index)
