"""Remove a memory completely, and everything that pointed at it.

``engram forget <id>`` is how you take back something that should never have
been saved (a test, a mistake, something private). Unlike a *correction*, which
keeps the old memory as history, forgetting deletes it:

* the memory itself, and its search entries (meaning and exact-word indexes);
* every correction link it is part of. If it was the *newer* half of a
  correction, the memory it replaced becomes current again; if it was the
  older half, the memory that replaced it simply stops saying it replaced
  something;
* every conflict mark, and the evidence links *from* it. Memories that rested
  on it are not deleted, and they do not quietly become unsupported claims: the
  link stays as a marker (the ID and when it was forgotten, never any text), and
  ``engram check`` and ``engram why`` say their evidence was deleted until
  you dismiss it with ``engram link <id> based_on <forgotten id> --undo``;
* its provenance record.

It does not touch backups you exported earlier, and a forgotten memory is not
recoverable. :func:`plan` says exactly what would happen, without doing it.
"""

from __future__ import annotations

from engram.lineage import Lineage, LineageError, _resolve, _summary
from engram.relations import Relations


def plan(chateau, memory_id: str) -> dict:
    """What forgetting *memory_id* (an ID or unique prefix) would remove and change."""
    drawer = _resolve(chateau, memory_id)
    lineage, relations = Lineage(chateau.path), Relations(chateau.path)

    def brief(mid: str) -> dict:
        other = chateau.find_drawer(mid)
        return _summary(other) if other is not None else {"id": mid, "text": "(missing)"}

    replaced = [lk["old"] for lk in lineage.links() if lk["kind"] == "supersedes" and lk["new"] == drawer.id]
    replaced_by = [lk["new"] for lk in lineage.links() if lk["kind"] == "supersedes" and lk["old"] == drawer.id]
    disputed = [lk["new"] if lk["old"] == drawer.id else lk["old"] for lk in lineage.links()
                if lk["kind"] == "disputes" and drawer.id in (lk["old"], lk["new"])]
    return {
        "memory": _summary(drawer),
        "becomes_current_again": [brief(m) for m in replaced],
        "loses_its_replaced_label": [brief(m) for m in replaced_by],
        "conflict_marks_removed": [brief(m) for m in disputed],
        "evidence_it_rested_on": [brief(lk["to"]) for lk in relations.evidence(drawer.id)],
        "memories_that_lose_it_as_evidence": [brief(lk["from"]) for lk in relations.dependents(drawer.id)],
    }


def forget(chateau, backend, memory_id: str) -> dict:
    """Delete the memory and clean every link to it. Returns what :func:`plan` described."""
    from engram.indexing import unindex_drawer

    what = plan(chateau, memory_id)
    drawer = _resolve(chateau, memory_id)
    unindex_drawer(backend, drawer.id)
    if not chateau.delete_drawer(drawer.wing, drawer.room, drawer.hall, drawer.id):
        raise LineageError(f"could not delete memory {drawer.id}")
    chateau.delete_drawer_by_id(drawer.id)               # a stray copy filed elsewhere, if any
    Lineage(chateau.path).forget(drawer.id)
    Relations(chateau.path).forget(drawer.id)
    prov = chateau.path / "provenance" / f"{drawer.id}.json"
    try:
        prov.unlink()
    except FileNotFoundError:
        pass
    return what
