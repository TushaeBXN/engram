"""Tests for engram.backends — backend selection and load failures."""

import sys

import pytest

from engram import config as config_mod
from engram.backends import BackendUnavailableError, get_backend


@pytest.fixture
def broken_chromadb(monkeypatch):
    """Simulate chromadb's Rust bindings failing to load."""
    monkeypatch.setitem(sys.modules, "chromadb_rust_bindings", None)
    for name in list(sys.modules):
        if name == "chromadb" or name.startswith("chromadb."):
            monkeypatch.delitem(sys.modules, name)


def test_broken_chromadb_raises_actionable_error(broken_chromadb, tmp_path):
    with pytest.raises(BackendUnavailableError) as excinfo:
        get_backend("chromadb", persist_directory=tmp_path)
    message = str(excinfo.value)
    assert "chromadb_rust_bindings" in message
    assert "ENGRAM_VECTOR_BACKEND=sqlitevec" in message


def test_unknown_backend_still_raises_value_error():
    with pytest.raises(ValueError):
        get_backend("nonsense")


@pytest.fixture
def isolated_config(monkeypatch, tmp_path):
    monkeypatch.setattr(config_mod, "ENGRAM_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.delenv("ENGRAM_VECTOR_BACKEND", raising=False)
    return tmp_path


def test_env_var_overrides_vector_backend(isolated_config, monkeypatch):
    monkeypatch.setenv("ENGRAM_VECTOR_BACKEND", "sqlitevec")
    assert config_mod.load_config()["vector_backend"] == "sqlitevec"


def test_env_var_overrides_config_file(isolated_config, monkeypatch):
    config_mod.save_config({"vector_backend": "faiss"})
    monkeypatch.setenv("ENGRAM_VECTOR_BACKEND", "sqlitevec")
    assert config_mod.load_config()["vector_backend"] == "sqlitevec"


def test_config_file_used_without_env_var(isolated_config):
    config_mod.save_config({"vector_backend": "faiss"})
    assert config_mod.load_config()["vector_backend"] == "faiss"
