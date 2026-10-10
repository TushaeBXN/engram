"""Shared fixtures."""

import pytest

from engram import agents, config, knowledge_graph, layers


@pytest.fixture
def engram_home(monkeypatch, tmp_path):
    """Point every ~/.engram path at a throwaway directory.

    Several modules compute their paths from ENGRAM_DIR at import time, so
    setting HOME alone is not enough: each constant is patched as well.
    Uses the sqlitevec backend so tests need no compiled ChromaDB bindings
    and no embedding-model download.
    """
    home = tmp_path / "home"
    engram_dir = home / ".engram"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("ENGRAM_VECTOR_BACKEND", "sqlitevec")
    monkeypatch.setattr(config, "ENGRAM_DIR", engram_dir)
    monkeypatch.setattr(config, "CONFIG_PATH", engram_dir / "config.json")
    monkeypatch.setattr(config, "WING_CONFIG_PATH", engram_dir / "wing_config.json")
    monkeypatch.setattr(config, "IDENTITY_PATH", engram_dir / "identity.txt")
    monkeypatch.setattr(layers, "_L1_PATH", engram_dir / "l1_facts.es")
    monkeypatch.setattr(agents, "AGENTS_DIR", engram_dir / "agents")
    monkeypatch.setattr(knowledge_graph, "DB_PATH", engram_dir / "kg.db")
    return engram_dir
