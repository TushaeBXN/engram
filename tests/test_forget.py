"""engram forget: delete a memory and clean everything that pointed at it."""

import json

import pytest
from typer.testing import CliRunner

from engram.cli import app
from engram.forget import forget, plan
from engram.lineage import Lineage, LineageError
from engram.mcp_server import EngramMCPServer
from engram.relations import Relations, check


@pytest.fixture
def server(engram_home):
    return EngramMCPServer()


def add(server, text, **kw):
    return server.dispatch("engram_add_memory", {"content": text, "wing": "brian", "room": "pref", **kw})["id"]


def ids(server, query):
    return [r["id"] for r in server.dispatch("engram_search", {"query": query, "n": 10})]


def test_forgetting_removes_the_memory_from_disk_and_from_search(server):
    mid = add(server, "Brian's favorite bakery is Rosewater Bakery and he always gets the lemon scone.")
    keep = add(server, "The office printer is called Gutenberg.")
    assert mid in ids(server, "favorite bakery Rosewater")
    forget(server.palace, server.backend, mid[:8])
    assert server.palace.find_drawer(mid) is None and keep in ids(server, "printer Gutenberg")
    assert mid not in ids(server, "favorite bakery Rosewater") and mid not in ids(server, "lemon scone")


def test_forgetting_the_newer_half_of_a_correction_makes_the_old_one_current_again(server):
    old = add(server, "Brian's favorite coffee shop is Krankies, a local spot.")
    new = server.dispatch("engram_correct", {"memory_id": old, "content": "Brian's favorite coffee shop is Copper Kettle.",
                                             "reason": "test"})["new"]["id"]
    assert Lineage(server.palace.path).status(old)["status"] == "superseded"
    what = plan(server.palace, new)
    assert [m["id"] for m in what["becomes_current_again"]] == [old]
    forget(server.palace, server.backend, new)
    assert Lineage(server.palace.path).status(old)["status"] == "current"
    assert Lineage(server.palace.path).links() == [] and check(server.palace)["ok"]
    top = server.dispatch("engram_search", {"query": "favorite coffee shop", "n": 3})[0]
    assert top["id"] == old and top["status"] == "current"


def test_forgetting_evidence_leaves_dependents_and_check_lists_the_orphans(server):
    evidence = add(server, "Article I says representatives are apportioned by population.", source="primary")
    view = add(server, "My view: population is the baseline.", source="inference", based_on=[evidence])
    what = plan(server.palace, evidence)
    assert [m["id"] for m in what["memories_that_lose_it_as_evidence"]] == [view]
    forget(server.palace, server.backend, evidence)
    assert server.palace.find_drawer(view) is not None
    (marker,) = Relations(server.palace.path).links()
    assert marker["forgotten"] and marker["to"] == evidence and marker["reason"] == ""
    report = check(server.palace)
    assert [lk["to"] for lk in report["broken_links"] if lk["forgotten"]] == [evidence] and not report["ok"]


def test_conflict_marks_and_provenance_go_too(server):
    a, b = add(server, "Standup is at 9:30 every day."), add(server, "Standup is at 10:15 every day.")
    server.dispatch("engram_dispute", {"id_a": a, "id_b": b})
    prov = server.palace.path / "provenance"
    prov.mkdir(exist_ok=True)
    (prov / f"{a}.json").write_text("{}")
    forget(server.palace, server.backend, a)
    assert Lineage(server.palace.path).status(b)["status"] == "current" and not (prov / f"{a}.json").exists()


def test_cli_shows_what_would_happen_and_only_deletes_with_yes(server):
    mid = add(server, "Brian's favorite bakery is Rosewater Bakery.")
    runner = CliRunner()
    res = runner.invoke(app, ["forget", mid[:8]])
    assert res.exit_code == 0 and "Nothing was deleted" in res.output and "Rosewater" in res.output
    assert server.palace.find_drawer(mid) is not None
    res = runner.invoke(app, ["forget", mid[:8], "--yes"])
    assert res.exit_code == 0 and "Forgot" in res.output and server.palace.find_drawer(mid) is None
    assert runner.invoke(app, ["forget", "no-such-id", "--yes"]).exit_code == 1


def test_unknown_ids_are_refused_and_nothing_is_touched(server):
    a = add(server, "first memory about tabs")
    with pytest.raises(LineageError):
        plan(server.palace, "zzzzzzzz")
    assert server.palace.find_drawer(a) is not None


def test_the_mcp_delete_tool_cleans_links_too(server):
    old = add(server, "We use SQLite.")
    new = server.dispatch("engram_correct", {"memory_id": old, "content": "We use PostgreSQL."})["new"]
    out = server.dispatch("engram_delete_drawer", {"wing": "brian", "room": "pref", "hall": "facts", "drawer_id": new["id"]})
    assert out == {"deleted": True} and Lineage(server.palace.path).links() == []
    assert server.dispatch("engram_delete_drawer", {"wing": "brian", "room": "pref", "hall": "facts", "drawer_id": "nope"}) == {"deleted": False}
    json.dumps(out)


def test_a_supported_claim_does_not_silently_become_unsupported(server):
    from engram.relations import explain
    law = add(server, "Statute 12 caps the fee at 5%.", source="primary")
    decision = add(server, "We charge 5%.", based_on=[law])
    forget(server.palace, server.backend, law)
    why = explain(server.palace, decision)
    assert why["claim"] == "supported" and why["evidence"][0]["forgotten"]
    assert any("was deleted" in c for c in why["concerns"])
    assert "Statute" not in json.dumps(why["evidence"]) and not check(server.palace)["ok"]


def test_a_forgotten_marker_survives_export_import_and_can_be_dismissed(server, tmp_path):
    from engram.backup import export_backup, import_backup
    from engram.chateau import Chateau
    from engram.relations import link_memories
    law = add(server, "Statute 12 caps the fee at 5%.", source="primary")
    decision = add(server, "We charge 5%.", based_on=[law])
    forget(server.palace, server.backend, law)
    export_backup(tmp_path / "b.json", server.palace)
    fresh = Chateau(chateau_path=tmp_path / "fresh")
    assert import_backup(tmp_path / "b.json", fresh)["evidence_links_added"] == 1
    assert [lk["to"] for lk in check(fresh)["broken_links"]] == [law]
    out = link_memories(fresh, decision, "based_on", law[:8], undo=True)
    assert out["removed"] and check(fresh)["ok"]


def test_forgetting_the_conclusion_drops_its_own_links(server):
    law = add(server, "Statute 12 caps the fee at 5%.", source="primary")
    decision = add(server, "We charge 5%.", based_on=[law])
    forget(server.palace, server.backend, decision)
    assert Relations(server.palace.path).links() == [] and check(server.palace)["ok"]
