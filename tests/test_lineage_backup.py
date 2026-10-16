"""Memory lineage (corrections, history) and backup/restore.

The acceptance tests at the top describe the behaviour 1.6.0 promises:
a corrected memory stays findable, search names the current one first, and a
backup restored into an empty château keeps both facts.
"""

import gzip
import json

import pytest

from engram.backup import BackupError, export_backup, import_backup, load_backup
from engram.chateau import Chateau, Drawer
from engram.lineage import (
    Lineage,
    LineageError,
    annotate,
    correct_memory,
    memory_history,
    short_id,
    supersede_memory,
    validate_links,
)
from engram.mcp_server import EngramMCPServer, _handle_message

SQLITE = "Decision: the app stores everything in SQLite because it is simple and local."
POSTGRES = "Decision: we migrated the app from SQLite to PostgreSQL because we need concurrent writers."


def call(server, tool, **args):
    msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}}
    resp = _handle_message(server, msg)
    if "error" in resp:
        raise RuntimeError(resp["error"]["message"])
    return json.loads(resp["result"]["content"][0]["text"])


@pytest.fixture
def server(engram_home):
    return EngramMCPServer()


def _ids(results):
    return [r["id"] for r in results]


# ---------------------------------------------------------------------------
# Acceptance
# ---------------------------------------------------------------------------

def test_superseded_memory_stays_findable_but_current_one_comes_first(server):
    old = call(server, "engram_add_memory", content=SQLITE, wing="app", room="db")
    fix = call(server, "engram_correct", memory_id=old["id"], content=POSTGRES, reason="needed concurrent writes")
    new_id = fix["new"]["id"]

    hits = call(server, "engram_search", query="which database SQLite PostgreSQL", n=5)
    assert _ids(hits)[:2] == [new_id, old["id"]]
    current, outdated = hits[0], hits[1]
    assert current["status"] == "current" and current["supersedes"] == [old["id"]]
    assert outdated["status"] == "superseded"
    assert outdated["superseded_by"] == new_id and outdated["current_id"] == new_id
    assert outdated["reason"] == "needed concurrent writes"

    # A search that only matches the old note still surfaces its replacement first.
    hits = call(server, "engram_search", query="simple and local", n=5)
    assert _ids(hits)[:2] == [new_id, old["id"]]


def test_backup_restored_into_empty_chateau_keeps_the_correction(server, engram_home, tmp_path):
    old = call(server, "engram_add_memory", content=SQLITE, wing="app", room="db")
    new_id = call(server, "engram_correct", memory_id=old["id"], content=POSTGRES)["new"]["id"]
    call(server, "engram_kg_add", subject="app", predicate="uses", object="PostgreSQL", valid_from="2026-04-09")
    backup = tmp_path / "backup.json.gz"
    export_backup(backup, server.palace, kg_path=engram_home / "kg.db")

    fresh = Chateau(chateau_path=tmp_path / "fresh")
    from engram.backends import get_backend
    report = import_backup(backup, fresh, backend=get_backend("sqlitevec", db_path=tmp_path / "fresh.db"),
                           kg_path=tmp_path / "fresh_kg.db")
    assert report["drawers_added"] == 2 and report["lineage_links_added"] == 1
    assert report["kg_triples_added"] == 1
    assert Lineage(fresh.path).status(old["id"])["superseded_by"] == new_id
    restored = {d.id: d for d in fresh.iter_drawers()}
    original = {d.id: d for d in server.palace.iter_drawers()}
    assert {k: v.to_dict() for k, v in restored.items()} == {k: v.to_dict() for k, v in original.items()}

    from engram.searcher import Searcher
    searcher = Searcher(get_backend("sqlitevec", db_path=tmp_path / "fresh.db"), fresh, {"hybrid_weight": 0.3})
    hits = searcher.search("which database SQLite PostgreSQL", n=5, no_decay=True)
    assert _ids(hits)[:2] == [new_id, old["id"]] and hits[1]["status"] == "superseded"


# ---------------------------------------------------------------------------
# Lineage rules
# ---------------------------------------------------------------------------

