"""Abstract VectorBackend interface — all backends must implement this."""

from __future__ import annotations

from abc import ABC, abstractmethod


class VectorBackend(ABC):
    """All three château backends share this interface.

    Implementors: ChromaDBBackend, FaissBackend, SqliteVecBackend.
    Selected via config.json ``"vector_backend"`` key.
    """

    # ------------------------------------------------------------------
    @abstractmethod
    def add(self, id: str, text: str, metadata: dict) -> None:
        """Embed *text* and store it under *id* with *metadata*."""
        ...

    @abstractmethod
    def search(self, query: str, n: int = 10, where: dict | None = None) -> list[dict]:
        """Semantic search for *query*.

        Returns a list of dicts with keys:
            ``id``, ``text``, ``metadata``, ``score``
        """
        ...

    @abstractmethod
    def delete(self, id: str) -> None:
        """Remove the entry with *id*."""
        ...

    @abstractmethod
    def count(self) -> int:
        """Return total number of stored embeddings."""
        ...

    @abstractmethod
    def update(self, id: str, text: str, metadata: dict) -> None:
        """Update the text/metadata of an existing entry."""
        ...


if __name__ == "__main__":
    print("VectorBackend — abstract base.  Use get_backend() to instantiate.")
