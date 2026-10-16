# Engram backup format (version 1)

`engram export FILE` writes one JSON document. If `FILE` ends in `.gz` it is gzip-compressed; `engram import` accepts either form.

```json
{
  "format": "engram-backup",
  "version": 1,
  "engram_version": "1.6.0",
  "exported_at": "2026-10-16T15:04:05+00:00",
  "wings":   [{"name": "myapp", "created": "…", "description": ""}],
  "rooms":   [{"name": "db", "wing": "myapp", "created": "…", "description": ""}],
  "drawers": [{"id": "c6e0b7b4-…", "content": "…", "wing": "myapp", "room": "db", "hall": "facts",
               "timestamp": "…", "pinned": false, "decay_weight": 1.0, "tags": [], "compressed": false}],
  "closets": [{"wing": "myapp", "room": "db", "hall": "facts", "content": "…"}],
  "tunnels": {"myapp": [{"room": "db", "source_wing": "myapp", "target_wing": "ops", "created": "…"}]},
  "lineage": [{"kind": "supersedes", "old": "file-05aa…", "new": "c6e0b7b4-…",
               "at": "…", "reason": "needed concurrent writers", "by": "cli"}],
  "provenance": [{"memory_id": "…", "source": "user", "confidence": 0.8, "…": "…"}],
  "knowledge_graph": [{"subject": "app", "predicate": "uses", "object": "PostgreSQL",
                       "valid_from": "2026-04-09", "valid_until": null, "confidence": 1.0, "source": "mcp"}],
  "identity": "I am Amy, …",
  "agents": {"amy.json": "…", "amy_diary.jsonl": "…"}
}
```

## What each part is

| Key | Contents |
|---|---|
| `drawers` | Every memory exactly as stored on disk, including fields a newer Engram may add. IDs and timestamps are kept, so lineage links and provenance still match after a restore. |
| `lineage` | The correction ledger (`lineage.json`): `supersedes` links (`new` replaced `old`) and `disputes` links (two memories conflict, undecided). |
| `wings`, `rooms`, `closets`, `tunnels` | The château's structure and short summaries. |
| `provenance` | Provenance records, if any were made. |
| `knowledge_graph` | Every triple, with its validity dates. Row IDs are not kept. |
| `identity`, `agents` | The wake-up identity text, agent profiles and diaries. |

Search indexes (ChromaDB, FAISS, sqlite-vec and the keyword index) are **not** in the backup. `engram import` rebuilds them from the drawers, so a backup can be restored into any backend.

Settings (`config.json`) are not included either, so a restore never changes your configuration.

## How import checks a backup

The whole file is checked before anything is written. If any check fails, the import stops with a list of problems and **nothing is changed**:

- `format` is `engram-backup` and `version` is one this Engram understands.
- Every drawer has text `id`, `content`, `wing`, `room` and `hall`, and every name is a safe single path component.
- No ID appears twice in the backup.
- A drawer whose ID already exists must be identical, or the import needs `--overwrite`.
- The merged lineage (what is stored plus what is imported) only links memories that exist, replaces each memory at most once, and has no cycles.
- Knowledge-graph rows have text subject, predicate and object.

## Re-running and merging

Importing the same backup twice is safe. Identical memories, links and triples are skipped. Diaries gain only the entries they don't already have. Existing identity text, agent profiles, closets and provenance records are left alone (closets and provenance are replaced with `--overwrite`).

`engram import FILE --dry-run` runs every check and reports what would be added, without writing.

## Compatibility

Readers must reject a `version` greater than they support. New optional keys may be added within version 1. Readers ignore keys they don't know, and drawer fields this version does not recognise are carried through export and import unchanged.
