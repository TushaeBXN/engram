"""Engram vector backend registry.

Import the active backend using :func:`get_backend`.
"""

from __future__ import annotations

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


def get_backend(name: str = "chromadb", **kwargs) -> VectorBackend:
    """Return an initialised VectorBackend for *name*.

    Args:
        name: ``"chromadb"`` (default) | ``"faiss"`` | ``"sqlitevec"``
        **kwargs: forwarded to the backend constructor.
    """
    if name == "chromadb":
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


__all__ = ["BackendUnavailableError", "VectorBackend", "get_backend"]
