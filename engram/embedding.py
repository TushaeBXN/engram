"""Use an embedding server you run instead of the built-in English model.

Engram's default model (all-MiniLM-L6-v2) is small, fast and English-only.
If you want another language, or a larger model, point Engram at any server
that speaks the OpenAI-style ``/v1/embeddings`` API. Servers you can run on
your own computer include LM Studio, Ollama, llama.cpp and vLLM. In
``~/.engram/config.json``::

    "embedding_api_url": "http://localhost:11434/v1",
    "embedding_api_model": "embeddinggemma"

then run ``engram reindex`` once.

Memories are private, so Engram is strict about where their text goes:

* The server must be on this computer or your local network (localhost, a
  private address such as 192.168.x.x, or a ``.local`` name). Any other host
  receives your memories' text, so it is refused unless you also set
  ``"embedding_api_allow_remote": true``.
* The key (if the server needs one) is read from ``ENGRAM_EMBEDDING_API_KEY``
  or ``embedding_api_key``; it is only ever sent to that server.

Each (server, model) pair gets its own index. Switching never touches the
index you had before, so you can switch back without reindexing, and your
memories themselves (the drawers) are never changed.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import urllib.error
import urllib.request
from typing import Optional
from urllib.parse import urlsplit

BATCH = 32
TIMEOUT = 60


class EmbeddingConfigError(RuntimeError):
    """The embedding server setting can't be used (and why)."""


def is_local_host(host: str) -> bool:
    host = (host or "").strip("[]").lower()
    if host == "localhost" or host.endswith(".local") or host.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or ip.is_link_local


def settings(cfg: dict) -> Optional[dict]:
    """The embedding-server settings from *cfg*, or None to use the built-in model.

    Raises :class:`EmbeddingConfigError` when the URL points somewhere that
    isn't local and ``embedding_api_allow_remote`` is not set.
    """
    url = (os.environ.get("ENGRAM_EMBEDDING_API_URL") or cfg.get("embedding_api_url") or "").strip()
    if not url:
        return None
    model = (os.environ.get("ENGRAM_EMBEDDING_API_MODEL") or cfg.get("embedding_api_model") or "").strip()
    if not model:
        raise EmbeddingConfigError("embedding_api_url is set but embedding_api_model is not")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise EmbeddingConfigError(f"embedding_api_url {url!r} is not an http(s) address")
    if not is_local_host(parts.hostname) and not cfg.get("embedding_api_allow_remote"):
        raise EmbeddingConfigError(
            f"embedding_api_url points at {parts.hostname}, which is not on this computer or your local "
            "network, so every memory's text would be sent there. If that is what you want, set "
            '"embedding_api_allow_remote": true in ~/.engram/config.json.')
    return {"url": url.rstrip("/"), "model": model,
            "key": os.environ.get("ENGRAM_EMBEDDING_API_KEY") or cfg.get("embedding_api_key") or ""}


def collection_suffix(s: dict) -> str:
    """A short, stable tag so each (server, model) pair keeps its own index."""
    return hashlib.sha1(f"{s['url']}|{s['model']}".encode()).hexdigest()[:8]


def embed(s: dict, texts: list[str]) -> list[list[float]]:
    """Embed *texts* with the server described by *s*, in order."""
    out: list[list[float]] = []
    for start in range(0, len(texts), BATCH):
        batch = texts[start:start + BATCH]
        body = json.dumps({"model": s["model"], "input": batch}).encode()
        headers = {"Content-Type": "application/json"}
        if s.get("key"):
            headers["Authorization"] = f"Bearer {s['key']}"
        req = urllib.request.Request(f"{s['url']}/embeddings", data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            raise EmbeddingConfigError(f"the embedding server answered {exc.code} ({s['url']})") from None
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise EmbeddingConfigError(f"could not reach the embedding server at {s['url']}: {exc}") from None
        rows = sorted(data.get("data", []), key=lambda r: r.get("index", 0))
        if len(rows) != len(batch) or any("embedding" not in r for r in rows):
            raise EmbeddingConfigError("the embedding server returned an unexpected reply")
        out.extend([float(x) for x in r["embedding"]] for r in rows)
    return out


def chroma_function(s: dict):
    """A ChromaDB embedding function that calls the server described by *s*."""
    from chromadb import EmbeddingFunction

    class _ServerEmbedding(EmbeddingFunction):
        def __init__(self) -> None:
            pass

        def __call__(self, input):  # noqa: A002 - signature required by ChromaDB
            return embed(s, list(input))

    return _ServerEmbedding()
