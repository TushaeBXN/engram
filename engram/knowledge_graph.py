"""Temporal knowledge graph — SQLite-backed entity/relationship store.

Every fact is a triple: (subject, predicate, object) with temporal bounds
valid_from / valid_until, so we can answer "who owned the auth migration
on 2026-01-20?" without discarding the old record.

Usage::

    kg = KnowledgeGraph()
    kg.add("Kai", "works_on", "Orion", valid_from="2025-06-01")
    kg.invalidate("Kai", "works_on", "Orion", ended="2026-03-01")
    for triple in kg.query("Kai"):
        print(triple)
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from engram.config import ENGRAM_DIR


DB_PATH = ENGRAM_DIR / "kg.db"


@dataclass
class Triple:
    """A temporal knowledge graph triple."""

    subject: str
    predicate: str
    object: str
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    confidence: float = 1.0
    source: str = ""           # e.g. "miner", "manual", "conflict_resolver"
    id: Optional[int] = None   # set by DB on insert

    def is_active(self, at: Optional[str] = None) -> bool:
        """Return True if the triple is active at *at* (ISO datetime string)."""
        now = at or datetime.now(timezone.utc).isoformat()
        if self.valid_from and now < self.valid_from:
            return False
        if self.valid_until and now > self.valid_until:
            return False
        return True

    def to_dict(self) -> dict:
        return asdict(self)


class KnowledgeGraph:
    """Manages the temporal KG stored in ~/.engram/kg.db.

    Args:
        db_path: Path to the SQLite database (default: ~/.engram/kg.db).
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._path = (db_path or DB_PATH).expanduser()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path))
        self._conn.row_factory = sqlite3.Row
        self._create_schema()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _create_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS triples (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                subject    TEXT NOT NULL,
                predicate  TEXT NOT NULL,
                object     TEXT NOT NULL,
                valid_from TEXT,
                valid_until TEXT,
                confidence REAL DEFAULT 1.0,
                source     TEXT DEFAULT ''
            );

            CREATE INDEX IF NOT EXISTS idx_subject    ON triples(subject);
            CREATE INDEX IF NOT EXISTS idx_predicate  ON triples(predicate);
            CREATE INDEX IF NOT EXISTS idx_object     ON triples(object);
            """
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def add(
        self,
        subject: str,
        predicate: str,
        obj: str,
        valid_from: Optional[str] = None,
        valid_until: Optional[str] = None,
        confidence: float = 1.0,
        source: str = "manual",
    ) -> Triple:
        """Insert a new triple.  Does NOT deduplicate — call :meth:`find`
        first if you want to avoid exact duplicates."""
        cur = self._conn.execute(
            """
            INSERT INTO triples (subject, predicate, object, valid_from, valid_until, confidence, source)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (subject, predicate, obj, valid_from, valid_until, confidence, source),
        )
        self._conn.commit()
        return Triple(
            subject=subject,
            predicate=predicate,
            object=obj,
            valid_from=valid_from,
            valid_until=valid_until,
            confidence=confidence,
            source=source,
            id=cur.lastrowid,
        )

    def invalidate(
        self,
        subject: str,
        predicate: str,
        obj: str,
        ended: Optional[str] = None,
    ) -> int:
        """Set valid_until on all matching active triples.

        Returns the number of rows updated.
        """
        ts = ended or datetime.now(timezone.utc).isoformat()
        cur = self._conn.execute(
            """
            UPDATE triples
               SET valid_until = ?
             WHERE subject = ? AND predicate = ? AND object = ?
               AND (valid_until IS NULL OR valid_until > ?)
            """,
            (ts, subject, predicate, obj, ts),
        )
        self._conn.commit()
        return cur.rowcount

    def delete_by_id(self, triple_id: int) -> bool:
        cur = self._conn.execute("DELETE FROM triples WHERE id = ?", (triple_id,))
        self._conn.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def query(
        self,
        entity: str,
        predicate: Optional[str] = None,
        active_at: Optional[str] = None,
    ) -> list[Triple]:
        """Return all triples where entity is subject OR object.

        Args:
            entity:    Entity name to look up.
            predicate: Optionally filter by predicate.
            active_at: ISO datetime; if given, filter to active triples.
        """
        sql = "SELECT * FROM triples WHERE (subject=? OR object=?)"
        params: list = [entity, entity]
        if predicate:
            sql += " AND predicate=?"
            params.append(predicate)
        sql += " ORDER BY valid_from DESC"
        rows = self._conn.execute(sql, params).fetchall()
        triples = [self._row_to_triple(r) for r in rows]
        if active_at:
            triples = [t for t in triples if t.is_active(active_at)]
        return triples

    def find(
        self,
        subject: Optional[str] = None,
        predicate: Optional[str] = None,
        obj: Optional[str] = None,
    ) -> list[Triple]:
        """Exact lookup by any combination of SPO fields."""
        clauses, params = [], []
        if subject:
            clauses.append("subject=?")
            params.append(subject)
        if predicate:
            clauses.append("predicate=?")
            params.append(predicate)
        if obj:
            clauses.append("object=?")
            params.append(obj)
        sql = "SELECT * FROM triples"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id DESC"
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_triple(r) for r in rows]

    def timeline(self, entity: str) -> list[Triple]:
        """Return all triples for *entity*, sorted chronologically."""
        triples = self.query(entity)
        triples.sort(key=lambda t: t.valid_from or "")
        return triples

    def all_triples(self) -> Iterator[Triple]:
        for row in self._conn.execute("SELECT * FROM triples ORDER BY id"):
            yield self._row_to_triple(row)

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM triples").fetchone()[0]

    def triples_missing_valid_from(self) -> list[Triple]:
        rows = self._conn.execute(
            "SELECT * FROM triples WHERE valid_from IS NULL"
        ).fetchall()
        return [self._row_to_triple(r) for r in rows]

    # ------------------------------------------------------------------
    # Conflict detection
    # ------------------------------------------------------------------

    def detect_tenure_conflicts(self) -> list[dict]:
        """Find triples where the same (subject, predicate) has overlapping
        active periods with different objects."""
        conflicts = []
        # Group by subject + predicate
        rows = self._conn.execute(
            "SELECT DISTINCT subject, predicate FROM triples"
        ).fetchall()
        for row in rows:
            s, p = row[0], row[1]
            variants = self.find(subject=s, predicate=p)
            active = [t for t in variants if t.is_active()]
            if len(active) > 1 and len({t.object for t in active}) > 1:
                conflicts.append(
                    {
                        "type": "tenure_conflict",
                        "subject": s,
                        "predicate": p,
                        "active_triples": [t.to_dict() for t in active],
                    }
                )
        return conflicts

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_triple(row: sqlite3.Row) -> Triple:
        return Triple(
            id=row["id"],
            subject=row["subject"],
            predicate=row["predicate"],
            object=row["object"],
            valid_from=row["valid_from"],
            valid_until=row["valid_until"],
            confidence=row["confidence"],
            source=row["source"],
        )

    def close(self) -> None:
        self._conn.close()


if __name__ == "__main__":
    kg = KnowledgeGraph()
    t = kg.add("Kai", "works_on", "Orion", valid_from="2025-06-01")
    print("Added:", t)
    for triple in kg.query("Kai"):
        print(" ", triple)
    print("Total triples:", kg.count())