def test_supersede_is_idempotent_and_refuses_unsound_links(tmp_path):
    lin = Lineage(tmp_path)
    link, created = lin.supersede("a", "b", reason="r")
    assert created and lin.status("a")["status"] == "superseded"
    assert lin.supersede("a", "b") == (link, False)          # retry: no duplicate
    assert len(lin.links()) == 1
    with pytest.raises(LineageError, match="already replaced by b"):
        lin.supersede("a", "c")                               # conflicting chain
    with pytest.raises(LineageError, match="itself outdated"):
        lin.supersede("c", "a")                               # replacement must be current
    with pytest.raises(LineageError, match="itself"):
        lin.supersede("x", "x")
    lin.supersede("b", "c")
    with pytest.raises(LineageError):
        lin.supersede("c", "a")                               # would close a loop
    assert lin.current_id("a") == "c"
    assert [(lk["old"], lk["new"]) for lk in lin.history("b")] == [("a", "b"), ("b", "c")]


def test_restore_and_dispute(tmp_path):
    lin = Lineage(tmp_path)
    lin.supersede("a", "b")
    assert lin.restore("a") is True and lin.status("a")["status"] == "current"
    assert lin.restore("a") is False
    _, created = lin.dispute("x", "y", reason="unclear")
    assert created and lin.dispute("y", "x")[1] is False
    assert lin.status("x")["status"] == "disputed" and lin.status("y")["disputed_with"] == ["x"]


def test_ledger_is_valid_json_after_every_write(tmp_path):
    lin = Lineage(tmp_path)
    for i in range(5):
        lin.supersede(f"m{i}", f"m{i + 1}")
    data = json.loads((tmp_path / "lineage.json").read_text())
    assert data["format"] == "engram-lineage" and len(data["links"]) == 5
    assert not list(tmp_path.glob("*.tmp"))


def test_validate_links_catches_cycles_and_unknown_ids():
    with pytest.raises(LineageError, match="loops"):
        validate_links([{"kind": "supersedes", "old": "a", "new": "b"},
                        {"kind": "supersedes", "old": "b", "new": "a"}])
    with pytest.raises(LineageError, match="unknown"):
        validate_links([{"kind": "supersedes", "old": "a", "new": "b"}], known_ids={"a"})
    with pytest.raises(LineageError, match="replaced by both"):
        validate_links([{"kind": "supersedes", "old": "a", "new": "b"},
                        {"kind": "supersedes", "old": "a", "new": "c"}])


def test_annotate_without_links_only_adds_status(tmp_path):
    results = [{"id": "a", "text": "x"}, {"id": "b", "text": "y"}]
    out = annotate(results, Lineage(tmp_path), lambda _id: None)
    assert out == [{"id": "a", "text": "x", "status": "current"}, {"id": "b", "text": "y", "status": "current"}]


def test_annotate_pulls_in_a_replacement_search_missed(tmp_path):
    palace = Chateau(chateau_path=tmp_path)
    new = Drawer(content=POSTGRES, wing="w", room="r", hall="facts")
    palace.save_drawer(new)
    lin = Lineage(tmp_path)
    lin.supersede("old", new.id)
    out = annotate([{"id": "old", "text": SQLITE, "final_score": 0.9}], lin, palace.find_drawer)
    assert _ids(out) == [new.id, "old"]
    assert out[0]["via"] == "old" and out[0]["text"] == POSTGRES and out[0]["supersedes"] == ["old"]


# ---------------------------------------------------------------------------
# Operations on stored memories
# ---------------------------------------------------------------------------

def test_correct_memory_retry_and_rollback(server, monkeypatch):
    old = call(server, "engram_add_memory", content=SQLITE, wing="app", room="db")
    first = correct_memory(server.palace, server.backend, old["id"], POSTGRES)
    again = correct_memory(server.palace, server.backend, old["id"], POSTGRES)
    assert first["created"] and not again["created"] and again["new"]["id"] == first["new"]["id"]
    with pytest.raises(LineageError, match="already replaced"):
        correct_memory(server.palace, server.backend, old["id"], "something else")

    # If recording the link fails, the new memory is removed again.
    other = call(server, "engram_add_memory", content="We deploy on Fridays.", wing="app", room="ops")
    before = {d.id for d in server.palace.iter_drawers()}
    monkeypatch.setattr(Lineage, "supersede", lambda *a, **k: (_ for _ in ()).throw(LineageError("boom")))
    with pytest.raises(LineageError, match="boom"):
        correct_memory(server.palace, server.backend, other["id"], "We deploy on Mondays.")
    assert {d.id for d in server.palace.iter_drawers()} == before
    assert "Mondays" not in json.dumps(call(server, "engram_search", query="deploy Mondays", n=5))


