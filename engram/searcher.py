"""Semantic search with recency weighting.

Score formula::

    final_score = semantic_score * (1 + recency_boost)
    recency_boost = decay_factor * max(0, decay_max_days - age_days)

Pinned drawers bypass decay and always receive a 1.0 recency multiplier.

Usage::

    searcher = Searcher(backend, palace, config)
    results = searcher.search("auth migration decisions", wing="myapp", n=5)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from engram.backends.base import VectorBackend
from engram.palace import Palace, Drawer
from engram.config import load_config


class Searcher:
    """Wraps the active VectorBackend and applies recency-weighted scoring.

    Args:
        backend:     Initialised VectorBackend.
        palace:      The active Palace (used to check pinned status).
        config:      Config dict (uses load_config() if None).
    """

    def __init__(
        self,
        backend: VectorBackend,
        palace: Palace,
        config: Optional[dict] = None,
    ) -> None:
        self.backend = backend
        self.palace = palace
        self.config = config or load_config()

    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        n: int = 10,
        wing: Optional[str] = None,
        room: Optional[str] = None,
        hall: Optional[str] = None,
        no_decay: bool = False,
    ) -> list[dict]:
        """Semantic search with optional recency weighting.

        Args:
            query:    Natural-language query string.
            n:        Maximum results to return.
            wing:     Filter to this wing.
            room:     Filter to this room.
            hall:     Filter to this hall type.
            no_decay: If True, disable recency weighting.

        Returns:
            List of result dicts sorted by final_score descending::

                {
                    "id": str,
                    "text": str,
                    "metadata": dict,
                    "semantic_score": float,
                    "recency_boost": float,
                    "final_score": float,
                    "pinned": bool,
                }
        """
        where = _build_where(wing, room, hall)
        raw = self.backend.search(query, n=n * 3, where=where or None)  # over-fetch then re-rank

        decay_factor = self.config.get("decay_factor", 0.005)
        decay_max_days = self.config.get("decay_max_days", 90)

        scored = []
        for hit in raw:
            meta = hit.get("metadata", {})
            pinned = meta.get("pinned", False)
            ts = meta.get("timestamp", "")
            age_days = _age_days(ts)

            if no_decay or pinned:
                recency_boost = 0.0
            else:
                recency_boost = decay_factor * max(0.0, float(decay_max_days) - age_days)

            sem = hit.get("score", 0.0)
            final = sem * (1.0 + recency_boost)

            scored.append(
                {
                    "id": hit["id"],
                    "text": hit["text"],
                    "metadata": meta,
                    "semantic_score": round(sem, 4),
                    "recency_boost": round(recency_boost, 4),
                    "final_score": round(final, 4),
                    "pinned": bool(pinned),
                }
            )

        scored.sort(key=lambda x: x["final_score"], reverse=True)
        return scored[:n]

    def get_by_id(self, drawer_id: str) -> Optional[Drawer]:
        """Fetch a drawer by ID from the palace."""
        for drawer in self.palace.iter_drawers():
            if drawer.id == drawer_id:
                return drawer
        return None


# ---------------------------------------------------------------------------

def _build_where(
    wing: Optional[str], room: Optional[str], hall: Optional[str]
) -> dict:
    where: dict = {}
    if wing:
        where["wing"] = wing
    if room:
        where["room"] = room
    if hall:
        where["hall"] = hall
    return where


def _age_days(timestamp: str) -> float:
    if not timestamp:
        return 0.0
    try:
        dt = datetime.fromisoformat(timestamp)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        return max(0.0, delta.total_seconds() / 86400)
    except ValueError:
        return 0.0


if __name__ == "__main__":
    from engram.palace import Palace
    from engram.backends import get_backend
    cfg = load_config()
    palace = Palace()
    backend = get_backend(cfg["vector_backend"])
    searcher = Searcher(backend, palace, cfg)
    print("Searcher ready.  Usage: searcher.search('your query')")
