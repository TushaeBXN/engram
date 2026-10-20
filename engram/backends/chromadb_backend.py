"""ChromaDB vector backend — the default château storage engine.

ChromaDB handles both embedding and storage locally (no API key needed).
Data is persisted under ~/.engram/chroma_db/.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from engram.backends.base import VectorBackend


class ChromaDBBackend(VectorBackend):
    """Wraps ChromaDB's local persistent client.

    Args:
        collection_name: Name of the ChromaDB collection to use.
        persist_directory: Path where ChromaDB stores its data.
    """

    def __init__(
        self,
        collection_name: str = "engram_drawers",
        persist_directory: str | Path = "~/.engram/chroma_db",
    ) -> None:
        import chromadb  # imported here — no network call at import time

        from engram import config, embedding

        # An embedding server from config gets its own collection, so the
        # default index is never mixed with vectors from another model.
        server = embedding.settings(config.load_config())
        if server:
            collection_name = f"{collection_name}__{embedding.collection_suffix(server)}"
        self._collection_name = collection_name
        self._persist_dir = str(Path(persist_directory).expanduser())
        Path(self._persist_dir).mkdir(parents=True, exist_ok=True)

        self._client = chromadb.PersistentClient(path=self._persist_dir)
        self._col = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
            embedding_function=(embedding.chroma_function(server) if server
                                else _cached_default_embedding_function()),
        )
        self.embedding_server = server
        if server and self._col.count() == 0:
            import sys
            print(f"engram: using the embedding server at {server['url']} ({server['model']}); its index is "
                  "empty. Run `engram reindex` to fill it from your memories.", file=sys.stderr)

    # ------------------------------------------------------------------

    def add(self, id: str, text: str, metadata: dict) -> None:
        self._col.upsert(ids=[id], documents=[text], metadatas=[_sanitise(metadata)])

    def add_many(self, items: list[tuple[str, str, dict]]) -> None:
        for start in range(0, len(items), _BATCH):
            batch = items[start:start + _BATCH]
            self._col.upsert(
                ids=[i for i, _, _ in batch],
                documents=[t for _, t, _ in batch],
                metadatas=[_sanitise(m) for _, _, m in batch],
            )

    def search(self, query: str, n: int = 10, where: dict | None = None) -> list[dict]:
        kwargs: dict[str, Any] = {
            "query_texts": [query],
            "n_results": min(n, max(1, self.count())),
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = _chroma_where(where)
        try:
            res = self._col.query(**kwargs)
        except Exception as exc:
            from engram.embedding import EmbeddingConfigError
            if isinstance(exc, EmbeddingConfigError):
                raise  # an embedding server that is down must not look like "no results"
            return []

        results = []
        ids = res.get("ids", [[]])[0]
        docs = res.get("documents", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        dists = res.get("distances", [[]])[0]
        for rid, doc, meta, dist in zip(ids, docs, metas, dists):
            results.append(
                {
                    "id": rid,
                    "text": doc,
                    "metadata": meta or {},
                    "score": 1.0 - dist,  # cosine distance → similarity
                }
            )
        return results

    def delete_where(self, where: dict) -> None:
        try:
            self._col.delete(where=_chroma_where(where))
        except Exception:
            pass

    def delete(self, id: str) -> None:
        try:
            self._col.delete(ids=[id])
        except Exception:
            pass

    def drop(self) -> None:
        """Delete the whole collection (the client stays open for other collections).

        Use this rather than deleting every entry: ChromaDB's HNSW index only
        marks deleted entries, and after a few rounds of delete-and-refill on
        one collection they crowd out real neighbours (recall fell from 1.00
        to 0.70 after ten rounds in testing).
        """
        self._client.delete_collection(self._collection_name)

    def count(self) -> int:
        try:
            return self._col.count()
        except Exception:
            return 0

    def update(self, id: str, text: str, metadata: dict) -> None:
        self._col.update(ids=[id], documents=[text], metadatas=[_sanitise(metadata)])


# ---------------------------------------------------------------------------

def _sanitise(metadata: dict) -> dict:
    """ChromaDB only accepts str/int/float/bool metadata values."""
    out: dict = {}
    for k, v in metadata.items():
        if isinstance(v, (str, int, float, bool)):
            out[k] = v
        else:
            out[k] = str(v)
    return out


if __name__ == "__main__":
    backend = ChromaDBBackend()
    print(f"ChromaDB collection '{backend._collection_name}' — {backend.count()} entries")


def _chroma_where(where: dict) -> dict:
    """ChromaDB needs ``$and`` to combine more than one metadata filter."""
    if len(where) <= 1:
        return dict(where)
    return {"$and": [{k: v} for k, v in where.items()]}


_BATCH = 256
_EMBEDDING_FUNCTION = None


def _cached_default_embedding_function():
    """ChromaDB's default embedding function with the model loaded once.

    ``DefaultEmbeddingFunction`` builds a new ``ONNXMiniLM_L6_V2`` (and ONNX
    session) on every call, which made each add ~0.2 s slower. This subclass
    keeps the same name ("default") and config, so existing collections are
    unaffected, but reuses one model instance.
    """
    global _EMBEDDING_FUNCTION
    if _EMBEDDING_FUNCTION is None:
        from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
        from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2

        class _CachedDefault(DefaultEmbeddingFunction):
            def __init__(self) -> None:
                super().__init__()
                self._model = ONNXMiniLM_L6_V2()

            def __call__(self, input):  # noqa: A002 - signature required by ChromaDB
                return self._model(input)

        _EMBEDDING_FUNCTION = _CachedDefault()
    return _EMBEDDING_FUNCTION
