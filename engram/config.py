"""Engram configuration — loads and persists ~/.engram/config.json."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_CONFIG: dict[str, Any] = {
    "chateau_path": "~/.engram/chateau",
    "vector_backend": "chromadb",
    "decay_factor": 0.005,
    "decay_max_days": 90,
    # Keyword boost on top of semantic search (0 turns it off). 0.3 raised
    # LongMemEval R@5 from 0.968 to 0.974; see benchmarks/BENCHMARKS.md.
    "hybrid_weight": 0.3,
    # Boost memories dated near a time the query names ("two weeks ago"), and
    # index a short summary of the preferences/concerns in each user message
    # (engram.temporal, engram.preferences). Together with hybrid_weight these
    # raised LongMemEval R@5 from 0.974 to 0.982.
    "temporal_weight": 0.4,
    "preference_summaries": True,
    # Replace API keys, tokens and passwords with [REDACTED:...] before a
    # drawer is saved (engram.redact). Off: drawers stay exactly as written.
    "redact_secrets": False,
    # Full-text keyword index (SQLite FTS5, BM25) searched alongside the
    # embeddings, merged by reciprocal rank fusion (engram.keyword_index).
    "keyword_search": True,
    # Auto-recall for Claude Code (engram.recall, `engram install-hooks`): how
    # many memories at most, how relevant they must be (meaning similarity
    # 0..1), wings never shown, and whether to rerank (slower).
    "recall": True,
    "recall_max": 3,
    "recall_min_relevance": 0.30,
    "recall_preference_min_relevance": 0.20,  # saved preferences: a lower bar, see engram.recall
    "recall_other_min_relevance": 0.55,  # memories from a different project than the one open
    "recall_exclude_wings": ["library"],
    "recall_rerank": False,
    # Optional local cross-encoder that reorders the top results
    # (engram.reranker). Off by default; turning it on downloads a ~90 MB
    # model once to ~/.engram/models/.
    "reranker": False,
    "rerank_top": 20,
    # Size of the "key facts" part of the wake-up note (engram wake-up), in
    # tokens (estimated as 4 characters each). Pinned facts first, then newest.
    "l1_budget_tokens": 120,
    "collection_name": "engram_drawers",
    "people_map": {},
}

ENGRAM_DIR = Path("~/.engram").expanduser()
CONFIG_PATH = ENGRAM_DIR / "config.json"
WING_CONFIG_PATH = ENGRAM_DIR / "wing_config.json"
IDENTITY_PATH = ENGRAM_DIR / "identity.txt"


def ensure_engram_dir() -> None:
    """Create ~/.engram and its subdirectories if they don't exist."""
    ENGRAM_DIR.mkdir(parents=True, exist_ok=True)
    (ENGRAM_DIR / "chateau").mkdir(exist_ok=True)
    (ENGRAM_DIR / "agents").mkdir(exist_ok=True)
    (ENGRAM_DIR / "chroma_db").mkdir(exist_ok=True)


def load_config() -> dict[str, Any]:
    """Load config from ~/.engram/config.json, merging with defaults.

    ``ENGRAM_VECTOR_BACKEND`` overrides ``vector_backend`` without editing the file.
    """
    ensure_engram_dir()
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            with CONFIG_PATH.open() as f:
                cfg.update(json.load(f))
        except (json.JSONDecodeError, OSError):
            pass
    if os.environ.get("ENGRAM_VECTOR_BACKEND"):
        cfg["vector_backend"] = os.environ["ENGRAM_VECTOR_BACKEND"]
    return cfg


def save_config(cfg: dict[str, Any]) -> None:
    """Persist config to ~/.engram/config.json."""
    ensure_engram_dir()
    with CONFIG_PATH.open("w") as f:
        json.dump(cfg, f, indent=2)


def load_wing_config() -> dict[str, Any]:
    """Load wing mappings from ~/.engram/wing_config.json."""
    if WING_CONFIG_PATH.exists():
        try:
            with WING_CONFIG_PATH.open() as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_wing_config(wc: dict[str, Any]) -> None:
    ensure_engram_dir()
    with WING_CONFIG_PATH.open("w") as f:
        json.dump(wc, f, indent=2)


def get_chateau_path() -> Path:
    cfg = load_config()
    return Path(cfg["chateau_path"]).expanduser()


def get_identity() -> str:
    """Return the L0 identity text, or an empty string if not set."""
    if IDENTITY_PATH.exists():
        return IDENTITY_PATH.read_text().strip()
    return ""


if __name__ == "__main__":
    import pprint
    pprint.pprint(load_config())
