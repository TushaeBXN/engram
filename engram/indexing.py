"""Indexing drawers into the vector backend.

Embedding models only read the start of a long text (all-MiniLM-L6-v2 stops
at 256 tokens, roughly 1,000 characters), and Engram used to index just the
first 2,000 characters of each drawer, so anything later in a long note or
conversation could never be found. Drawers are now split into overlapping
chunks; each chunk is indexed separately with the drawer's ID in its
metadata, and search results are collapsed back to one hit per drawer.

Usage::

    index_drawer(backend, drawer.id, drawer.content, metadata)
    unindex_drawer(backend, drawer.id)
"""

from __future__ import annotations

import re

from engram.backends.base import VectorBackend

CHUNK_CHARS = 900
OVERLAP_CHARS = 150

_BREAKS = ("\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " ")


def chunk_text(text: str, size: int = CHUNK_CHARS, overlap: int = OVERLAP_CHARS) -> list[str]:
    """Split *text* into chunks of at most *size* characters.

    Chunks end at the strongest natural break (paragraph, line, sentence,
    clause, word) found in their second half, and consecutive chunks share
    up to *overlap* characters so a fact spanning a boundary stays findable.
    """
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []

    chunks = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            window = text[start:end]
            for brk in _BREAKS:
                cut = window.rfind(brk, size // 2)
                if cut != -1:
                    end = start + cut + len(brk)
                    break
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        next_start = max(end - overlap, start + 1)
        # Start the overlap on a word boundary
        space = text.find(" ", next_start, end)
        start = space + 1 if space != -1 else next_start
    return chunks


def chunk_id(drawer_id: str, n: int) -> str:
    return f"{drawer_id}::{n}"


def index_drawer(backend: VectorBackend, drawer_id: str, text: str, metadata: dict) -> int:
    """(Re)index *text* for *drawer_id*. Returns the number of chunks stored."""
    return index_drawers(backend, [(drawer_id, text, metadata)])


def index_drawers(
    backend: VectorBackend, drawers: list[tuple[str, str, dict]], replace: bool = True
) -> int:
    """Index several ``(drawer_id, text, metadata)`` drawers in one batched write.

    With ``replace=False`` the caller guarantees none of the drawers was indexed
    before, which skips the per-drawer delete (used for brand-new drawers).
    Returns the total number of chunks stored.
    """
    items = []
    for drawer_id, text, metadata in drawers:
        if replace:
            unindex_drawer(backend, drawer_id)
        for n, chunk in enumerate(chunk_text(text)):
            items.append((chunk_id(drawer_id, n), chunk,
                          {**metadata, "drawer_id": drawer_id, "chunk": n}))
    if items:
        backend.add_many(items)
    return len(items)


def unindex_drawer(backend: VectorBackend, drawer_id: str) -> None:
    """Remove every chunk of *drawer_id*, plus any pre-chunking entry stored under the bare ID."""
    backend.delete_where({"drawer_id": drawer_id})
    backend.delete(drawer_id)


def drawer_id_of(hit: dict) -> str:
    """The drawer a search hit belongs to (pre-chunking entries use their own ID)."""
    meta = hit.get("metadata") or {}
    return meta.get("drawer_id") or re.sub(r"::\d+$", "", hit["id"])