def test_history_reports_the_chain(server):
    a = call(server, "engram_add_memory", content="Team lunch is on Tuesday.", wing="t", room="r")
    b = call(server, "engram_correct", memory_id=a["id"], content="Team lunch moved to Wednesday.", reason="room")
    c = call(server, "engram_correct", memory_id=b["new"]["id"], content="Team lunch is now on Thursday.")
    h = call(server, "engram_history", memory_id=a["id"])
    assert h["status"] == "superseded" and h["current_id"] == c["new"]["id"]
    assert [s["new_text"] for s in h["history"]] == ["Team lunch moved to Wednesday.", "Team lunch is now on Thursday."]
    assert memory_history(server.palace, short_id(c["new"]["id"]))["status"] == "current"


def test_mcp_supersede_undo_dispute_and_add_with_supersedes(server):
    a = call(server, "engram_add_memory", content=SQLITE, wing="app", room="db")
    b = call(server, "engram_add_memory", content=POSTGRES, wing="app", room="db")
    assert any(p["id"] == a["id"] for p in b["possible_updates"])  # hint, nothing linked yet
    assert Lineage(server.palace.path).links() == []

    out = call(server, "engram_supersede", old_id=a["id"], new_id=b["id"], reason="migrated")
    assert out["created"] and call(server, "engram_supersede", old_id=a["id"], new_id=b["id"])["created"] is False
    assert call(server, "engram_supersede", old_id=a["id"], undo=True)["restored"] is True

    c = call(server, "engram_add_memory", content="We are trying CockroachDB.", wing="app", room="db",
             supersedes=a["id"], reason="experiment")
    assert c["supersedes"]["old"] == a["id"] and Lineage(server.palace.path).current_id(a["id"]) == c["id"]

    # A refused link leaves nothing behind.
    count = sum(1 for _ in server.palace.iter_drawers())
    with pytest.raises(RuntimeError, match="already replaced"):
        call(server, "engram_add_memory", content="Or maybe MySQL.", wing="app", room="db", supersedes=a["id"])
    assert sum(1 for _ in server.palace.iter_drawers()) == count

    d = call(server, "engram_dispute", id_a=b["id"], id_b=c["id"], reason="two notes disagree")
    assert d["created"] and call(server, "engram_history", memory_id=b["id"])["status"] == "disputed"


def test_unknown_or_ambiguous_ids(server, tmp_path):
    with pytest.raises(RuntimeError, match="no memory"):
        call(server, "engram_correct", memory_id="nope-not-there", content="x")
    palace = Chateau(chateau_path=tmp_path / "p")
    for i in range(2):
        palace.save_drawer(Drawer(content=f"n{i}", wing="w", room="r", hall="facts", id=f"abcd-{i}"))
    with pytest.raises(LookupError, match="matches 2"):
        palace.find_drawer("abcd")
    assert palace.find_drawer("abcd-1").content == "n1"
    with pytest.raises(LineageError, match="matches 2"):
        supersede_memory(palace, "abcd", "abcd-1")


def test_short_id():
    assert short_id("c6e0b7b4-323b-44f9-bfce-12c3d565c0d9") == "c6e0b7b4"
    assert short_id("file-05aa607ad25c3307de680a6c") == "file-05aa607a"


def test_drawers_from_newer_versions_still_load(tmp_path):
    d = Drawer(content="x", wing="w", room="r", hall="facts").to_dict()
    assert Drawer.from_dict({**d, "some_future_field": 1}).content == "x"


def test_provenance_directory_is_not_a_wing(tmp_path):
    palace = Chateau(chateau_path=tmp_path)
    palace.create_wing("real")
    (tmp_path / "provenance").mkdir()
    assert [w.name for w in palace.list_wings()] == ["real"]


# ---------------------------------------------------------------------------
# Backup and restore
# ---------------------------------------------------------------------------

def _populated(tmp_path):
    palace = Chateau(chateau_path=tmp_path / "src")
    a = Drawer(content=SQLITE, wing="app", room="db", hall="facts", tags=["db"], pinned=True)
    b = Drawer(content=POSTGRES, wing="app", room="db", hall="facts")
    for d in (a, b):
        palace.save_drawer(d)
    Lineage(palace.path).supersede(a.id, b.id, reason="migrated")
    return palace, a, b


