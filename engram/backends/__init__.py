"""Engram vector backend registry.

Import the active backend using :func:`get_backend`.
"""

from __future__ import annotations

import sys

from engram.backends.base import VectorBackend


class BackendUnavailableError(RuntimeError):
    """Raised when a vector backend's dependencies are installed but fail to load."""


_CHROMADB_HELP = (
    "ChromaDB failed to load ({error}).\n"
    "This usually means its compiled Rust bindings (chromadb_rust_bindings) do not\n"
    "match this Python or platform. Try one of:\n"
    "  * pip install --force-reinstall --no-cache-dir chromadb\n"
    "  * switch backend for one run:  ENGRAM_VECTOR_BACKEND=sqlitevec engram ...\n"
    "  * switch permanently: set \"vector_backend\": \"sqlitevec\" in ~/.engram/config.json\n"
    "Note: each backend keeps its own index, so re-run `engram mine` after switching."
)


_CHROMADB_MISSING = (
    "engram: ChromaDB is not installed for Python {version}, so Engram is using its\n"
    "built-in sqlitevec backend. Search works, but without an embedding model it\n"
    "matches words rather than meaning.\n"
    "For semantic search install ChromaDB when it supports this Python\n"
    "(pip install chromadb), or use Python 3.11-3.14. To silence this message set\n"
    "\"vector_backend\": \"sqlitevec\" in ~/.engram/config.json."
)


def _chromadb_installed() -> bool:
    import importlib.util
    return importlib.util.find_spec("chromadb") is not None


def get_backend(name: str = "chromadb", fallback: bool = False, **kwargs) -> VectorBackend:
    """Return an initialised VectorBackend for *name*.

    Args:
        name: ``"chromadb"`` (default) | ``"faiss"`` | ``"sqlitevec"``
        fallback: If ChromaDB is requested but not installed (e.g. on a Python
            it has no build for), warn on stderr and return the default
            sqlitevec backend instead of failing. *kwargs* are ChromaDB's, so
            they are not passed on. A ChromaDB that is installed but broken
            still raises :class:`BackendUnavailableError`.
        **kwargs: forwarded to the backend constructor.
    """
    if name == "chromadb":
        if fallback and not _chromadb_installed():
            print(_CHROMADB_MISSING.format(version=".".join(map(str, sys.version_info[:2]))),
                  file=sys.stderr)
            from engram.backends.sqlitevec_backend import SqliteVecBackend
            return SqliteVecBackend()
        try:
            from engram.backends.chromadb_backend import ChromaDBBackend
            return ChromaDBBackend(**kwargs)
        except (ImportError, OSError) as exc:
            raise BackendUnavailableError(_CHROMADB_HELP.format(error=exc)) from exc
    if name == "faiss":
        from engram.backends.faiss_backend import FaissBackend
        return FaissBackend(**kwargs)
    if name == "sqlitevec":
        from engram.backends.sqlitevec_backend import SqliteVecBackend
        return SqliteVecBackend(**kwargs)
    raise ValueError(f"Unknown vector backend '{name}'. Choose: chromadb | faiss | sqlitevec")


def backend_from_config(cfg: dict, fallback: bool = True) -> VectorBackend:
    """The backend Engram's CLI, MCP server and watcher use: the configured
    vector backend, plus the keyword index when ``keyword_search`` is on."""
    backend = get_backend(cfg.get("vector_backend", "chromadb"), fallback=fallback)
    if cfg.get("keyword_search"):
        from engram.keyword_index import with_keyword_index
        backend = with_keyword_index(backend, cfg)
    return backend


__all__ = ["BackendUnavailableError", "VectorBackend", "backend_from_config", "get_backend"]
