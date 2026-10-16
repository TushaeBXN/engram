"""Memory lineage: which memories are current, which were replaced, and why.

Engram never decides on its own that one memory corrects another. The agent
using it (Claude, Amy, you) makes that call and records it here; Engram keeps
the links consistent and makes search and history use them.

Two kinds of link are stored in ``<chateau>/lineage.json``:

* ``supersedes``: memory *new* replaces memory *old*. *old* becomes
  ``superseded``: still stored, still searchable, but shown as historical
  with a pointer to what replaced it.
* ``disputes``: two memories conflict and nobody has decided which is right
  yet. Both are marked ``disputed``.

Every memory with no link is ``current``, so château data written before
lineage existed needs no migration.

Rules that keep the history sound:

* A memory can be replaced by at most one other memory. To change your mind
  again, supersede the replacement (A -> B -> C), or :meth:`Lineage.restore`
  the old one first.
* Only a current memory can be the replacement, which rules out cycles.
* Recording the same link twice is a no-op (safe to retry).
* Each change is one atomic file replace, made under a lock: either the whole
  link is recorded or nothing is.
"""

from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:  # POSIX advisory lock; Windows falls back to the in-process lock only
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

LINEAGE_FILE = "lineage.json"
FORMAT_VERSION = 1
_THREAD_LOCK = threading.Lock()


class LineageError(ValueError):
    """A requested link would break the history (cycle, double replacement, unknown memory)."""


def short_id(memory_id: str) -> str:
    """The part of an ID people need to type: 8 characters after any "file-" style prefix."""
    head, sep, rest = memory_id.partition("-")
    if sep and head.isalpha() and len(head) < 8:
        return memory_id[:len(head) + 1 + 8]
    return memory_id[:8]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_links(links: list[dict], known_ids: Optional[set] = None) -> None:
    """Raise :class:`LineageError` unless *links* form a sound history.

    Checks link shape, that every memory exists (when *known_ids* is given),
    that no memory is replaced twice, and that there are no cycles.
    """
    replaced_by: dict[str, str] = {}
    for link in links:
        kind, old, new = link.get("kind"), link.get("old"), link.get("new")
        if kind not in ("supersedes", "disputes") or not old or not new:
            raise LineageError(f"malformed link: {link!r}")
        if old == new:
            raise LineageError(f"memory {old} cannot be linked to itself")
        if known_ids is not None:
            for mid in (old, new):
                if mid not in known_ids:
                    raise LineageError(f"link refers to unknown memory {mid}")
        if kind == "supersedes":
            if old in replaced_by and replaced_by[old] != new:
                raise LineageError(f"memory {old} is replaced by both {replaced_by[old]} and {new}")
            replaced_by[old] = new
    for start in replaced_by:
        seen, node = {start}, start
        while node in replaced_by:
            node = replaced_by[node]
            if node in seen:
                raise LineageError(f"replacement chain from {start} loops back on itself")
            seen.add(node)


