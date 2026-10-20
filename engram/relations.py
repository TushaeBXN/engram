"""Evidence links between memories, and explaining why a memory says what it says.

Lineage (``lineage.py``) records how a memory changed over time. This module
records what a memory rests on:

* ``based_on``: memory *A* is a conclusion or position supported by memory
  *B* (a constitutional passage, a decision, a measurement).
* ``derived_from``: memory *A* was inferred from *B*. An inference is not
  evidence of anything by itself; it is only as good as what it came from.

Together with the lineage kinds this gives the full set of relationships an
agent can record with :func:`link_memories`::

    A based_on B       B is evidence for A
    A derived_from B   A was inferred from B
    A contradicts B    the two conflict, undecided (lineage ``disputes``)
    A supersedes B     A replaces B (lineage ``supersedes``; ``updates`` is a synonym)

Each memory can also say where it came from (``Drawer.source``):
``user`` (the person said it), ``primary`` (an original document, law, ruling,
dataset), ``secondary`` (reporting or analysis about a primary source),
``tool`` (a search or program result) or ``inference`` (concluded by an AI).
Memories saved before this existed have no source and are treated as
"not recorded", never guessed.

Like lineage, Engram never creates these links itself. The agent decides;
Engram keeps them sound (no missing memories, no circular evidence), never
rewrites them when evidence is corrected, and points out what needs review.

Links live in ``<chateau>/relations.json``, separate from ``lineage.json`` so
older Engram versions keep reading the lineage ledger unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from engram.lineage import (
    Lineage,
    LineageError,
    _locked_dir,
    _now,
    _resolve,
    _summary,
    _write_atomic,
)

RELATIONS_FILE = "relations.json"
FORMAT_VERSION = 1
EVIDENCE_KINDS = ("based_on", "derived_from")
LINK_KINDS = EVIDENCE_KINDS + ("contradicts", "supersedes", "updates")
SOURCE_KINDS = ("user", "primary", "secondary", "tool", "inference")
SOURCE_LABELS = {
    "user": "told by the user",
    "primary": "primary source",
    "secondary": "secondary source",
    "tool": "tool result",
    "inference": "AI inference",
}


def validate_relations(links: list[dict], known_ids: Optional[set] = None) -> None:
    """Raise :class:`LineageError` unless *links* are well formed and evidence never loops."""
    edges: dict[str, set] = {}
    for link in links:
        kind, frm, to = link.get("kind"), link.get("from"), link.get("to")
        if kind not in EVIDENCE_KINDS or not frm or not to:
            raise LineageError(f"malformed relation: {link!r}")
        if frm == to:
            raise LineageError(f"memory {frm} cannot rest on itself")
        if known_ids is not None:
            for mid in (frm, to):
                if mid not in known_ids:
                    raise LineageError(f"relation refers to unknown memory {mid}")
        edges.setdefault(frm, set()).add(to)
    for start in edges:  # circular evidence: A rests on B rests on ... A
        stack, seen = list(edges[start]), set()
        while stack:
            node = stack.pop()
            if node == start:
                raise LineageError(f"evidence for {start} leads back to itself")
            if node not in seen:
                seen.add(node)
                stack.extend(edges.get(node, ()))


class Relations:
    """The evidence ledger of one château."""

    def __init__(self, chateau_path: Path) -> None:
        self.dir = Path(chateau_path).expanduser()
        self.path = self.dir / RELATIONS_FILE
        self._cache: Optional[tuple[float, list[dict]]] = None

    def links(self) -> list[dict]:
        """All evidence links, oldest first."""
        try:
            mtime = self.path.stat().st_mtime
        except FileNotFoundError:
            return []
        if self._cache and self._cache[0] == mtime:
            return self._cache[1]
        links = list(json.loads(self.path.read_text()).get("links", []))
        self._cache = (mtime, links)
        return links

    def evidence(self, memory_id: str) -> list[dict]:
        """Links from *memory_id* to what it rests on."""
        return [lk for lk in self.links() if lk["from"] == memory_id]

    def dependents(self, memory_id: str) -> list[dict]:
        """Links from memories that rest on *memory_id*."""
        return [lk for lk in self.links() if lk["to"] == memory_id]

    def _write(self, links: list[dict]) -> None:
        _write_atomic(self.path, {"format": "engram-relations", "version": FORMAT_VERSION, "links": links})
        self._cache = None

    def add(self, kind: str, frm: str, to: str, reason: str = "", by: str = "") -> tuple[dict, bool]:
        """Record that *frm* rests on *to*. Returns ``(link, created)``; repeating it is a no-op."""
        with _locked_dir(self.dir, RELATIONS_FILE):
            links = list(self.links())
            for lk in links:
                if (lk["kind"], lk["from"], lk["to"]) == (kind, frm, to):
                    return lk, False
            link = {"kind": kind, "from": frm, "to": to, "at": _now(), "reason": reason, "by": by}
            links.append(link)
            validate_relations(links)
            self._write(links)
            return link, True

    def remove(self, kind: str, frm: str, to: str) -> bool:
        with _locked_dir(self.dir, RELATIONS_FILE):
            links = self.links()
            kept = [lk for lk in links if (lk["kind"], lk["from"], lk["to"]) != (kind, frm, to)]
            if len(kept) == len(links):
                return False
            self._write(kept)
            return True

    def forget(self, memory_id: str) -> int:
        """Drop every evidence link that mentions *memory_id* (the memory was deleted). Returns how many."""
        with _locked_dir(self.dir, RELATIONS_FILE):
            links = self.links()
            kept = [lk for lk in links if memory_id not in (lk["from"], lk["to"])]
            if len(kept) != len(links):
                self._write(kept)
            return len(links) - len(kept)

    def replace_all(self, links: list[dict]) -> None:
        """Write *links* as the whole ledger (used by import, after validation)."""
        validate_relations(links)
        with _locked_dir(self.dir, RELATIONS_FILE):
            self._write(links)


# ---------------------------------------------------------------------------
# Operations on stored memories (used by the CLI and the MCP server)
# ---------------------------------------------------------------------------

def link_memories(chateau, memory_id: str, kind: str, target_id: str, reason: str = "", by: str = "",
                  undo: bool = False) -> dict:
    """Record "*memory_id* <kind> *target_id*" (IDs or unique prefixes), or remove it with *undo*."""
    if kind not in LINK_KINDS:
        raise LineageError(f"unknown relationship {kind!r}; use one of: {', '.join(LINK_KINDS)}")
    a, b = _resolve(chateau, memory_id), _resolve(chateau, target_id)
    if a.id == b.id:
        raise LineageError("a memory cannot be linked to itself")
    out = {"memory": _summary(a), "relation": kind, "target": _summary(b)}
    lineage = Lineage(chateau.path)
    if kind in EVIDENCE_KINDS:
        rel = Relations(chateau.path)
        if undo:
            return {**out, "removed": rel.remove(kind, a.id, b.id)}
        link, created = rel.add(kind, a.id, b.id, reason=reason, by=by)
    elif kind == "contradicts":
        if undo:
            return {**out, "removed": lineage.undispute(a.id, b.id)}
        link, created = lineage.dispute(a.id, b.id, reason=reason, by=by)
    else:  # supersedes / updates: a replaces b
        if undo:
            current = lineage.status(b.id)["superseded_by"] == a.id
            return {**out, "removed": current and lineage.restore(b.id)}
        link, created = lineage.supersede(b.id, a.id, reason=reason, by=by)
    return {**out, "link": link, "created": created}


def check_source(kind: str) -> str:
    if kind and kind not in SOURCE_KINDS:
        raise LineageError(f"unknown source {kind!r}; use one of: {', '.join(SOURCE_KINDS)}")
    return kind or ""


def resolve_evidence(chateau, based_on=None, derived_from=None) -> list[tuple[str, str]]:
    """Check evidence IDs (or prefixes) before saving anything: ``[(kind, full_id), ...]``."""
    out = []
    for kind, ids in (("based_on", based_on), ("derived_from", derived_from)):
        if isinstance(ids, str):
            ids = [ids]
        for mid in ids or []:
            out.append((kind, _resolve(chateau, mid).id))
    return out


def attach_evidence(chateau, memory_id: str, evidence: list[tuple[str, str]], reason: str = "",
                    by: str = "") -> list[dict]:
    """Link a newly saved memory to evidence checked with :func:`resolve_evidence`."""
    rel = Relations(chateau.path)
    return [rel.add(kind, memory_id, target, reason=reason, by=by)[0] for kind, target in evidence]


def set_source(chateau, memory_id: str, kind: str, ref: str = "") -> dict:
    """Record where a stored memory came from (see :data:`SOURCE_KINDS`)."""
    if not kind:
        raise LineageError(f"say where it came from: one of {', '.join(SOURCE_KINDS)}")
    check_source(kind)
    drawer = _resolve(chateau, memory_id)
    changed = (drawer.source, drawer.source_ref) != (kind, ref or drawer.source_ref)
    drawer.source, drawer.source_ref = kind, ref or drawer.source_ref
    if changed:
        chateau.save_drawer(drawer)
    return {"memory": _summary(drawer), "source": kind, "source_ref": drawer.source_ref, "changed": changed}


def claim_type(drawer, evidence_links: list[dict]) -> str:
    """'inference', 'supported' (a conclusion resting on evidence) or 'direct' (recorded as given)."""
    if drawer.source == "inference" or any(lk["kind"] == "derived_from" for lk in evidence_links):
        return "inference"
    return "supported" if evidence_links else "direct"


def _brief(chateau, lineage: Lineage, memory_id: str, chars: int = 300) -> dict:
    drawer = chateau.find_drawer(memory_id)
    if drawer is None:
        return {"id": memory_id, "missing": True}
    info = lineage.status(memory_id)
    out = {"id": drawer.id, "text": drawer.text().strip()[:chars], "wing": drawer.wing, "room": drawer.room,
           "timestamp": drawer.timestamp, "source": drawer.source or None, "status": info["status"]}
    if drawer.source_ref:
        out["source_ref"] = drawer.source_ref
    if info["current_id"] != drawer.id:
        out["current_id"] = info["current_id"]
    if info["disputed_with"]:
        out["disputed_with"] = info["disputed_with"]
    return out


def _evidence_tree(chateau, lineage, rel, memory_id, depth, seen) -> list[dict]:
    out = []
    for lk in rel.evidence(memory_id):
        if lk["to"] in seen:
            continue
        seen.add(lk["to"])
        item = {"relation": lk["kind"], "reason": lk.get("reason") or None, "linked_at": lk["at"],
                **_brief(chateau, lineage, lk["to"])}
        if depth > 1 and not item.get("missing"):
            deeper = _evidence_tree(chateau, lineage, rel, lk["to"], depth - 1, seen)
            if deeper:
                item["evidence"] = deeper
        out.append(item)
    return out


def _concerns(memory: dict, evidence: list[dict], claim: str, prefix: str = "") -> list[str]:
    notes = []
    for ev in evidence:
        sid = ev["id"][:8]
        if ev.get("missing"):
            notes.append(f"{prefix}evidence {sid} no longer exists")
        elif ev["status"] == "superseded":
            notes.append(f"{prefix}evidence {sid} was corrected (current version: {ev['current_id'][:8]}); "
                         "check whether this still holds")
        elif ev["status"] == "disputed":
            notes.append(f"{prefix}evidence {sid} is disputed")
        if ev.get("evidence"):
            notes += _concerns(ev, ev["evidence"], "", prefix=f"{prefix}{sid} → ")
    if not prefix:
        if claim == "inference" and not evidence:
            notes.append("this is an inference with no recorded evidence")
        if memory["status"] == "superseded":
            notes.append(f"this memory is outdated; the current version is {memory['current_id'][:8]}")
        for other in memory.get("disputed_with", []):
            notes.append(f"conflicts with {other[:8]}, undecided")
    return notes


def explain(chateau, memory_id: str, query: Optional[str] = None, searcher=None, depth: int = 3) -> dict:
    """Everything that explains a memory: source, date, evidence, history, conflicts, relevance.

    The answer separates what was recorded directly from what was inferred,
    shows the evidence behind earlier versions as well as the current one,
    and lists ``concerns``: corrected or disputed evidence, unsupported
    inferences, unresolved conflicts. Nothing is rewritten.
    """
    drawer = _resolve(chateau, memory_id)
    lineage, rel = Lineage(chateau.path), Relations(chateau.path)
    memory = _brief(chateau, lineage, drawer.id, chars=1000)
    evidence = _evidence_tree(chateau, lineage, rel, drawer.id, depth, {drawer.id})
    claim = claim_type(drawer, rel.evidence(drawer.id))
    info = lineage.status(drawer.id)
    history = []
    for link in lineage.earlier_versions(drawer.id):
        prior = link["old"]
        history.append({**_brief(chateau, lineage, prior), "replaced_by": link["new"],
                        "replaced_at": link["at"], "reason": link.get("reason") or None,
                        "evidence": _evidence_tree(chateau, lineage, rel, prior, 1, {prior})})
    result = {
        "memory": memory,
        "source": drawer.source or "not recorded",
        "claim": claim,
        "evidence": evidence,
        "supports": [{"relation": lk["kind"], **_brief(chateau, lineage, lk["from"])}
                     for lk in rel.dependents(drawer.id)],
        "conflicts": [_brief(chateau, lineage, other) for other in info["disputed_with"]],
        "history": history,
        "concerns": _concerns(memory, evidence, claim),
    }
    if query and searcher is not None:
        result["relevance"] = relevance(searcher, drawer.id, query)
    return result


def relevance(searcher, memory_id: str, query: str, n: int = 50) -> dict:
    """How *memory_id* scores for *query*: rank and the parts of its score."""
    results = searcher.search(query, n=n)
    for rank, r in enumerate(results, 1):
        if memory_id in (r.get("id"), (r.get("metadata") or {}).get("drawer_id")):
            out = {"query": query, "rank": rank, "of": len(results)}
            for key in ("final_score", "semantic_score", "keyword_overlap", "recency_boost",
                        "temporal_closeness", "rerank_score"):
                if isinstance(r.get(key), (int, float)):
                    out[key] = round(r[key], 3)
            if r.get("via"):
                out["note"] = f"shown because it is the current version of {r['via'][:8]}"
            return out
    return {"query": query, "rank": None, "note": f"not among the top {n} results for this query"}


def check(chateau) -> dict:
    """Maintenance report: what needs a person's (or agent's) attention. Changes nothing.

    * ``stale_support``: current memories resting on evidence that has since
      been corrected or disputed.
    * ``unsupported_inferences``: current inferences with no recorded evidence.
    * ``unresolved_conflicts``: pairs marked as contradicting where both are
      still current.
    * ``broken_links``: links to memories that no longer exist.
    """
    lineage, rel = Lineage(chateau.path), Relations(chateau.path)
    exists: dict[str, bool] = {}

    def present(mid: str) -> bool:
        if mid not in exists:
            exists[mid] = chateau.find_drawer(mid) is not None
        return exists[mid]

    report: dict[str, list] = {"stale_support": [], "unsupported_inferences": [],
                               "unresolved_conflicts": [], "broken_links": []}
    for lk in rel.links():
        missing = [m for m in (lk["from"], lk["to"]) if not present(m)]
        if missing:
            report["broken_links"].append({**lk, "missing": missing})
            continue
        if lineage.status(lk["from"])["status"] == "superseded":
            continue  # history: the old position keeps the evidence it had
        ev = lineage.status(lk["to"])
        if ev["status"] in ("superseded", "disputed"):
            report["stale_support"].append({
                "memory": _brief(chateau, lineage, lk["from"]), "relation": lk["kind"],
                "evidence": _brief(chateau, lineage, lk["to"]), "problem": ev["status"]})
    for lk in lineage.links():
        if any(not present(m) for m in (lk["old"], lk["new"])):
            report["broken_links"].append({**lk, "missing": [m for m in (lk["old"], lk["new"]) if not present(m)]})
        elif lk["kind"] == "disputes" and all(lineage.status(m)["status"] != "superseded"
                                              for m in (lk["old"], lk["new"])):
            report["unresolved_conflicts"].append({
                "a": _brief(chateau, lineage, lk["old"]), "b": _brief(chateau, lineage, lk["new"]),
                "reason": lk.get("reason") or None, "since": lk["at"]})
    with_evidence = {lk["from"] for lk in rel.links()}
    for drawer in chateau.iter_drawers():
        if drawer.source == "inference" and drawer.id not in with_evidence \
                and lineage.status(drawer.id)["status"] != "superseded":
            report["unsupported_inferences"].append(_brief(chateau, lineage, drawer.id))
    report["ok"] = not any(report[k] for k in ("stale_support", "unsupported_inferences",
                                               "unresolved_conflicts", "broken_links"))
    return report
