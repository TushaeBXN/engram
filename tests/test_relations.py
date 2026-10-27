"""Evidence links, sources, `engram why` and `engram check` (engram.relations).

The scenario at the top is the one 1.9.0 is built for: a position rests on
a primary source, the evidence is later corrected, and Engram shows what the
earlier position rested on and that the current one needs review, without
rewriting anything.
"""

import json

import pytest
from typer.testing import CliRunner

from engram.backup import BackupError, export_backup, import_backup, load_backup
from engram.chateau import Chateau, Drawer
from engram.cli import app
from engram.lineage import Lineage, LineageError
from engram.mcp_server import EngramMCPServer, _handle_message
from engram.relations import (
    Relations,
    check,
    explain,
    link_memories,
    set_source,
    validate_relations,
)

TEXT = "Article I, Section 2: Representatives shall be apportioned among the several States according to their numbers."
VIEW = "My view: apportionment by population is the constitutional baseline for drawing districts."
NEWS = "Report: the state legislature adopted a new congressional map in 2025."


def call(server, tool, **args):
    msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}}
    resp = _handle_message(server, msg)
    if "error" in resp:
        raise RuntimeError(resp["error"]["message"])
    return json.loads(resp["result"]["content"][0]["text"])


@pytest.fixture
def server(engram_home):
    return EngramMCPServer()


# ---------------------------------------------------------------------------
# Acceptance
# ---------------------------------------------------------------------------

def test_a_position_keeps_its_evidence_trail_through_corrections(server):
    text = call(server, "engram_add_memory", content=TEXT, wing="library", room="constitution",
                source="primary", source_ref="U.S. Const. art. I, § 2")
    news = call(server, "engram_add_memory", content=NEWS, wing="amy", room="news", source="secondary")
    view = call(server, "engram_add_memory", content=VIEW, wing="amy", room="views", source="inference",
                based_on=[text["id"]], derived_from=[news["id"][:8]])
    assert [lk["kind"] for lk in view["evidence"]] == ["based_on", "derived_from"]

    why = call(server, "engram_why", memory_id=view["id"], query="how should districts be apportioned?")
    assert why["claim"] == "inference" and why["source"] == "inference"
    assert {e["id"]: e["source"] for e in why["evidence"]} == {text["id"]: "primary", news["id"]: "secondary"}
    assert why["evidence"][0]["source_ref"] == "U.S. Const. art. I, § 2"
    assert why["relevance"]["rank"] >= 1 and "semantic_score" in why["relevance"]
    assert why["concerns"] == []
    assert call(server, "engram_why", memory_id=text["id"])["supports"][0]["id"] == view["id"]

    # The news report turns out to be wrong; the correction replaces it.
    fixed = call(server, "engram_correct", memory_id=news["id"],
                 content="Correction: the 2025 map was blocked by a court and never took effect.",
                 reason="court ruling")
    assert fixed["new"]["id"] != news["id"]
    why = call(server, "engram_why", memory_id=view["id"])
    assert any("was corrected" in c and fixed["new"]["id"][:8] in c for c in why["concerns"])
    report = call(server, "engram_check")
    assert not report["ok"] and report["stale_support"][0]["memory"]["id"] == view["id"]

    # Amy revises her view; the old one keeps the evidence it had.
    revised = call(server, "engram_correct", memory_id=view["id"], source="inference",
                   content="My view, revised: the map never took effect; apportionment by population still governs.",
                   based_on=[text["id"], fixed["new"]["id"]], reason="the news was corrected")
    why = call(server, "engram_why", memory_id=revised["new"]["id"])
    assert {e["id"] for e in why["evidence"]} == {text["id"], fixed["new"]["id"]}
    assert why["history"][0]["id"] == view["id"]
    assert {e["id"] for e in why["history"][0]["evidence"]} == {text["id"], news["id"]}
    assert why["concerns"] == []
    assert call(server, "engram_check")["ok"]  # the outdated view is history, not a problem


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------

def _palace(tmp_path, *texts, **source):
    palace = Chateau(chateau_path=tmp_path / "chateau")
    drawers = []
    for t in texts:
        d = Drawer(content=t, wing="w", room="r", hall="facts", **source)
        palace.save_drawer(d)
        drawers.append(d)
    return palace, drawers