class Lineage:
    """The lineage ledger of one château."""

    def __init__(self, chateau_path: Path) -> None:
        self.dir = Path(chateau_path).expanduser()
        self.path = self.dir / LINEAGE_FILE
        self._cache: Optional[tuple[float, list[dict]]] = None

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def links(self) -> list[dict]:
        """All recorded links, oldest first."""
        try:
            mtime = self.path.stat().st_mtime
        except FileNotFoundError:
            return []
        if self._cache and self._cache[0] == mtime:
            return self._cache[1]
        data = json.loads(self.path.read_text())
        links = list(data.get("links", []))
        self._cache = (mtime, links)
        return links

    def _replaced_by(self, links: list[dict]) -> dict[str, dict]:
        return {link["old"]: link for link in links if link["kind"] == "supersedes"}

    def status(self, memory_id: str) -> dict:
        """Where *memory_id* stands::

            {"status": "current" | "superseded" | "disputed",
             "superseded_by": id | None, "replaced_at": iso | None, "reason": str | None,
             "current_id": id of the newest memory in its chain,
             "supersedes": [ids it replaced], "disputed_with": [ids]}
        """
        links = self.links()
        replaced = self._replaced_by(links)
        link = replaced.get(memory_id)
        disputed = sorted({lk["new"] if lk["old"] == memory_id else lk["old"] for lk in links
                           if lk["kind"] == "disputes" and memory_id in (lk["old"], lk["new"])})
        status = "superseded" if link else ("disputed" if disputed else "current")
        return {
            "status": status,
            "superseded_by": link["new"] if link else None,
            "replaced_at": link["at"] if link else None,
            "reason": link.get("reason") if link else None,
            "current_id": self._head(memory_id, replaced),
            "supersedes": [lk["old"] for lk in links if lk["kind"] == "supersedes" and lk["new"] == memory_id],
            "disputed_with": disputed,
        }

    def _head(self, memory_id: str, replaced: dict[str, dict]) -> str:
        node, seen = memory_id, {memory_id}
        while node in replaced and replaced[node]["new"] not in seen:
            node = replaced[node]["new"]
            seen.add(node)
        return node

    def current_id(self, memory_id: str) -> str:
        """The newest memory in *memory_id*'s replacement chain (itself if current)."""
        return self._head(memory_id, self._replaced_by(self.links()))

    def history(self, memory_id: str) -> list[dict]:
        """Every supersedes link in *memory_id*'s chain, oldest first.

        Covers what led up to it and what replaced it since, including merges
        where one memory replaced several.
        """
        links = [lk for lk in self.links() if lk["kind"] == "supersedes"]
        related, frontier = set(), {memory_id}
        while frontier:  # walk links in both directions
            node = frontier.pop()
            related.add(node)
            for lk in links:
                for a, b in ((lk["old"], lk["new"]), (lk["new"], lk["old"])):
                    if a == node and b not in related:
                        frontier.add(b)
        return [lk for lk in links if lk["old"] in related]

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    @contextmanager
    def _locked(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        with _THREAD_LOCK, open(self.dir / (LINEAGE_FILE + ".lock"), "w") as fh:
            if fcntl:
                fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl:
                    fcntl.flock(fh, fcntl.LOCK_UN)

    def _write(self, links: list[dict]) -> None:
        tmp = self.path.with_suffix(".json.tmp")
        with open(tmp, "w") as fh:
            json.dump({"format": "engram-lineage", "version": FORMAT_VERSION, "links": links}, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)
        self._cache = None

    def supersede(self, old_id: str, new_id: str, reason: str = "", by: str = "") -> tuple[dict, bool]:
        """Record that *new_id* replaces *old_id*. Returns ``(link, created)``.

        ``created`` is False when exactly this link already existed.
        Raises :class:`LineageError` if the link would break the history.
        """
        if old_id == new_id:
            raise LineageError("a memory cannot replace itself")
        with self._locked():
            links = list(self.links())
            replaced = self._replaced_by(links)
            if old_id in replaced:
                existing = replaced[old_id]
                if existing["new"] == new_id:
                    return existing, False
                raise LineageError(
                    f"{old_id} was already replaced by {existing['new']}; supersede that one instead, "
                    f"or restore {old_id} first")
            if new_id in replaced:
                raise LineageError(
                    f"{new_id} is itself outdated (replaced by {self._head(new_id, replaced)}); "
                    "only a current memory can replace another")
            link = {"kind": "supersedes", "old": old_id, "new": new_id, "at": _now(),
                    "reason": reason, "by": by}
            links.append(link)
            validate_links(links)
            self._write(links)
            return link, True

    def dispute(self, a: str, b: str, reason: str = "", by: str = "") -> tuple[dict, bool]:
        """Mark two memories as conflicting, undecided. Returns ``(link, created)``."""
        if a == b:
            raise LineageError("a memory cannot dispute itself")
        with self._locked():
            links = list(self.links())
            for lk in links:
                if lk["kind"] == "disputes" and {lk["old"], lk["new"]} == {a, b}:
                    return lk, False
            link = {"kind": "disputes", "old": a, "new": b, "at": _now(), "reason": reason, "by": by}
            links.append(link)
            self._write(links)
            return link, True

    def restore(self, old_id: str) -> bool:
        """Undo the replacement of *old_id*, making it current again.

        Returns False if it was not replaced. The replacement itself is kept.
        """
        with self._locked():
            links = self.links()
            kept = [lk for lk in links if not (lk["kind"] == "supersedes" and lk["old"] == old_id)]
            if len(kept) == len(links):
                return False
            self._write(kept)
            return True

    def replace_all(self, links: list[dict]) -> None:
        """Write *links* as the whole ledger (used by import, after validation)."""
        validate_links(links)
        with self._locked():
            self._write(links)


def _apply(result: dict, info: dict) -> dict:
    result["status"] = info["status"]
    for key in ("superseded_by", "replaced_at", "reason"):
        if info[key]:
            result[key] = info[key]
    if info["current_id"] != result["id"]:
        result["current_id"] = info["current_id"]
    if info["supersedes"]:
        result["supersedes"] = info["supersedes"]
    if info["disputed_with"]:
        result["disputed_with"] = info["disputed_with"]
    return info


def annotate(results: list[dict], lineage: Lineage, find_drawer) -> list[dict]:
    """Add lineage to search results and put each replacement before what it replaced.

    Every result gains ``status`` (and, when relevant, ``superseded_by``,
    ``current_id``, ``replaced_at``, ``reason``, ``supersedes``,
    ``disputed_with``). When an outdated memory is found, its current
    replacement is placed directly above it; if search did not find the
    replacement, it is loaded with *find_drawer* and inserted (marked with
    ``"via": <old id>``). Outdated memories stay in the results, so old
    evidence is never hidden. Without any links this only adds
    ``status: "current"``.
    """
    if not lineage.links():
        for r in results:
            r.setdefault("status", "current")
        return results
    by_id = {r["id"]: r for r in results}
    out: list[dict] = []
    emitted: set[str] = set()

    def emit(r: dict) -> None:
        if r["id"] not in emitted:
            emitted.add(r["id"])
            out.append(r)

    for r in results:
        info = _apply(r, lineage.status(r["id"]))
        if info["status"] == "superseded" and info["current_id"] not in emitted:
            head = by_id.get(info["current_id"])
            if head is None:
                drawer = find_drawer(info["current_id"])
                if drawer is not None:
                    head = {
                        "id": drawer.id, "text": drawer.text()[:1000],
                        "metadata": {"wing": drawer.wing, "room": drawer.room, "hall": drawer.hall,
                                     "timestamp": drawer.timestamp, "pinned": drawer.pinned,
                                     "drawer_id": drawer.id},
                        "semantic_score": 0.0, "recency_boost": 0.0, "keyword_overlap": 0.0,
                        "temporal_closeness": 0.0, "final_score": r.get("final_score", 0.0),
                        "pinned": drawer.pinned, "via": r["id"],
                    }
                    by_id[drawer.id] = head
            if head is not None:
                _apply(head, lineage.status(head["id"]))
                emit(head)
        emit(r)
    return out


# ---------------------------------------------------------------------------
# Operations on stored memories (used by the CLI and the MCP server)
# ---------------------------------------------------------------------------

def _resolve(chateau, memory_id: str):
    try:
        drawer = chateau.find_drawer(memory_id)
    except LookupError as exc:
        raise LineageError(str(exc)) from exc
    if drawer is None:
        raise LineageError(f"no memory with ID {memory_id!r}")
    return drawer


def _summary(drawer) -> dict:
    return {"id": drawer.id, "text": drawer.text().strip()[:300], "wing": drawer.wing, "room": drawer.room,
            "hall": drawer.hall, "timestamp": drawer.timestamp}


def supersede_memory(chateau, old_id: str, new_id: str, reason: str = "", by: str = "") -> dict:
    """Record that stored memory *new_id* replaces *old_id* (IDs or unique prefixes)."""
    old, new = _resolve(chateau, old_id), _resolve(chateau, new_id)
    link, created = Lineage(chateau.path).supersede(old.id, new.id, reason=reason, by=by)
    return {"link": link, "created": created, "old": _summary(old), "new": _summary(new)}


def correct_memory(chateau, backend, old_id: str, content: str, reason: str = "", by: str = "") -> dict:
    """Save *content* as a new memory that replaces *old_id*, in the same wing/room/hall.

    All or nothing: if the link cannot be recorded, the new memory is removed
    again. Retrying with the same content returns the existing correction
    instead of saving a duplicate.
    """
    from engram.chateau import Drawer
    from engram.indexing import index_drawer, unindex_drawer

    if not content or not content.strip():
        raise LineageError("the correction is empty")
    old = _resolve(chateau, old_id)
    lineage = Lineage(chateau.path)
    info = lineage.status(old.id)
    if info["superseded_by"]:
        existing = chateau.find_drawer(info["superseded_by"])
        if existing is not None and existing.text().strip() == content.strip():
            link = next(lk for lk in lineage.links() if lk["kind"] == "supersedes" and lk["old"] == old.id)
            return {"link": link, "created": False, "old": _summary(old), "new": _summary(existing)}
        raise LineageError(f"{old.id} was already replaced by {info['superseded_by']}; "
                           "correct that one instead")
    new = Drawer(content=content, wing=old.wing, room=old.room, hall=old.hall, tags=list(old.tags))
    chateau.save_drawer(new)
    try:
        index_drawer(backend, new.id, new.content, {
            "wing": new.wing, "room": new.room, "hall": new.hall,
            "timestamp": new.timestamp, "pinned": new.pinned})
        link, _ = lineage.supersede(old.id, new.id, reason=reason, by=by)
    except Exception:
        try:
            unindex_drawer(backend, new.id)
        finally:
            chateau.delete_drawer(new.wing, new.room, new.hall, new.id)
        raise
    return {"link": link, "created": True, "old": _summary(old), "new": _summary(new)}


def memory_history(chateau, memory_id: str) -> dict:
    """A memory's status and the full chain of replacements around it."""
    drawer = _resolve(chateau, memory_id)
    lineage = Lineage(chateau.path)
    steps = []
    for link in lineage.history(drawer.id):
        old, new = chateau.find_drawer(link["old"]), chateau.find_drawer(link["new"])
        steps.append({**link,
                      "old_text": old.text().strip()[:300] if old else None,
                      "new_text": new.text().strip()[:300] if new else None})
    return {"memory": _summary(drawer), **lineage.status(drawer.id), "history": steps}


def possible_updates(backend, chateau, drawer, n: int = 3, min_score: float = 0.35) -> list[dict]:
    """Current memories in the same wing that look like earlier versions of *drawer*.

    A hint for the agent that saved it ("this may update memory X"); nothing
    is linked until the agent calls supersede.
    """
    from engram.indexing import drawer_id_of

    try:
        hits = backend.search(drawer.content, n=n * 4, where={"wing": drawer.wing})
    except Exception:
        return []
    lineage = Lineage(chateau.path)
    out, seen = [], {drawer.id}
    for hit in hits:
        did = drawer_id_of(hit)
        if did in seen or hit.get("score", 0.0) < min_score:
            continue
        seen.add(did)
        if lineage.status(did)["status"] == "superseded":
            continue
        meta = hit.get("metadata") or {}
        out.append({"id": did, "text": hit["text"][:300], "room": meta.get("room"),
                    "timestamp": meta.get("timestamp"), "similarity": round(hit.get("score", 0.0), 3)})
        if len(out) >= n:
            break
    return out
