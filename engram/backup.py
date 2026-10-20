"""Back up and restore everything Engram remembers, in one portable file.

``engram export backup.json`` writes a single JSON document (gzipped when the
name ends in ``.gz``) holding:

* every drawer, exactly as stored (IDs, timestamps, tags, pinned state and
  any fields this version does not know about),
* wing and room descriptions, closets (short summaries) and tunnels,
* the lineage ledger (what replaced what, when and why),
* the evidence ledger (which memories rest on which),
* provenance records,
* the knowledge graph (every triple, with its validity dates),
* the identity text and agent profiles and diaries.

Search indexes are not exported: they are rebuilt from the drawers on import,
so a backup works with any vector backend.

``engram import backup.json`` checks the whole file before changing
anything: format and version, every drawer and name, duplicate IDs, clashes
with memories already stored, and that the merged lineage is still sound. If
any check fails nothing is written. Importing the same file twice is safe;
memories already present are skipped. A memory that exists with different
content is an error unless ``overwrite=True``.

The format is documented in ``docs/backup-format.md``.
"""

from __future__ import annotations

import gzip
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from engram.chateau import RESERVED_DIRS, Chateau, Drawer, InvalidNameError, validate_name
from engram.lineage import LINEAGE_FILE, Lineage, LineageError, validate_links
from engram.relations import Relations, validate_relations

FORMAT = "engram-backup"
VERSION = 1
_KG_COLUMNS = ("subject", "predicate", "object", "valid_from", "valid_until", "confidence", "source")