def test_link_kinds_map_onto_evidence_and_lineage(tmp_path):
    palace, (a, b, c) = _palace(tmp_path, "conclusion A", "evidence B", "rival C")
    out = link_memories(palace, a.id, "based_on", b.id[:8], reason="B says so")
    assert out["created"] and Relations(palace.path).evidence(a.id)[0]["to"] == b.id
    assert not link_memories(palace, a.id, "based_on", b.id)["created"]  # safe to retry
    link_memories(palace, a.id, "contradicts", c.id)
    assert Lineage(palace.path).status(c.id)["disputed_with"] == [a.id]
    assert link_memories(palace, a.id, "contradicts", c.id, undo=True)["removed"]
    assert Lineage(palace.path).status(c.id)["status"] == "current"
    link_memories(palace, c.id, "updates", b.id)
    assert Lineage(palace.path).status(b.id)["superseded_by"] == c.id
    assert link_memories(palace, c.id, "supersedes", b.id, undo=True)["removed"]
    assert link_memories(palace, a.id, "based_on", b.id, undo=True)["removed"]
    assert Relations(palace.path).links() == []


def test_evidence_cannot_loop_or_point_at_itself(tmp_path):
    palace, (a, b, c) = _palace(tmp_path, "A", "B", "C")
    link_memories(palace, a.id, "based_on", b.id)
    link_memories(palace, b.id, "derived_from", c.id)
    with pytest.raises(LineageError, match="leads back"):
        link_memories(palace, c.id, "based_on", a.id)
    with pytest.raises(LineageError, match="itself"):
        link_memories(palace, a.id, "based_on", a.id)
    with pytest.raises(LineageError, match="unknown relationship"):
        link_memories(palace, a.id, "proves", b.id)
    with pytest.raises(LineageError, match="no memory"):
        link_memories(palace, a.id, "based_on", "nonexistent-id")
    with pytest.raises(LineageError, match="malformed"):
        validate_relations([{"kind": "based_on", "from": "x"}])


def test_sources_are_recorded_and_unset_sources_are_not_written(tmp_path):
    palace, (a,) = _palace(tmp_path, "The user prefers oat milk.")
    raw = json.loads(next(palace.path.glob("*/*/*/*.json")).read_text())
    assert "source" not in raw and "source_ref" not in raw  # same file as older versions wrote
    assert explain(palace, a.id)["source"] == "not recorded"
    out = set_source(palace, a.id, "user", "Telegram, 20 Oct")
    assert out["changed"] and palace.find_drawer(a.id).source_ref == "Telegram, 20 Oct"
    assert not set_source(palace, a.id, "user")["changed"]  # keeps the ref, nothing to write
    with pytest.raises(LineageError, match="unknown source"):
        set_source(palace, a.id, "rumour")


def test_check_reports_without_changing_anything(tmp_path):
    palace, (guess, x, y, z) = _palace(tmp_path, "An inference with nothing behind it", "X", "Y", "Z")
    set_source(palace, guess.id, "inference")
    Lineage(palace.path).dispute(x.id, y.id, reason="sources disagree")
    link_memories(palace, z.id, "based_on", y.id)
    palace.delete_drawer_by_id(x.id)
    before = (Lineage(palace.path).links(), Relations(palace.path).links())
    report = check(palace)
    assert [m["id"] for m in report["unsupported_inferences"]] == [guess.id]
    assert report["broken_links"][0]["missing"] == [x.id]
    assert report["unresolved_conflicts"] == []  # x is gone: reported as a broken link instead
    assert (Lineage(palace.path).links(), Relations(palace.path).links()) == before
    palace2, (p, q, r) = _palace(tmp_path / "two", "P", "Q", "R")
    Lineage(palace2.path).dispute(p.id, q.id)
    link_memories(palace2, r.id, "based_on", q.id)
    report = check(palace2)
    assert report["unresolved_conflicts"][0]["a"]["id"] == p.id
    assert report["stale_support"][0]["problem"] == "disputed"


