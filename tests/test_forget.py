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
    assert server.palace.find_drawer(view) is not None and Relations(server.palace.path).links() == []
    assert [m["id"] for m in check(server.palace)["unsupported_inferences"]] == [view]


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
