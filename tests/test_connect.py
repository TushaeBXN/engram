"""engram connect: adding Engram's MCP server to other AI apps, and the MCP instructions."""

import json
import sys

import pytest
from typer.testing import CliRunner

from engram import connect as cn
from engram.cli import app


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    monkeypatch.setattr(cn.platform, "system", lambda: "Linux")
    return tmp_path


def _server():
    return {"command": sys.executable, "args": ["-m", "engram.mcp_server"]}


def test_json_apps_get_an_engram_entry_and_keep_everything_else(home):
    path = home / ".cursor" / "mcp.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"mcpServers": {"github": {"command": "gh-mcp"}}, "theme": "dark"}))
    cursor = cn.apps()["cursor"]
    assert cn.connect(cursor) == "added"
    data = json.loads(path.read_text())
    assert data["mcpServers"] == {"github": {"command": "gh-mcp"}, "engram": _server()}
    assert data["theme"] == "dark"
    assert json.loads((home / ".cursor" / "mcp.json.bak").read_text())["mcpServers"] == {"github": {"command": "gh-mcp"}}
    assert cn.connect(cursor) == "unchanged"  # running it again changes nothing


def test_an_outdated_engram_entry_is_updated(home):
    path = home / ".gemini" / "settings.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"mcpServers": {"engram": {"command": "old-engram-mcp"}}}))
    assert cn.connect(cn.apps()["gemini"]) == "updated"
    assert json.loads(path.read_text())["mcpServers"]["engram"] == _server()


def test_vscode_uses_its_own_key_and_type(home):
    assert cn.connect(cn.apps()["vscode"]) == "added"
    data = json.loads((home / ".config" / "Code" / "User" / "mcp.json").read_text())
    assert data == {"servers": {"engram": {"type": "stdio", **_server()}}}


def test_codex_toml_is_appended_once(home):
    path = home / ".codex" / "config.toml"
    path.parent.mkdir()
    path.write_text('model = "gpt-5"\n')
    codex = cn.apps()["codex"]
    assert cn.connect(codex) == "added"
    text = path.read_text()
    assert text.startswith('model = "gpt-5"\n\n[mcp_servers.engram]\n')
    assert f'command = {json.dumps(sys.executable)}' in text and 'args = ["-m", "engram.mcp_server"]' in text
    assert cn.connect(codex) == "unchanged"
    path.write_text('[mcp_servers.engram]\ncommand = "something-else"\n')
    with pytest.raises(ValueError, match="update it by hand"):
        cn.connect(codex)


def test_unreadable_settings_are_left_alone(home):
    path = home / ".cursor" / "mcp.json"
    path.parent.mkdir()
    path.write_text("{ // a comment\n}")
    with pytest.raises(ValueError, match="isn't plain JSON"):
        cn.connect(cn.apps()["cursor"])
    assert path.read_text() == "{ // a comment\n}"


def test_manual_apps_get_a_snippet(home):
    zed = cn.apps()["zed"]
    with pytest.raises(ValueError):
        cn.connect(zed)
    assert json.loads(cn.snippet(zed)) == {"context_servers": {"engram": _server()}}


def test_cli_connect(home):
    runner = CliRunner()
    listing = runner.invoke(app, ["connect"])
    assert listing.exit_code == 0 and "engram connect cursor" in listing.output
    res = runner.invoke(app, ["connect", "windsurf"])
    assert res.exit_code == 0 and "Engram added" in res.output
    assert "engram" in json.loads((home / ".codeium" / "windsurf" / "mcp_config.json").read_text())["mcpServers"]
    assert runner.invoke(app, ["connect", "nope"]).exit_code == 1
    (home / ".gemini").mkdir()
    res = runner.invoke(app, ["connect", "all"])
    assert res.exit_code == 0 and "Gemini CLI" in res.output and "already has Engram" in res.output
    assert not (home / ".cursor").exists()  # 'all' only touches apps that look installed
    res = runner.invoke(app, ["connect", "claude-code"])
    assert "claude mcp add engram --" in res.output and "install-hooks --apply" in res.output


# ---------------------------------------------------------------------------
# What every MCP client gets
# ---------------------------------------------------------------------------

def test_mcp_initialize_sends_memory_instructions(engram_home):
    from engram.mcp_server import EngramMCPServer, _handle_message
    resp = _handle_message(EngramMCPServer(), {"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    text = resp["result"]["instructions"]
    assert "engram_recall" in text and "engram_correct" in text and "OUTDATED" in text


def test_engram_recall_tool(engram_home):
    from engram.mcp_server import EngramMCPServer, _handle_message

    server = EngramMCPServer()

    def call(tool, **args):
        msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}}
        return json.loads(_handle_message(server, msg)["result"]["content"][0]["text"])

    call("engram_add_memory", content="We switched the auth library from Passport to Lucia sessions.",
         wing="myapp", room="auth")
    server.cfg["recall_min_relevance"] = 0.2
    note = call("engram_recall", message="why did we switch the auth library to Lucia?")
    assert note.startswith("[Engram memory") and "Passport to Lucia" in note
    assert call("engram_recall", message="how do I bake sourdough bread at home") == \
        "Nothing in memory is clearly relevant to this."
