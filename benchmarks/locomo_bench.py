"""LoCoMo benchmark runner for Engram.

Evaluates entity recall and event tracking against the LoCoMo dataset
of 100-turn social dialogues.

Usage::

    python benchmarks/locomo_bench.py --data-dir ~/datasets/locomo

Dataset: https://github.com/snap-research/locomo

# TODO: implement full LoCoMo evaluation loop
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


def run_locomo(data_dir: Path) -> dict:
    """Run LoCoMo evaluation against entity and event recall."""
    if not data_dir.exists():
        return {"error": f"Dataset not found at {data_dir}. See benchmarks/BENCHMARKS.md"}

    # Stub — real implementation mines dialogues and evaluates recall
    return {
        "status": "stub",
        "note": "Full LoCoMo evaluation not yet implemented.",
        "entity_recall": None,
        "event_recall": None,
        "target_entity_recall": 0.72,
        "target_event_recall": 0.69,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Engram LoCoMo benchmark")
    parser.add_argument("--data-dir", type=Path, default=Path("~/datasets/locomo").expanduser())
    args = parser.parse_args()

    print("=" * 60)
    print("ENGRAM BENCHMARK RUNNER — LoCoMo")
    print("=" * 60)

    t0 = time.time()
    results = run_locomo(args.data_dir)
    elapsed = time.time() - t0

    print(json.dumps(results, indent=2))
    print(f"\nCompleted in {elapsed:.2f}s")


if __name__ == "__main__":
    main()
