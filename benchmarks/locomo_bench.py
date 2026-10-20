"""LoCoMo benchmark runner for Engram.

Session-level retrieval recall on LoCoMo (10 long conversations between two
people, 1,986 questions), measured as the usual session-level evaluation does: for each
question, the share of its evidence sessions that appear among the top-k
retrieved sessions (k = 10), averaged over every question in all five
categories.

Each conversation is mined once with Engram's own pipeline (one room per
session, one verbatim drawer per turn, chunked index) and every question
about it is answered with Searcher, exactly as ``engram search`` would.

Usage::

    python benchmarks/locomo_bench.py ~/datasets/locomo/locomo10.json
    python benchmarks/locomo_bench.py locomo10.json --hybrid --temporal --preferences

Dataset: https://github.com/snap-research/locomo (data/locomo10.json)
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import tempfile
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DEFAULT_DATA_FILE = Path("~/datasets/locomo/locomo10.json").expanduser()

# Category numbering as used by the common LoCoMo runners.
CATEGORIES = {1: "single-hop", 2: "temporal", 3: "temporal-inference", 4: "open-domain", 5: "adversarial"}


def _locomo_date(value: str) -> Optional[datetime]:
    """LoCoMo dates look like "1:56 pm on 8 May, 2023"."""
    try:
        return datetime.strptime(value.strip(), "%I:%M %p on %d %B, %Y").replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return None


def _sessions(conversation: dict) -> list:
    """``(session_id, date, turns)`` for session_1, session_2, ... in order."""
    out = []
    n = 1
    while f"session_{n}" in conversation:
        out.append((f"session_{n}", _locomo_date(conversation.get(f"session_{n}_date_time", "")),
                    conversation[f"session_{n}"]))
        n += 1
    return out


def evidence_sessions(evidence: list) -> set:
    """Evidence dialog IDs ("D3:12") to session IDs ("session_3").

    Parsed as the common runners do (one leading ``D<n>:`` per entry) so
    the two scores are computed on the same evidence sets, malformed entries
    included.
    """
    sessions = set()
    for eid in evidence:
        m = re.match(r"D(\d+):", eid)
        if m:
            sessions.add(f"session_{m.group(1)}")
    return sessions


def _recall(ranked: list, gold: set, k: int) -> float:
    if not gold:
        return 1.0
    top = set(ranked[:k])
    return sum(1 for g in gold if g in top) / len(gold)


def _make_backend(backend_name: str, workdir: Path, shared_dir: Optional[Path], n: int):
    from engram.backends import get_backend
    if backend_name == "chromadb":
        # One client per run, one collection per conversation (see longmemeval_bench).
        return get_backend("chromadb", persist_directory=shared_dir / "chroma",
                           collection_name=f"locomo-{n}")
    if backend_name == "sqlitevec":
        return get_backend("sqlitevec", db_path=workdir / "vec.db")
    return get_backend(backend_name)


def run_locomo(data_file: Path, limit: Optional[int] = None, backend: str = "chromadb",
               top_k: int = 10, hybrid_weight: float = 0.0, temporal_weight: float = 0.0,
               preferences: bool = False, out: Optional[Path] = None,
               rerank: bool = False, rerank_top: int = 20, keywords: bool = False) -> dict:
    """Session recall@k on LoCoMo for every question in the first *limit* conversations."""
    from engram.chateau import Chateau
    from engram.convo_miner import ConvoMiner
    from engram.searcher import Searcher

    data_file = data_file.expanduser()
    if data_file.is_dir():
        data_file = data_file / "locomo10.json"
    if not data_file.exists():
        return {"error": f"Dataset not found at {data_file}. See benchmarks/BENCHMARKS.md"}
    data = json.loads(data_file.read_text())[:limit]

    scores: list = []
    recall5: list = []
    by_cat: dict = defaultdict(list)
    log = out.open("w") if out else None
    t0 = time.time()
    shared = tempfile.TemporaryDirectory() if backend == "chromadb" else None
    try:
        for n, sample in enumerate(data):
            sessions = _sessions(sample["conversation"])
            with tempfile.TemporaryDirectory() as tmp:
                workdir = Path(tmp)
                be = _make_backend(backend, workdir, Path(shared.name) if shared else None, n)
                if keywords:
                    from engram.keyword_index import KeywordIndex, KeywordIndexedBackend
                    be = KeywordIndexedBackend(be, KeywordIndex(workdir / "keywords.db"))
                palace = Chateau(chateau_path=workdir / "chateau")
                cfg = {"decay_factor": 0.0, "decay_max_days": 0, "preference_summaries": preferences,
                       "rerank_top": rerank_top}
                miner = ConvoMiner(palace, be, cfg)
                for sess_id, date, turns in sessions:
                    # Both people are users of the memory; speaker names stay in the text,
                    # as they would in any saved transcript.
                    messages = [
                        {"role": "user", "text": f'{t.get("speaker", "?")} said, "{t.get("text", "")}"',
                         "timestamp": date.isoformat() if date else "",
                         "id": f'{sample.get("sample_id", n)}:{t.get("dia_id", i)}'}
                        for i, t in enumerate(turns)
                    ]
                    miner.store_messages(messages, wing="locomo", room=sess_id)
                # Questions are asked after the last session.
                now = max((d for _, d, _ in sessions if d), default=None)
                searcher = Searcher(be, palace, cfg)
                for qa in sample["qa"]:
                    hits = searcher.search(qa["question"], n=50, no_decay=True,
                                           hybrid_weight=hybrid_weight,
                                           temporal_weight=temporal_weight, now=now, rerank=rerank,
                                           keyword_search=keywords)
                    ranked: list = []
                    for hit in hits:
                        sid = hit["metadata"].get("room")
                        if sid and sid not in ranked:
                            ranked.append(sid)
                    gold = evidence_sessions(qa.get("evidence", []))
                    r = _recall(ranked, gold, top_k)
                    scores.append(r)
                    recall5.append(_recall(ranked, gold, 5))
                    cat = CATEGORIES.get(qa.get("category"), f"cat-{qa.get('category')}")
                    by_cat[cat].append(r)
                    if log:
                        log.write(json.dumps({"sample_id": sample.get("sample_id", n),
                                              "question": qa["question"], "category": cat,
                                              "gold": sorted(gold), "ranked": ranked[:top_k],
                                              f"recall@{top_k}": r}) + "\n")
                if backend == "chromadb":
                    be.drop()
            print(f"  [{n + 1:2}/{len(data)}] {sample.get('sample_id', n)}: {len(sessions)} sessions, "
                  f"{len(sample['qa'])} questions — R@{top_k} so far {statistics.mean(scores):.3f} "
                  f"({time.time() - t0:.0f}s)", flush=True)
    finally:
        if log:
            log.close()
        if shared:
            shared.cleanup()

    return {
        "conversations": len(data),
        "questions": len(scores),
        "backend": backend,
        "top_k": top_k,
        "hybrid_weight": hybrid_weight,
        "temporal_weight": temporal_weight,
        "preferences": preferences,
        "rerank": rerank,
        "keywords": keywords,
        "seconds": round(time.time() - t0, 1),
        f"recall@{top_k}": round(statistics.mean(scores), 4) if scores else None,
        "recall@5": round(statistics.mean(recall5), 4) if recall5 else None,
        "perfect": sum(1 for s in scores if s >= 1.0),
        "zero": sum(1 for s in scores if s == 0.0),
        "by_category": {cat: {"n": len(v), f"recall@{top_k}": round(statistics.mean(v), 4)}
                        for cat, v in sorted(by_cat.items())},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Engram LoCoMo benchmark (session recall@k)")
    parser.add_argument("data_file", nargs="?", type=Path, default=DEFAULT_DATA_FILE,
                        help="locomo10.json (or the directory containing it)")
    parser.add_argument("--data-dir", type=Path, help="Alias for DATA_FILE (kept for compatibility)")
    parser.add_argument("--limit", type=int, help="Only evaluate the first N conversations")
    parser.add_argument("--backend", default="chromadb", choices=["chromadb", "sqlitevec", "faiss"])
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--hybrid", action="store_true", help="Keyword boost (hybrid_weight 0.3)")
    parser.add_argument("--temporal", action="store_true", help="Time boost (temporal_weight 0.4)")
    parser.add_argument("--preferences", action="store_true", help="Index preference summaries")
    parser.add_argument("--rerank", action="store_true", help="Reorder top results with the local reranker")
    parser.add_argument("--keywords", action="store_true",
                        help="Also search the full-text keyword index and merge the rankings")
    parser.add_argument("--rerank-top", type=int, default=20, help="Results the reranker reorders")
    parser.add_argument("--out", type=Path, help="Write per-question results as JSONL")
    args = parser.parse_args()

    print("=" * 60)
    print("ENGRAM BENCHMARK RUNNER — LoCoMo (session recall)")
    print("=" * 60)
    from longmemeval_bench import _raise_open_file_limit
    _raise_open_file_limit()
    results = run_locomo(args.data_dir or args.data_file, limit=args.limit, backend=args.backend,
                         top_k=args.top_k, hybrid_weight=0.3 if args.hybrid else 0.0,
                         temporal_weight=0.4 if args.temporal else 0.0,
                         preferences=args.preferences, out=args.out,
                         rerank=args.rerank, rerank_top=args.rerank_top, keywords=args.keywords)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