def test_correction_keeps_the_source_unless_told_otherwise(engram_home, tmp_path):
    from engram.backends import get_backend
    from engram.lineage import correct_memory
    palace, (a,) = _palace(tmp_path, "Population: 330 million", source="tool", source_ref="search")
    backend = get_backend("sqlitevec", db_path=tmp_path / "vec.db")
    new = correct_memory(palace, backend, a.id, "Population: 335 million")["new"]
    assert (palace.find_drawer(new["id"]).source, palace.find_drawer(new["id"]).source_ref) == ("tool", "search")
    newer = correct_memory(palace, backend, new["id"], "Population: 336 million", source="primary")["new"]
    assert (palace.find_drawer(newer["id"]).source, palace.find_drawer(newer["id"]).source_ref) == ("primary", "")


def test_add_memory_refuses_bad_evidence_before_saving(server):
    with pytest.raises(RuntimeError, match="no memory"):
        call(server, "engram_add_memory", content="orphan conclusion", based_on=["missing-id"])
    with pytest.raises(RuntimeError, match="'source' must be one of"):
        call(server, "engram_add_memory", content="orphan conclusion", source="vibes")
    assert list(server.palace.iter_drawers()) == []


# ---------------------------------------------------------------------------
# Backup, CLI
# ---------------------------------------------------------------------------

def test_backup_carries_sources_and_evidence(tmp_path):
    palace, (a, b) = _palace(tmp_path, "conclusion", "evidence", source="primary", source_ref="doc")
    link_memories(palace, a.id, "based_on", b.id)
    export_backup(tmp_path / "b.json", palace)
    data = load_backup(tmp_path / "b.json")
    assert data["relations"][0]["to"] == b.id
    fresh = Chateau(chateau_path=tmp_path / "fresh")
    report = import_backup(tmp_path / "b.json", fresh)
    assert report["evidence_links_added"] == 1 and fresh.find_drawer(a.id).source_ref == "doc"
    assert import_backup(tmp_path / "b.json", fresh)["evidence_links_added"] == 0
    data["relations"].append({"kind": "based_on", "from": b.id, "to": a.id, "at": "x"})
    with pytest.raises(BackupError, match="leads back"):
        import_backup(data, Chateau(chateau_path=tmp_path / "other"))
    del data["relations"]  # a backup from before 1.9
    assert import_backup(data, Chateau(chateau_path=tmp_path / "old"))["evidence_links_added"] == 0


def test_cli_link_source_why_check(engram_home):
    palace = Chateau()
    ev = Drawer(content=TEXT, wing="library", room="constitution", hall="facts")
    view = Drawer(content=VIEW, wing="amy", room="views", hall="facts")
    palace.save_drawer(ev)
    palace.save_drawer(view)
    runner = CliRunner()
    assert "Linked" in runner.invoke(app, ["link", view.id[:8], "based_on", ev.id[:8], "--reason", "text"]).output
    assert "primary source" in runner.invoke(app, ["source", ev.id[:8], "primary", "--ref", "art. I"]).output
    res = runner.invoke(app, ["why", view.id[:8]])
    assert res.exit_code == 0 and "Evidence" in res.output and "art. I" in res.output
    assert "a conclusion resting on evidence" in res.output
    assert json.loads(runner.invoke(app, ["why", view.id[:8], "--json"]).output)["claim"] == "supported"
    assert "Nothing needs review" in runner.invoke(app, ["check"]).output
    runner.invoke(app, ["source", view.id[:8], "inference"])
    runner.invoke(app, ["link", view.id[:8], "based_on", ev.id[:8], "--undo"])
    res = runner.invoke(app, ["check"])
    assert "No evidence" in res.output
    assert runner.invoke(app, ["link", view.id[:8], "proves", ev.id[:8]]).exit_code == 1


def test_check_follows_stale_evidence_up_the_chain(server):
    from engram.lineage import correct_memory
    fact = call(server, "engram_add_memory", content="Limit is 10.", wing="w", room="r", source="primary")["id"]
    finding = call(server, "engram_add_memory", content="So the cap is 10.", wing="w", room="r",
                   source="inference", based_on=[fact])["id"]
    plan_ = call(server, "engram_add_memory", content="Plan for 10.", wing="w", room="r",
                 based_on=[finding])["id"]
    correct_memory(server.palace, server.backend, fact, "Limit is 20.")
    stale = {i["memory"]["id"]: i for i in check(server.palace)["stale_support"]}
    assert stale[finding]["problem"] == "superseded"
    assert stale[plan_]["problem"] == "upstream" and stale[plan_]["through"] == [finding]