def test_export_format_and_dry_run(tmp_path):
    palace, a, b = _populated(tmp_path)
    export_backup(tmp_path / "b.json", palace)
    data = json.loads((tmp_path / "b.json").read_text())
    assert data["format"] == "engram-backup" and data["version"] == 1
    assert {d["id"] for d in data["drawers"]} == {a.id, b.id}
    assert data["lineage"][0]["old"] == a.id and data["wings"] and data["rooms"]

    target = Chateau(chateau_path=tmp_path / "dst")
    report = import_backup(tmp_path / "b.json", target, dry_run=True)
    assert report["drawers_added"] == 2 and list(target.iter_drawers()) == []
    assert not (target.path / "lineage.json").exists()


def test_import_is_idempotent_and_gzip_round_trips(tmp_path):
    palace, a, _ = _populated(tmp_path)
    export_backup(tmp_path / "b.json.gz", palace)
    assert gzip.open(tmp_path / "b.json.gz").read(1) == b"{"
    target = Chateau(chateau_path=tmp_path / "dst")
    import_backup(tmp_path / "b.json.gz", target)
    second = import_backup(tmp_path / "b.json.gz", target)
    assert second["drawers_added"] == 0 and second["drawers_skipped"] == 2 and second["lineage_links_added"] == 0
    assert len(Lineage(target.path).links()) == 1
    restored = target.find_drawer(a.id)
    assert restored.to_dict() == a.to_dict()  # id, timestamp, tags, pinned preserved


def test_invalid_backups_change_nothing(tmp_path):
    palace, a, b = _populated(tmp_path)
    export_backup(tmp_path / "b.json", palace)
    good = load_backup(tmp_path / "b.json")
    target = Chateau(chateau_path=tmp_path / "dst")

    def rejected(data, match):
        with pytest.raises(BackupError, match=match):
            import_backup(json.loads(json.dumps(data)), target)
        assert list(target.iter_drawers()) == [] and not (target.path / "lineage.json").exists()

    rejected({**good, "format": "other"}, "not an Engram backup")
    rejected({**good, "version": 99}, "newer")
    rejected({**good, "drawers": good["drawers"] + [{**good["drawers"][0]}]}, "duplicate ID")
    rejected({**good, "drawers": [{**good["drawers"][0], "wing": "../escape"}]}, "Invalid wing")
    loop = [{"kind": "supersedes", "old": a.id, "new": b.id}, {"kind": "supersedes", "old": b.id, "new": a.id}]
    rejected({**good, "lineage": loop}, "loops")
    rejected({**good, "lineage": [{"kind": "supersedes", "old": a.id, "new": "missing"}]}, "unknown memory")
    with pytest.raises(BackupError, match="cannot read"):
        load_backup(tmp_path / "missing.json")


def test_conflicting_memory_needs_overwrite(tmp_path):
    palace, a, _ = _populated(tmp_path)
    export_backup(tmp_path / "b.json", palace)
    target = Chateau(chateau_path=tmp_path / "dst")
    target.save_drawer(Drawer(content="different", wing="app", room="db", hall="facts", id=a.id))
    with pytest.raises(BackupError, match="already exists with different content"):
        import_backup(tmp_path / "b.json", target)
    assert target.find_drawer(a.id).content == "different"
    import_backup(tmp_path / "b.json", target, overwrite=True)
    assert target.find_drawer(a.id).content == SQLITE


def test_cli_export_import_round_trip(engram_home, tmp_path):
    from typer.testing import CliRunner

    from engram.cli import app

    runner = CliRunner()
    palace = Chateau()
    old = Drawer(content=SQLITE, wing="app", room="db", hall="facts")
    palace.save_drawer(old)
    res = runner.invoke(app, ["correct", old.id[:8], POSTGRES, "--reason", "migrated"])
    assert res.exit_code == 0, res.output
    assert "replacing" in res.output
    res = runner.invoke(app, ["history", old.id[:8]])
    assert res.exit_code == 0 and "superseded" in res.output and "migrated" in res.output
    res = runner.invoke(app, ["export", str(tmp_path / "b.json")])
    assert res.exit_code == 0 and "2 memories" in res.output and "1 correction" in res.output
    res = runner.invoke(app, ["import", str(tmp_path / "b.json"), "--dry-run"])
    assert res.exit_code == 0 and "Would add 0 memories (2 already present)" in res.output
    res = runner.invoke(app, ["supersede", old.id[:8], "--undo"])
    assert res.exit_code == 0 and "current again" in res.output
    res = runner.invoke(app, ["correct", "zzzz-missing", "x"])
    assert res.exit_code == 1 and "no memory" in res.output