class BackupError(ValueError):
    """The backup file is invalid or would clash with what is stored; nothing was changed."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        shown = "\n  - ".join(problems[:20])
        more = f"\n  … and {len(problems) - 20} more" if len(problems) > 20 else ""
        super().__init__(f"backup rejected, nothing was changed:\n  - {shown}{more}")


def _read_json(path: Path):
    return json.loads(path.read_text())


def _drawer_files(chateau_path: Path):
    for p in sorted(chateau_path.glob("*/*/*/*.json")):
        if p.parts[-4] not in RESERVED_DIRS:
            yield p


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def collect(chateau: Chateau, kg_path: Optional[Path] = None, identity_path: Optional[Path] = None,
            agents_dir: Optional[Path] = None) -> dict:
    """Everything Engram stores, as one JSON-serialisable dict."""
    from engram import __version__

    root = chateau.path
    data: dict = {
        "format": FORMAT, "version": VERSION, "engram_version": __version__,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "wings": [], "rooms": [], "drawers": [], "closets": [], "tunnels": {},
        "lineage": [], "relations": [], "provenance": [], "knowledge_graph": [], "identity": None, "agents": {},
    }
    for p in sorted(root.glob("*/wing.json")):
        data["wings"].append(_read_json(p))
    for p in sorted(root.glob("*/*/room.json")):
        data["rooms"].append(_read_json(p))
    for p in _drawer_files(root):
        try:
            data["drawers"].append(_read_json(p))
        except json.JSONDecodeError:
            continue
    for p in sorted(root.glob("*/*/*/closet.es")):
        wing, room, hall = p.parts[-4:-1]
        data["closets"].append({"wing": wing, "room": room, "hall": hall, "content": p.read_text()})
    for p in sorted(root.glob("*/tunnels.json")):
        data["tunnels"][p.parent.name] = _read_json(p)
    data["lineage"] = Lineage(root).links()
    data["relations"] = Relations(root).links()
    for p in sorted((root / "provenance").glob("*.json")):
        data["provenance"].append(_read_json(p))
    if kg_path and Path(kg_path).exists():
        conn = sqlite3.connect(str(kg_path))
        try:
            rows = conn.execute(f"SELECT {', '.join(_KG_COLUMNS)} FROM triples ORDER BY id").fetchall()
        except sqlite3.OperationalError:
            rows = []
        conn.close()
        data["knowledge_graph"] = [dict(zip(_KG_COLUMNS, r)) for r in rows]
    if identity_path and Path(identity_path).exists():
        data["identity"] = Path(identity_path).read_text()
    if agents_dir and Path(agents_dir).is_dir():
        for p in sorted(Path(agents_dir).iterdir()):
            if p.is_file() and p.suffix in (".json", ".jsonl"):
                data["agents"][p.name] = p.read_text()
    return data


def export_backup(dest: Path, chateau: Chateau, **kwargs) -> dict:
    """Write a backup to *dest* (gzipped if it ends in ``.gz``). Returns counts."""
    data = collect(chateau, **kwargs)
    text = json.dumps(data, indent=1, ensure_ascii=False)
    dest = Path(dest).expanduser()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    if dest.suffix == ".gz":
        with gzip.open(tmp, "wt", encoding="utf-8") as fh:
            fh.write(text)
    else:
        tmp.write_text(text, encoding="utf-8")
    tmp.replace(dest)
    return summary(data)


def summary(data: dict) -> dict:
    return {
        "drawers": len(data.get("drawers", [])),
        "lineage_links": len(data.get("lineage", [])),
        "evidence_links": len(data.get("relations", [])),
        "kg_triples": len(data.get("knowledge_graph", [])),
        "wings": len(data.get("wings", [])),
        "rooms": len(data.get("rooms", [])),
        "provenance": len(data.get("provenance", [])),
        "agent_files": len(data.get("agents", {})),
    }


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def load_backup(src: Path) -> dict:
    src = Path(src).expanduser()
    try:
        with open(src, "rb") as fh:
            raw = fh.read()
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        return json.loads(raw.decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise BackupError([f"cannot read {src}: {exc}"]) from exc


def _check_names(problems: list[str], where: str, **names) -> bool:
    ok = True
    for kind, value in names.items():
        try:
            validate_name(value, kind)
        except InvalidNameError as exc:
            problems.append(f"{where}: {exc}")
            ok = False
    return ok


def plan_import(data: dict, chateau: Chateau, overwrite: bool = False) -> dict:
    """Validate *data* against what is stored. Returns the import plan or raises BackupError."""
    problems: list[str] = []
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise BackupError(["not an Engram backup (missing \"format\": \"engram-backup\")"])
    version = data.get("version")
    if not isinstance(version, int) or version > VERSION:
        raise BackupError([f"backup format version {version!r} is newer than this Engram supports "
                           f"({VERSION}); upgrade Engram first"])

    existing = {p.stem: p for p in _drawer_files(chateau.path)}
    to_write, skipped, seen = [], 0, set()
    for i, d in enumerate(data.get("drawers") or []):
        where = f"drawer #{i + 1}"
        if not isinstance(d, dict):
            problems.append(f"{where}: not an object")
            continue
        missing = [k for k in ("id", "content", "wing", "room", "hall") if not isinstance(d.get(k), str)]
        if missing:
            problems.append(f"{where}: missing or non-text {', '.join(missing)}")
            continue
        if not _check_names(problems, f"{where} ({d['id']})", **{"drawer id": d["id"], "wing": d["wing"],
                                                                  "room": d["room"], "hall": d["hall"]}):
            continue
        if d["wing"] in RESERVED_DIRS:
            problems.append(f"{where}: wing name {d['wing']!r} is reserved")
            continue
        try:
            Drawer.from_dict(d)
        except TypeError as exc:
            problems.append(f"{where} ({d['id']}): {exc}")
            continue
        if d["id"] in seen:
            problems.append(f"{where}: duplicate ID {d['id']} in the backup")
            continue
        seen.add(d["id"])
        if d["id"] in existing:
            try:
                same = _read_json(existing[d["id"]]) == d
            except json.JSONDecodeError:
                same = False
            if same:
                skipped += 1
                continue
            if not overwrite:
                problems.append(f"memory {d['id']} already exists with different content "
                                "(use --overwrite to replace it)")
                continue
        to_write.append(d)

    current_links = Lineage(chateau.path).links()
    have = {(lk["kind"], lk["old"], lk["new"]) for lk in current_links}
    new_links = []
    for lk in data.get("lineage") or []:
        if not isinstance(lk, dict):
            problems.append(f"lineage link {lk!r}: not an object")
            continue
        if (lk.get("kind"), lk.get("old"), lk.get("new")) not in have:
            new_links.append(lk)
            have.add((lk.get("kind"), lk.get("old"), lk.get("new")))
    merged_links = current_links + new_links
    try:
        validate_links(merged_links, known_ids=set(existing) | seen)
    except LineageError as exc:
        problems.append(f"lineage: {exc}")

    current_rel = Relations(chateau.path).links()
    have_rel = {(lk["kind"], lk["from"], lk["to"]) for lk in current_rel}
    new_rel = []
    for lk in data.get("relations") or []:  # absent in backups from before 1.9
        if not isinstance(lk, dict):
            problems.append(f"evidence link {lk!r}: not an object")
            continue
        key = (lk.get("kind"), lk.get("from"), lk.get("to"))
        if key not in have_rel:
            new_rel.append(lk)
            have_rel.add(key)
    merged_rel = current_rel + new_rel
    try:
        validate_relations(merged_rel, known_ids=set(existing) | seen)
    except LineageError as exc:
        problems.append(f"evidence links: {exc}")

    for kind, items in (("wing", data.get("wings") or []), ("room", data.get("rooms") or [])):
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                problems.append(f"{kind} entry {item!r}: missing name")
            elif kind == "room" and not isinstance(item.get("wing"), str):
                problems.append(f"room {item['name']!r}: missing wing")
            else:
                names = {kind: item["name"]}
                if kind == "room":
                    names["wing"] = item["wing"]
                _check_names(problems, f"{kind} {item['name']!r}", **names)
    for c in data.get("closets") or []:
        if not isinstance(c, dict) or not all(isinstance(c.get(k), str) for k in ("wing", "room", "hall", "content")):
            problems.append(f"closet entry {c!r}: malformed")
        else:
            _check_names(problems, "closet", wing=c["wing"], room=c["room"], hall=c["hall"])
    for wing, tunnels in (data.get("tunnels") or {}).items():
        if _check_names(problems, "tunnels", wing=wing) and not isinstance(tunnels, list):
            problems.append(f"tunnels for {wing!r}: not a list")
    for rec in data.get("provenance") or []:
        if not isinstance(rec, dict) or not isinstance(rec.get("memory_id"), str):
            problems.append(f"provenance record {rec!r}: missing memory_id")
        else:
            _check_names(problems, "provenance", **{"memory id": rec["memory_id"]})
    for row in data.get("knowledge_graph") or []:
        if not isinstance(row, dict) or not all(isinstance(row.get(k), str) for k in ("subject", "predicate", "object")):
            problems.append(f"knowledge-graph triple {row!r}: needs text subject, predicate and object")
    for name, text in (data.get("agents") or {}).items():
        if not isinstance(text, str) or Path(name).suffix not in (".json", ".jsonl"):
            problems.append(f"agent file {name!r}: must be a .json or .jsonl text file")
        else:
            _check_names(problems, "agent file", **{"file name": name})
    identity = data.get("identity")
    if identity is not None and not isinstance(identity, str):
        problems.append("identity: must be text")

    if problems:
        raise BackupError(problems)
    return {"drawers": to_write, "skipped": skipped, "links": new_links, "merged_links": merged_links,
            "relations": new_rel, "merged_relations": merged_rel}


def import_backup(src, chateau: Chateau, backend=None, kg_path: Optional[Path] = None,
                  identity_path: Optional[Path] = None, agents_dir: Optional[Path] = None,
                  overwrite: bool = False, dry_run: bool = False, preference_summaries: bool = True) -> dict:
    """Restore a backup into *chateau* (and reindex into *backend*). Returns counts.

    *src* is a path or an already-loaded dict. Raises :class:`BackupError`
    before writing anything if the backup is invalid.
    """
    data = src if isinstance(src, dict) else load_backup(src)
    plan = plan_import(data, chateau, overwrite=overwrite)
    report = {"drawers_added": len(plan["drawers"]), "drawers_skipped": plan["skipped"],
              "lineage_links_added": len(plan["links"]), "evidence_links_added": len(plan["relations"]),
              "kg_triples_added": 0, "dry_run": dry_run}
    if dry_run:
        report["kg_triples_in_backup"] = len(data.get("knowledge_graph") or [])
        return report

    root = chateau.path
    for w in data.get("wings") or []:
        p = root / w["name"] / "wing.json"
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(w, indent=2))
    for r in data.get("rooms") or []:
        p = root / r["wing"] / r["name"] / "room.json"
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(r, indent=2))

    written = []
    for d in plan["drawers"]:
        for old in root.glob(f"*/*/*/{d['id']}.json"):  # overwrite: drop copies stored elsewhere
            old.unlink()
        dest = root / d["wing"] / d["room"] / d["hall"] / f"{d['id']}.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(d, indent=2))
        written.append(d)

    for c in data.get("closets") or []:
        p = root / c["wing"] / c["room"] / c["hall"] / "closet.es"
        if overwrite or not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(c["content"])
    for wing, tunnels in (data.get("tunnels") or {}).items():
        p = root / wing / "tunnels.json"
        current = _read_json(p) if p.exists() else []
        merged = current + [t for t in tunnels if t not in current]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(merged, indent=2))
    prov_dir = root / "provenance"
    for rec in data.get("provenance") or []:
        p = prov_dir / f"{rec['memory_id']}.json"
        if overwrite or not p.exists():
            prov_dir.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(rec, indent=2))
    if plan["links"]:
        Lineage(root).replace_all(plan["merged_links"])
    if plan["relations"]:
        Relations(root).replace_all(plan["merged_relations"])

    if kg_path and data.get("knowledge_graph"):
        from engram.knowledge_graph import KnowledgeGraph
        KnowledgeGraph(Path(kg_path))  # creates the schema if needed
        conn = sqlite3.connect(str(kg_path))
        with conn:
            present = {tuple(r) for r in conn.execute(
                "SELECT subject, predicate, object, valid_from, valid_until FROM triples")}
            for row in data["knowledge_graph"]:
                key = tuple(row.get(k) for k in _KG_COLUMNS[:5])
                if key in present:
                    continue
                present.add(key)
                conn.execute(f"INSERT INTO triples ({', '.join(_KG_COLUMNS)}) VALUES (?, ?, ?, ?, ?, ?, ?)",
                             tuple(row.get(k, 1.0 if k == "confidence" else ("" if k == "source" else None))
                                   for k in _KG_COLUMNS))
                report["kg_triples_added"] += 1
        conn.close()
    if identity_path and data.get("identity") and not Path(identity_path).exists():
        Path(identity_path).parent.mkdir(parents=True, exist_ok=True)
        Path(identity_path).write_text(data["identity"])
    if agents_dir:
        for name, text in (data.get("agents") or {}).items():
            p = Path(agents_dir) / name
            p.parent.mkdir(parents=True, exist_ok=True)
            if not p.exists():
                p.write_text(text)
            elif name.endswith(".jsonl"):  # diaries: add entries we don't have
                have = set(p.read_text().splitlines())
                extra = [ln for ln in text.splitlines() if ln and ln not in have]
                if extra:
                    with p.open("a") as fh:
                        fh.write("".join(ln + "\n" for ln in extra))

    if backend is not None and written:
        report["chunks_indexed"] = reindex(backend, written, preference_summaries)
    return report


def reindex(backend, drawers: list[dict], preference_summaries: bool = True, batch: int = 200) -> int:
    """Index restored drawers into *backend*."""
    from engram.indexing import index_drawers
    from engram.preferences import preference_summary

    total = 0
    for i in range(0, len(drawers), batch):
        items = []
        for d in drawers[i:i + batch]:
            drawer = Drawer.from_dict(d)
            meta = {"wing": drawer.wing, "room": drawer.room, "hall": drawer.hall,
                    "timestamp": drawer.timestamp, "pinned": drawer.pinned}
            extra = []
            if preference_summaries:
                summary_text = preference_summary(drawer.content)
                if summary_text:
                    extra.append(summary_text)
            items.append((drawer.id, drawer.content, meta, extra))
        total += index_drawers(backend, items, replace=True)
    return total


__all__ = ["BackupError", "collect", "export_backup", "import_backup", "load_backup", "plan_import",
           "reindex", "summary", "LINEAGE_FILE"]
