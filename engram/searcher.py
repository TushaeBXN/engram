"""Semantic search with recency weighting and optional keyword boosting.

Score formula::

    final_score = semantic_score * (1 + recency_boost)
                  * (1 + hybrid_weight * keyword_overlap)
                  * (1 + temporal_weight * temporal_closeness)
    recency_boost = decay_factor * max(0, decay_max_days - age_days)
    keyword_overlap = share of the query's keywords that appear in the hit
    temporal_closeness = 1 if the hit is dated near a time the query names
                         ("two weeks ago"), fading to 0 (engram.temporal)

Pinned drawers bypass decay and always receive a 1.0 recency multiplier.
Hybrid search is on by default (``hybrid_weight`` 0.3 in the default config;
a config without the key, or ``hybrid_weight`` 0, means semantic only). Change
it with the ``hybrid_weight`` config key, ``engram search --no-hybrid`` or the
``hybrid_weight`` argument. It helps when a query names exact things (people,
products, numbers) that embeddings blur together.

Usage::

    searcher = Searcher(backend, palace, config)
    results = searcher.search("auth migration decisions", wing="myapp", n=5)
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from engram.backends.base import VectorBackend
from engram.chateau import Chateau, Drawer
from engram.config import load_config
from engram.indexing import drawer_id_of
from engram.lineage import Lineage, annotate
from engram.temporal import temporal_closeness, time_reference


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
        palace: Chateau,
        config: Optional[dict] = None,
    ) -> None:
        self.backend = backend
        self.palace = palace
        self.config = config or load_config()
        path = getattr(palace, "path", None)
        self.lineage = Lineage(path) if path is not None else None

    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        n: int = 10,
        wing: Optional[str] = None,
        room: Optional[str] = None,
        hall: Optional[str] = None,
        no_decay: bool = False,
        hybrid_weight: Optional[float] = None,
        temporal_weight: Optional[float] = None,
        now: Optional[datetime] = None,
        rerank: Optional[bool] = None,
        keyword_search: Optional[bool] = None,
    ) -> list[dict]:
        """Semantic search with optional recency weighting.

        Args:
            query:    Natural-language query string.
            n:        Maximum results to return.
            wing:     Filter to this wing.
            room:     Filter to this room.
            hall:     Filter to this hall type.
            no_decay: If True, disable recency weighting.
            hybrid_weight: Keyword boost weight; None uses the config's
                      ``hybrid_weight`` (0.3 in the default config).
            temporal_weight: Boost for memories near a time the query names
                      ("two weeks ago", "last month"); None uses the config's
                      ``temporal_weight``.
            now:      Reference time for those phrases (default: the current time).
            keyword_search: Also run the full-text keyword index and merge
                      both rankings (reciprocal rank fusion). Needs a backend
                      from ``backend_from_config`` with ``keyword_search`` on;
                      None uses the config (off by default).
            rerank:   Reorder the top results with the local cross-encoder
                      (engram.reranker); None uses the config's ``reranker``
                      (off by default).

        Returns:
            List of result dicts sorted by final_score descending::

                {
                    "id": str,
                    "text": str,
                    "metadata": dict,
                    "semantic_score": float,
                    "recency_boost": float,
                    "keyword_overlap": float,
                    "temporal_closeness": float,
                    "final_score": float,
                    "pinned": bool,
                    "status": "current" | "superseded" | "disputed",
                    # plus, for corrected memories: "superseded_by",
                    # "current_id", "replaced_at", "reason", "supersedes",
                    # "disputed_with" (see engram.lineage.annotate)
                }

            A memory that was replaced is still returned, directly below
            its current replacement.
        """
        where = _build_where(wing, room, hall)
        # Over-fetch: several hits may be chunks of the same drawer.
        raw = self.backend.search(query, n=n * 5, where=where or None)

        decay_factor = self.config.get("decay_factor", 0.005)
        decay_max_days = self.config.get("decay_max_days", 90)
        if hybrid_weight is None:
            hybrid_weight = float(self.config.get("hybrid_weight", 0.0))
        query_kw = keywords(query) if hybrid_weight else set()
        if temporal_weight is None:
            temporal_weight = float(self.config.get("temporal_weight", 0.0))
        now = now or datetime.now(timezone.utc)
        time_ref = time_reference(query, now) if temporal_weight else None

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
            overlap = keyword_overlap(query_kw, hit["text"]) if query_kw else 0.0
            closeness = temporal_closeness(ts, now, time_ref) if time_ref else 0.0
            if final > 0:
                final *= (1.0 + hybrid_weight * overlap) * (1.0 + temporal_weight * closeness)

            scored.append(
                {
                    "id": drawer_id_of(hit),
                    "text": hit["text"],
                    "metadata": meta,
                    "semantic_score": round(sem, 4),
                    "recency_boost": round(recency_boost, 4),
                    "keyword_overlap": round(overlap, 4),
                    "temporal_closeness": round(closeness, 4),
                    "final_score": round(final, 4),
                    "pinned": bool(pinned),
                }
            )

        scored.sort(key=lambda x: x["final_score"], reverse=True)
        # Keep only the best-matching chunk of each drawer; its text is the snippet.
        best: dict[str, dict] = {}
        for hit in scored:
            best.setdefault(hit["id"], hit)
        results = list(best.values())
        if keyword_search is None:
            keyword_search = bool(self.config.get("keyword_search", False))
        if keyword_search and hasattr(self.backend, "keyword_search"):
            kw_hits = self.backend.keyword_search(query, n=n * 5, where=where or None)
            results = fuse_rankings(results, kw_hits)
        if rerank is None:
            rerank = bool(self.config.get("reranker", False))
        if rerank:
            from engram.reranker import get_reranker
            from engram.reranker import rerank as rerank_results
            model = get_reranker(self.config)
            if model is not None:
                results = rerank_results(query, results, model,
                                         top=int(self.config.get("rerank_top", 20)))
        # Lineage: label outdated memories and put their replacement first.
        if self.lineage is not None:
            results = annotate(results, self.lineage, self.palace.find_drawer)
        return results[:n]

    def get_by_id(self, drawer_id: str) -> Optional[Drawer]:
        """Fetch a drawer by ID from the palace."""
        for drawer in self.palace.iter_drawers():
            if drawer.id == drawer_id:
                return drawer
        return None


# ---------------------------------------------------------------------------

RRF_K = 60  # the usual reciprocal-rank-fusion constant


def fuse_rankings(results: list[dict], keyword_hits: list[dict], k: int = RRF_K) -> list[dict]:
    """Merge the meaning-search ranking with the keyword-index ranking.

    Each drawer scores ``1 / (k + rank)`` in every list it appears in, and the
    sum decides the order (reciprocal rank fusion). Drawers only the keyword
    index found are added with zero semantic scores. Each result gains a
    ``fusion_score``.
    """
    by_id = {r["id"]: r for r in results}
    fused = {rid: 1.0 / (k + i + 1) for i, rid in enumerate(by_id)}
    order: list[str] = []
    for hit in keyword_hits:
        did = drawer_id_of(hit)
        if did in order:
            continue
        order.append(did)
        if did not in by_id:
            meta = hit.get("metadata") or {}
            by_id[did] = {
                "id": did, "text": hit["text"], "metadata": meta,
                "semantic_score": 0.0, "recency_boost": 0.0, "keyword_overlap": 0.0,
                "temporal_closeness": 0.0, "final_score": 0.0,
                "pinned": bool(meta.get("pinned", False)),
            }
    for i, did in enumerate(order):
        fused[did] = fused.get(did, 0.0) + 1.0 / (k + i + 1)
    out = sorted(by_id.values(), key=lambda r: fused[r["id"]], reverse=True)
    for r in out:
        r["fusion_score"] = round(fused[r["id"]], 6)
    return out


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


_WORD = re.compile(r"[a-z0-9]+")

STOPWORDS = frozenset("""
a about above after again against all also am an and any are as at be because been
before being below between both but by can could did do does doing done down during
each few for from further get got had has have having he her here hers herself him
himself his how i if in into is it its itself just know last let like many me might
more most much must my myself never no nor not now of off on once one only or other
our ours ourselves out over own really said same say says she should so some still
such tell than that the their theirs them themselves then there these they thing
things this those through to too under until up us use used very was way we well
were what when where which while who whom why will with would yes yet you your
yours yourself yourselves ago day days time recently remember mentioned told
""".split())


def _stem(word: str) -> str:
    """Very light suffix stripping so "tomatoes"/"tomato", "booked"/"book" and
    "loved"/"love" reduce to the same key. Not a real stemmer, just enough to
    stop plurals and tenses from hiding a match."""
    if word.isdigit() or len(word) <= 3:
        return word
    if word.endswith(("ies", "ied")) and len(word) > 4:
        word = word[:-3] + "y"
    elif word.endswith(("sses", "xes", "ches", "shes", "oes", "zes")):
        word = word[:-2]
    elif word.endswith(("ing", "ed")) and len(word) > 4 + (word[-1] == "g"):
        word = word[:-3] if word.endswith("ing") else word[:-2]
        if len(word) > 2 and word[-1] == word[-2] and word[-1] not in "lsz":
            word = word[:-1]  # running -> run, planned -> plan
    elif word.endswith("s") and not word.endswith("ss"):
        word = word[:-1]
    if word.endswith("e") and len(word) > 3:
        word = word[:-1]
    return word


def keywords(text: str) -> set[str]:
    """Content words of *text*: lower-cased, stopwords dropped, lightly stemmed.

    Words shorter than three letters are dropped unless they contain a digit
    (years, quantities, versions).
    """
    return {
        _stem(w) for w in _WORD.findall(text.lower())
        if w not in STOPWORDS and (len(w) >= 3 or any(c.isdigit() for c in w))
    }


def keyword_overlap(query_keywords: set[str], text: str) -> float:
    """Fraction of *query_keywords* that occur in *text* (0.0 to 1.0)."""
    if not query_keywords:
        return 0.0
    return len(query_keywords & keywords(text)) / len(query_keywords)


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
    from engram.backends import get_backend
    from engram.chateau import Chateau
    cfg = load_config()
    palace = Chateau()
    backend = get_backend(cfg["vector_backend"])
    searcher = Searcher(backend, palace, cfg)
    print("Searcher ready.  Usage: searcher.search('your query')")
