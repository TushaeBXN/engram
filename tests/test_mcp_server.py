"""Tests for engram.mcp_server — the MCP tools Claude and other clients call."""

import json
import os
import subprocess
import sys

import pytest

from engram.mcp_server import TOOLS, EngramMCPServer, _handle_message


@pytest.fixture
def server(engram_home):
    return EngramMCPServer()


def call(server, tool, **args):
    """Call a tool through the JSON-RPC handler, the same path a client uses."""
    msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
           "params": {"name": tool, "arguments": args}}
    resp = _handle_message(server, msg)
    if "error" in resp:
        raise RuntimeError(resp["error"]["message"])
    return json.loads(resp["result"]["content"][0]["text"])


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

def test_initialize(server):
    resp = _handle_message(server, {"jsonrpc": "2.0", "id": 7, "method": "initialize"})
    assert resp["id"] == 7
    assert resp["result"]["serverInfo"]["name"] == "engram"


def test_tools_list_matches_implemented_handlers(server):
    resp = _handle_message(server, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = [t["name"] for t in resp["result"]["tools"]]
    assert names == [t["name"] for t in TOOLS]
    assert len(names) == len(set(names))
    for name in names:
        assert callable(getattr(server, f"_tool_{name}", None)), f"{name} has no handler"


def test_tool_schemas_are_well_formed():
    for tool in TOOLS:
        schema = tool["inputSchema"]
        assert schema["type"] == "object"
        for required in schema.get("required", []):
            assert required in schema["properties"], f"{tool['name']}: {required}"


def test_unknown_method_returns_error(server):
    resp = _handle_message(server, {"jsonrpc": "2.0", "id": 3, "method": "nope"})
    assert resp["error"]["code"] == -32601


def test_notifications_get_no_response(server):
    assert _handle_message(server, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert _handle_message(server, {"jsonrpc": "2.0", "method": "nope"}) is None


def test_unknown_tool_returns_error(server):
    with pytest.raises(RuntimeError, match="Unknown tool"):
        call(server, "engram_does_not_exist")


def test_bad_arguments_return_error_not_crash(server):
    with pytest.raises(RuntimeError, match="TypeError"):
        call(server, "engram_add_memory", nonsense=True)


# ---------------------------------------------------------------------------
# Memory tools
# ---------------------------------------------------------------------------

def test_add_search_get_delete_round_trip(server):
    added = call(server, "engram_add_memory", content="We migrated auth to OAuth2 last sprint",
                 wing="work", room="auth", hall="events")
    assert added["wing"] == "work" and added["hall"] == "events"

    results = call(server, "engram_search", query="OAuth2 auth migration", wing="work")
    assert any(r["id"] == added["id"] for r in results)

    fetched = call(server, "engram_get_drawer", drawer_id=added["id"])
    assert fetched["id"] == added["id"]

    assert call(server, "engram_delete_drawer", wing="work", room="auth",
                hall="events", drawer_id=added["id"]) == {"deleted": True}
    assert call(server, "engram_get_drawer", drawer_id=added["id"]) is None
    assert all(r["id"] != added["id"] for r in call(server, "engram_search", query="OAuth2"))


def test_add_memory_rejects_path_traversal(server, engram_home):
    with pytest.raises(RuntimeError, match="InvalidNameError"):
        call(server, "engram_add_memory", content="x", wing="../../escaped")
    assert not (engram_home.parent / "escaped").exists()
    assert call(server, "engram_status")["drawers"] == 0


def test_pin(server):
    added = call(server, "engram_add_memory", content="Always run migrations in a transaction")
    pinned = call(server, "engram_pin", drawer_id=added["id"])
    assert pinned["pinned"] is True and pinned["drawer"]["pinned"] is True
    assert call(server, "engram_pin", drawer_id="missing")["pinned"] is False


def test_wings_rooms_and_status(server):
    call(server, "engram_create_wing", name="work", description="day job")
    call(server, "engram_create_room", wing="work", name="auth")
    call(server, "engram_add_memory", content="Tokens expire after one hour", wing="work", room="auth")

    assert [w["name"] for w in call(server, "engram_list_wings")] == ["work"]
    assert [r["name"] for r in call(server, "engram_list_rooms", wing="work")] == ["auth"]
    assert call(server, "engram_status") == {"wings": 1, "rooms": 1, "drawers": 1, "closets": 0}


def test_wake_up_and_load_room(server):
    call(server, "engram_add_memory", content="Prefer float32 on CPU", wing="ml", room="perf")
    assert isinstance(call(server, "engram_wake_up"), str)
    assert "ml/perf" in call(server, "engram_load_room", wing="ml", room="perf")


def test_compress_decompress(server):
    text = "The authentication module has a dependency on the database."
    compressed = call(server, "engram_compress", text=text)
    assert len(compressed) < len(text)
    assert isinstance(call(server, "engram_decompress", text=compressed), str)


# ---------------------------------------------------------------------------
# Knowledge graph, diary, audit, replay
# ---------------------------------------------------------------------------

def test_knowledge_graph_tools(server):
    call(server, "engram_kg_add", subject="Maya", predicate="owns", object="auth",
         valid_from="2026-01-01")
    assert [t["object"] for t in call(server, "engram_kg_query", entity="Maya")] == ["auth"]
    assert call(server, "engram_kg_invalidate", subject="Maya", predicate="owns",
                object="auth")["invalidated"] == 1
    assert call(server, "engram_kg_query", entity="Maya") == []
    assert len(call(server, "engram_kg_timeline", entity="Maya")) == 1


def test_diary_tools(server):
    call(server, "engram_diary_write", agent="claude", entry="Started auth refactor", tags=["auth"])
    entries = call(server, "engram_diary_read", agent="claude")
    assert len(entries) == 1
    assert entries[0]["agent"] == "claude" and entries[0]["tags"] == ["auth"]
    assert entries[0]["content"]  # stored ES-compressed


def test_diary_rejects_path_traversal(server):
    with pytest.raises(RuntimeError, match="InvalidNameError"):
        call(server, "engram_diary_write", agent="../../escaped", entry="x")


def test_audit_and_replay(server):
    call(server, "engram_add_memory", content="Deployed v2 yesterday", wing="work", room="release")
    assert isinstance(call(server, "engram_audit"), dict)
    assert "Deployed v2" in call(server, "engram_replay", room="release", wing="work")
    assert isinstance(call(server, "engram_replay", room="release", wing="work", format="json"), (list, dict))


# ---------------------------------------------------------------------------
# Real stdio session
# ---------------------------------------------------------------------------

def test_stdio_session(tmp_path):
    env = dict(os.environ, HOME=str(tmp_path / "home"), ENGRAM_VECTOR_BACKEND="sqlitevec")
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "engram_add_memory", "arguments": {"content": "hello from stdio"}}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "engram_status", "arguments": {}}},
    ]
    stdin = "\n".join(json.dumps(r) for r in requests) + "\nnot json\n"
    proc = subprocess.run([sys.executable, "-m", "engram.mcp_server"], input=stdin,
                          capture_output=True, text=True, env=env, timeout=120)
    responses = [json.loads(line) for line in proc.stdout.splitlines()]
    assert [r.get("id") for r in responses] == [1, 2, 3, None]
    status = json.loads(responses[2]["result"]["content"][0]["text"])
    assert status["drawers"] == 1
    assert responses[3]["error"]["code"] == -32700
