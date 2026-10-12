"""Optional local reranker (cross-encoder), off by default.

A cross-encoder reads the query and a candidate memory *together* and scores
how well the memory answers the query. It is slower than the embedding search
but sharper, so Engram uses it only to reorder the top results.

Everything stays local: the model (ms-marco-MiniLM-L-6-v2 in ONNX form, about
90 MB) runs on onnxruntime and tokenizers, which ChromaDB already installs, so
there is no PyTorch and no API key. The model is downloaded once, into
``~/.engram/models/``, the first time reranking is used, and only then: with
``"reranker": false`` (the default) Engram never touches the network.

Turn it on with ``"reranker": true`` in ``~/.engram/config.json`` or
``engram search --rerank``. If the model or its runtime is unavailable,
search carries on without reranking and says why once on stderr.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

DEFAULT_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"
# Files fetched for a model, as (local name, path in the model repository).
MODEL_FILES = (("model.onnx", "onnx/model.onnx"), ("tokenizer.json", "tokenizer.json"))
DOWNLOAD_URL = "https://huggingface.co/{model}/resolve/main/{path}"
MAX_LENGTH = 512


class RerankerUnavailable(RuntimeError):
    """The reranker model or its runtime (onnxruntime, tokenizers) is missing."""


def models_dir() -> Path:
    from engram.config import ENGRAM_DIR
    return ENGRAM_DIR / "models"


def model_path(model: str = DEFAULT_MODEL, base: Optional[Path] = None) -> Path:
    return (base or models_dir()) / model.replace("/", "__")


def ensure_model(model: str = DEFAULT_MODEL, base: Optional[Path] = None,
                 download: bool = True) -> Path:
    """Return the local directory of *model*, downloading it once if allowed."""
    target = model_path(model, base)
    if all((target / name).exists() for name, _ in MODEL_FILES):
        return target
    if not download:
        raise RerankerUnavailable(f"reranker model not found in {target}")
    import requests

    target.mkdir(parents=True, exist_ok=True)
    print(f"engram: downloading reranker model {model} (about 90 MB, once) to {target}",
          file=sys.stderr)
    for name, remote in MODEL_FILES:
        dest = target / name
        if dest.exists():
            continue
        tmp = dest.with_suffix(dest.suffix + ".part")
        try:
            with requests.get(DOWNLOAD_URL.format(model=model, path=remote),
                              stream=True, timeout=60) as resp:
                resp.raise_for_status()
                with tmp.open("wb") as f:
                    for chunk in resp.iter_content(chunk_size=1 << 20):
                        f.write(chunk)
            tmp.replace(dest)
        except Exception as exc:
            tmp.unlink(missing_ok=True)
            raise RerankerUnavailable(f"could not download {remote} for {model}: {exc}") from exc
    return target


class CrossEncoder:
    """ONNX cross-encoder: ``score(query, texts)`` returns one relevance score per text."""

    def __init__(self, model_dir: Path, max_length: int = MAX_LENGTH, threads: int = 0) -> None:
        try:
            import numpy as np  # noqa: F401  (needed by score)
            import onnxruntime as ort
            from tokenizers import Tokenizer
        except ImportError as exc:
            raise RerankerUnavailable(f"reranking needs onnxruntime and tokenizers ({exc})") from exc
        self._tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self._tokenizer.enable_truncation(max_length=max_length)
        self._tokenizer.enable_padding()
        options = ort.SessionOptions()
        if threads:
            options.intra_op_num_threads = threads
        self._session = ort.InferenceSession(str(model_dir / "model.onnx"), options,
                                             providers=["CPUExecutionProvider"])
        self._inputs = {i.name for i in self._session.get_inputs()}

    def score(self, query: str, texts: list[str], batch_size: int = 32) -> list[float]:
        import numpy as np

        scores: list[float] = []
        for start in range(0, len(texts), batch_size):
            batch = self._tokenizer.encode_batch([(query, t) for t in texts[start:start + batch_size]])
            feed = {
                "input_ids": np.array([e.ids for e in batch], dtype=np.int64),
                "attention_mask": np.array([e.attention_mask for e in batch], dtype=np.int64),
                "token_type_ids": np.array([e.type_ids for e in batch], dtype=np.int64),
            }
            logits = self._session.run(None, {k: v for k, v in feed.items() if k in self._inputs})[0]
            scores.extend(float(x) for x in np.asarray(logits).reshape(len(batch), -1)[:, 0])
        return scores


_LOADED: dict = {}
_WARNED: set = set()


def get_reranker(config: dict) -> Optional[CrossEncoder]:
    """The configured cross-encoder, loaded once per process; None (with one
    warning on stderr) if it cannot be loaded, so search falls back to the
    normal ranking instead of failing."""
    model = config.get("reranker_model", DEFAULT_MODEL)
    path = config.get("reranker_path")  # a local model directory skips the download
    key = path or model
    if key in _LOADED:
        return _LOADED[key]
    try:
        model_dir = Path(path).expanduser() if path else ensure_model(model)
        _LOADED[key] = CrossEncoder(model_dir)
    except Exception as exc:
        if key not in _WARNED:
            _WARNED.add(key)
            print(f"engram: reranker unavailable, searching without it ({exc})", file=sys.stderr)
        _LOADED[key] = None
    return _LOADED[key]


def rerank(query: str, results: list[dict], reranker: CrossEncoder, top: int) -> list[dict]:
    """Reorder the first *top* results by cross-encoder score; the rest keep their order.

    Each reranked result gains a ``rerank_score``.
    """
    head, tail = results[:top], results[top:]
    if not head:
        return results
    for hit, s in zip(head, reranker.score(query, [h["text"] for h in head])):
        hit["rerank_score"] = round(s, 4)
    head.sort(key=lambda h: h["rerank_score"], reverse=True)
    return head + tail
