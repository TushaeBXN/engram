"""Engram configuration — loads and persists ~/.engram/config.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_CONFIG: dict[str, Any] = {
    "palace_path": "~/.engram/palace",
    "vector_backend": "chromadb",
    "decay_factor": 0.005,
    "decay_max_days": 90,
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
    (ENGRAM_DIR / "palace").mkdir(exist_ok=True)
    (ENGRAM_DIR / "agents").mkdir(exist_ok=True)
    (ENGRAM_DIR / "chroma_db").mkdir(exist_ok=True)


def load_config() -> dict[str, Any]:
    """Load config from ~/.engram/config.json, merging with defaults."""
    ensure_engram_dir()
    if CONFIG_PATH.exists():
        try:
            with CONFIG_PATH.open() as f:
                on_disk = json.load(f)
            return {**DEFAULT_CONFIG, **on_disk}
        except (json.JSONDecodeError, OSError):
            pass
    return dict(DEFAULT_CONFIG)


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


def get_palace_path() -> Path:
    cfg = load_config()
    return Path(cfg["palace_path"]).expanduser()


def get_identity() -> str:
    """Return the L0 identity text, or an empty string if not set."""
    if IDENTITY_PATH.exists():
        return IDENTITY_PATH.read_text().strip()
    return ""


if __name__ == "__main__":
    import pprint
    pprint.pprint(load_config())
