"""LongMemEval benchmark runner for Engram.

Evaluates single-session and multi-session QA performance against the
LongMemEval dataset.  Also supports a --compression-only mode that
measures ES compression ratios without requiring the dataset.

Usage::

    python benchmarks/longmemeval_bench.py --data-dir ~/datasets/longmemeval
    python benchmarks/longmemeval_bench.py --compression-only

Dataset: https://github.com/xiaowu0162/LongMemEval
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import tempfile
import time
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# ES compression benchmark (no dataset required)
# ---------------------------------------------------------------------------

FACTUAL_SAMPLES = [
    "The authentication module is a critical component that has a dependency on "
    "the database and is responsible for verifying user credentials. It was completed "
    "by Maya and will be deprecated in the next release because of security concerns.",

    "The deployment pipeline uses GitHub Actions for continuous integration and "
    "continuous deployment to the production environment. The pipeline runs unit tests, "
    "integration tests, and end-to-end tests before deploying to the Kubernetes cluster.",

    "The user interface was redesigned with a focus on accessibility and mobile "
    "responsiveness. The new design uses Tailwind CSS for styling and React for the "
    "component library. The redesign was completed in Q1 2026.",
]

CODE_SAMPLES = [
    "def authenticate_user(username: str, password: str, token: str = None) -> bool:\n"
    "    if not username or not password:\n"
    "        raise ValueError('Username and password are required')\n"
    "    return verify_credentials(username, password)\n",

    "async def fetch_user_profile(user_id: int, include_preferences: bool = False) -> dict:\n"
    "    user = await db.get_user(user_id)\n"
    "    if include_preferences:\n"
    "        user['preferences'] = await db.get_preferences(user_id)\n"
    "    return user\n",
]

MIXED_SAMPLES = FACTUAL_SAMPLES[:2] + CODE_SAMPLES[:1]


def run_compression_benchmark() -> dict:
    """Measure ES compression ratios across sample types."""
    from engram.shorthand import compress, compression_ratio

    results = {}

    factual_ratios = [
        compression_ratio(s, compress(s)) for s in FACTUAL_SAMPLES
    ]
    results["factual"] = {
        "mean": round(statistics.mean(factual_ratios), 2),
        "min": round(min(factual_ratios), 2),
        "max": round(max(factual_ratios), 2),
        "target": 1.5,
    }

    code_ratios = [
        compression_ratio(s, compress(s, is_code=True)) for s in CODE_SAMPLES
    ]
    results["code"] = {
        "mean": round(statistics.mean(code_ratios), 2),
        "min": round(min(code_ratios), 2),
        "max": round(max(code_ratios), 2),
        "target": 1.1,
    }

    mixed_ratios = [
        compression_ratio(s, compress(s, is_code=(".py" in s or "def " in s)))
        for s in MIXED_SAMPLES
    ]
    results["mixed"] = {
        "mean": round(statistics.mean(mixed_ratios), 2),
        "min": round(min(mixed_ratios), 2),
        "max": round(max(mixed_ratios), 2),
        "target": 1.4,
    }

    return results


DEFAULT_DATA_FILE = Path("~/datasets/longmemeval/longmemeval_s_cleaned.json")
RECALL_KS = (1, 3, 5, 10)


def _ndcg_any(ranked: list[str], gold: set[str], k: int) -> float:
    gains = [1.0 / math.log2(i + 2) for i, sid in enumerate(ranked[:k]) if sid in gold]
    ideal = sum(1.0 / math.log2(i + 2) for i in range(min(len(gold), k)))
    return sum(gains) / ideal if ideal else 0.0


def rank_sessions(entry: dict, workdir: Path, backend_name: str, roles: str) -> list[str]:
    """Mine one question's haystack with Engram's pipeline and rank its sessions.

    Each haystack session becomes a room; every message goes through
    ConvoMiner (verbatim drawer, chunked index) and the question is answered
    with Searcher, exactly as `engram search` would. Ranked drawers are mapped
    back to their session, keeping each session's best rank.
    """
    from engram.backends import get_backend
    from engram.chateau import Chateau
    from engram.convo_miner import ConvoMiner
    from engram.searcher import Searcher

    palace = Chateau(chateau_path=workdir / "chateau")
    if backend_name == "chromadb":
        backend = get_backend("chromadb", persist_directory=workdir / "chroma",
                              collection_name="bench")
    elif backend_name == "sqlitevec":
        backend = get_backend("sqlitevec", db_path=workdir / "vec.db")
    else:
        backend = get_backend(backend_name)
    cfg = {"decay_factor": 0.0, "decay_max_days": 0}
    miner = ConvoMiner(palace, backend, cfg)

    for sess_id, session in zip(entry["haystack_session_ids"], entry["haystack_sessions"]):
        messages = [
            {"role": turn["role"], "text": turn["content"], "timestamp": "",
             "id": f"{sess_id}:{i}"}
            for i, turn in enumerate(session)
            if roles == "all" or turn["role"] == "user"
        ]
        miner.store_messages(messages, wing="bench", room=sess_id)

    hits = Searcher(backend, palace, cfg).search(entry["question"], n=50, no_decay=True)
    ranked: list[str] = []
    for hit in hits:
        sid = hit["metadata"].get("room")
        if sid and sid not in ranked:
            ranked.append(sid)
    return ranked


def run_longmemeval(data_file: Path, limit: int | None = None, backend: str = "chromadb",
                    roles: str = "all", out: Path | None = None) -> dict:
    """Session-level retrieval recall on LongMemEval (same metric as MemPalace's "raw" R@k).

    For each question a fresh château and index are built from its haystack
    sessions; a hit is counted at k if any gold answer session ranks in the
    top k (recall_any@k). recall_all@5 and NDCG@10 are reported as well.
    """
    data_file = data_file.expanduser()
    if data_file.is_dir():
        data_file = data_file / "longmemeval_s_cleaned.json"
    if not data_file.exists():
        return {"error": f"Dataset not found at {data_file}. See benchmarks/BENCHMARKS.md"}

    data = json.loads(data_file.read_text())
    if limit:
        data = data[:limit]

    totals: dict[str, list[float]] = defaultdict(list)
    by_type: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    log = out.open("w") if out else None
    t0 = time.time()

    try:
        for i, entry in enumerate(data, 1):
            gold = set(entry["answer_session_ids"])
            with tempfile.TemporaryDirectory() as tmp:
                ranked = rank_sessions(entry, Path(tmp), backend, roles)
            scores = {f"recall_any@{k}": float(bool(gold & set(ranked[:k]))) for k in RECALL_KS}
            scores["recall_all@5"] = float(gold <= set(ranked[:5]))
            scores["ndcg_any@10"] = _ndcg_any(ranked, gold, 10)
            for name, v in scores.items():
                totals[name].append(v)
                by_type[entry["question_type"]][name].append(v)
            if log:
                log.write(json.dumps({"question_id": entry["question_id"],
                                      "question_type": entry["question_type"],
                                      "gold": sorted(gold), "ranked": ranked[:10], **scores}) + "\n")
            if i % 25 == 0 or i == len(data):
                r5 = statistics.mean(totals["recall_any@5"])
                print(f"  [{i:4}/{len(data)}] R@5 so far {r5:.3f}  ({time.time() - t0:.0f}s)",
                      flush=True)
    finally:
        if log:
            log.close()

    return {
        "questions": len(data),
        "backend": backend,
        "roles": roles,
        "seconds": round(time.time() - t0, 1),
        **{name: round(statistics.mean(v), 4) for name, v in totals.items()},
        "by_type": {
            qtype: {"n": len(m["recall_any@5"]), "recall_any@5": round(statistics.mean(m["recall_any@5"]), 4)}
            for qtype, m in sorted(by_type.items())
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Engram LongMemEval benchmark")
    parser.add_argument("data_file", nargs="?", type=Path, default=DEFAULT_DATA_FILE,
                        help="longmemeval_s_cleaned.json (or the directory containing it)")
    parser.add_argument("--data-dir", type=Path, help="Alias for DATA_FILE (kept for compatibility)")
    parser.add_argument("--limit", type=int, help="Only evaluate the first N questions")
    parser.add_argument("--backend", default="chromadb", choices=["chromadb", "sqlitevec", "faiss"])
    parser.add_argument("--roles", default="all", choices=["all", "user"],
                        help="Index all messages (Engram's default) or user turns only")
    parser.add_argument("--out", type=Path, help="Write per-question results as JSONL")
    parser.add_argument("--compression-only", action="store_true")
    args = parser.parse_args()

    print("=" * 60)
    print("ENGRAM BENCHMARK RUNNER — LongMemEval")
    print("=" * 60)

    # Always run compression benchmark
    print("\n[1/2] ES Compression ratios:")
    t0 = time.time()
    comp_results = run_compression_benchmark()
    elapsed = time.time() - t0
    for category, r in comp_results.items():
        status = "✓" if r["mean"] >= r["target"] else "✗"
        print(f"  {status} {category:10s}: {r['mean']:.1f}x mean  (target: ≥{r['target']}x)")
    print(f"  Completed in {elapsed:.2f}s")

    if args.compression_only:
        print("\n" + json.dumps(comp_results, indent=2))
        return

    print("\n[2/2] LongMemEval retrieval (session recall):")
    lme_results = run_longmemeval(args.data_dir or args.data_file, limit=args.limit,
                                  backend=args.backend, roles=args.roles, out=args.out)
    print("  " + json.dumps(lme_results, indent=2))


if __name__ == "__main__":
    main()
