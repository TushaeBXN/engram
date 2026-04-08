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
import statistics
import sys
import time
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
        "target": "8-10x",
    }

    code_ratios = [
        compression_ratio(s, compress(s, is_code=True)) for s in CODE_SAMPLES
    ]
    results["code"] = {
        "mean": round(statistics.mean(code_ratios), 2),
        "min": round(min(code_ratios), 2),
        "max": round(max(code_ratios), 2),
        "target": "4-6x",
    }

    mixed_ratios = [
        compression_ratio(s, compress(s, is_code=(".py" in s or "def " in s)))
        for s in MIXED_SAMPLES
    ]
    results["mixed"] = {
        "mean": round(statistics.mean(mixed_ratios), 2),
        "min": round(min(mixed_ratios), 2),
        "max": round(max(mixed_ratios), 2),
        "target": "~6x",
    }

    return results


def run_longmemeval(data_dir: Path) -> dict:
    """Run LongMemEval evaluation.  Requires dataset download.

    # TODO: implement full LongMemEval evaluation loop
    """
    sessions_dir = data_dir / "sessions"
    if not sessions_dir.exists():
        return {"error": f"Dataset not found at {data_dir}. See benchmarks/BENCHMARKS.md"}

    from engram.palace import Palace
    from engram.backends import get_backend
    from engram.miner import Miner
    from engram.searcher import Searcher

    palace = Palace()
    backend = get_backend("chromadb")
    searcher = Searcher(backend, palace)

    # Stub — real implementation mines sessions and evaluates QA
    return {
        "status": "stub",
        "note": "Full LongMemEval evaluation not yet implemented.",
        "single_session_f1": None,
        "multi_session_f1": None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Engram LongMemEval benchmark")
    parser.add_argument("--data-dir", type=Path, default=Path("~/datasets/longmemeval").expanduser())
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
        status = "✓" if r["mean"] >= 2.0 else "✗"
        print(f"  {status} {category:10s}: {r['mean']:.1f}x mean  (target: {r['target']})")
    print(f"  Completed in {elapsed:.2f}s")

    if args.compression_only:
        print("\n" + json.dumps(comp_results, indent=2))
        return

    print("\n[2/2] LongMemEval QA:")
    lme_results = run_longmemeval(args.data_dir)
    print("  " + json.dumps(lme_results, indent=2))

    print("\nFull results:")
    print(json.dumps({"compression": comp_results, "longmemeval": lme_results}, indent=2))


if __name__ == "__main__":
    main()
