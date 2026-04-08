"""FAISS vector backend — speed-optimised, in-memory with disk persistence.

Uses sentence-transformers for embedding (falls back to a hash-based stub
when unavailable, so imports always succeed).  Install with::

    pip install engram[faiss]
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path

from engram.backends.base import VectorBackend

_EMBED_DIM = 384  # all-MiniLM-L6-v2 output dimension


def _get_embedder():
    """Return a sentence-transformer model, or a deterministic stub."""
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
        return SentenceTransformer("all-MiniLM-L6-v2")
    except Exception:
        return None


class FaissBackend(VectorBackend):
    """FAISS flat-L2 index with JSON side-car for metadata.

    Args:
        index_path: Directory to persist index + metadata.
    """

    def __init__(self, index_path: str | Path = "~/.engram/faiss_index") -> None:
        try:
            import faiss  # type: ignore
            self._faiss = faiss
        except ImportError as exc:
            raise ImportError(
                "faiss-cpu is required for the faiss backend. "
                "Install with: pip install engram[faiss]"
            ) from exc

        self._path = Path(index_path).expanduser()
        self._path.mkdir(parents=True, exist_ok=True)
        self._index_file = self._path / "index.faiss"
        self._meta_file = self._path / "metadata.pkl"

        self._embedder = _get_embedder()
        self._meta: dict[int, dict] = {}  # int_id → {"id": str, "text": str, "metadata": dict}
        self._id_map: dict[str, int] = {}  # str_id → int_id
        self._next_int_id = 0

        self._index = faiss.IndexFlatIP(_EMBED_DIM)  # inner-product = cosine on unit vecs
        self._load()

    # ------------------------------------------------------------------

    def _embed(self, text: str):
        import numpy as np  # type: ignore
        if self._embedder:
            vec = self._embedder.encode([text], normalize_embeddings=True)
            return vec.astype("float32")
        # deterministic stub — l2-norm of char hash values
        import hashlib
        raw = hashlib.sha256(text.encode()).digest()
        arr = np.frombuffer(raw, dtype=np.uint8).astype("float32")
        arr = arr[:_EMBED_DIM] if len(arr) >= _EMBED_DIM else np.pad(arr, (0, _EMBED_DIM - len(arr)))
        norm = np.linalg.norm(arr)
        return (arr / (norm + 1e-9)).reshape(1, -1)

    def _save(self) -> None:
        self._faiss.write_index(self._index, str(self._index_file))
        with self._meta_file.open("wb") as f:
            pickle.dump({"meta": self._meta, "id_map": self._id_map, "next": self._next_int_id}, f)

    def _load(self) -> None:
        if self._index_file.exists() and self._meta_file.exists():
            try:
                self._index = self._faiss.read_index(str(self._index_file))
                with self._meta_file.open("rb") as f:
                    state = pickle.load(f)
                self._meta = state.get("meta", {})
                self._id_map = state.get("id_map", {})
                self._next_int_id = state.get("next", 0)
            except Exception:
                pass

    # ------------------------------------------------------------------

    def add(self, id: str, text: str, metadata: dict) -> None:
        import numpy as np  # type: ignore
        if id in self._id_map:
            self.update(id, text, metadata)
            return
        vec = self._embed(text)
        int_id = self._next_int_id
        self._next_int_id += 1
        self._index.add(vec)
        self._meta[int_id] = {"id": id, "text": text, "metadata": metadata}
        self._id_map[id] = int_id
        self._save()

    def search(self, query: str, n: int = 10, where: dict | None = None) -> list[dict]:
        if self._index.ntotal == 0:
            return []
        vec = self._embed(query)
        k = min(n, self._index.ntotal)
        scores, indices = self._index.search(vec, k)
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            m = self._meta.get(int(idx))
            if m is None:
                continue
            if where and not _match_where(m["metadata"], where):
                continue
            results.append(
                {"id": m["id"], "text": m["text"], "metadata": m["metadata"], "score": float(score)}
            )
        return results

    def delete(self, id: str) -> None:
        # FAISS flat index doesn't support removal; mark as tombstone
        if id in self._id_map:
            int_id = self._id_map.pop(id)
            self._meta.pop(int_id, None)
            self._save()

    def count(self) -> int:
        return len(self._id_map)

    def update(self, id: str, text: str, metadata: dict) -> None:
        self.delete(id)
        self.add(id, text, metadata)


def _match_where(meta: dict, where: dict) -> bool:
    return all(meta.get(k) == v for k, v in where.items())


if __name__ == "__main__":
    backend = FaissBackend()
    print(f"FAISS backend — {backend.count()} entries")
