"""Engram vector backend registry.

Import the active backend using :func:`get_backend`.
"""

from __future__ import annotations

from engram.backends.base import VectorBackend


def get_backend(name: str = "chromadb", **kwargs) -> VectorBackend:
    """Return an initialised VectorBackend for *name*.

    Args:
        name: ``"chromadb"`` (default) | ``"faiss"`` | ``"sqlitevec"``
        **kwargs: forwarded to the backend constructor.
    """
    if name == "chromadb":
        from engram.backends.chromadb_backend import ChromaDBBackend
        return ChromaDBBackend(**kwargs)
    if name == "faiss":
        from engram.backends.faiss_backend import FaissBackend
        return FaissBackend(**kwargs)
    if name == "sqlitevec":
        from engram.backends.sqlitevec_backend import SqliteVecBackend
        return SqliteVecBackend(**kwargs)
    raise ValueError(f"Unknown vector backend '{name}'. Choose: chromadb | faiss | sqlitevec")


__all__ = ["VectorBackend", "get_backend"]
