"""Auto-recall for Claude Code (engram.recall) and installing its hook."""

import io
import json

import pytest

from engram import recall as rc
from engram.backends import get_backend
from engram.chateau import Chateau, Drawer
from engram.indexing import index_drawer
from engram.lineage import correct_memory
from engram.searcher import Searcher

CFG = {"hybrid_weight": 0.3, "keyword_search": False, "recall_min_relevance": 0.2, "recall_max": 3}


@pytest.fixture
def mem(engram_home, tmp_path):
    palace = Chateau(chateau_path=tmp_path / "chateau")
    backend = get_backend("sqlitevec", db_path=tmp_path / "vec.db")

    def add(text, wing="myapp", room="auth"):
        d = Drawer(content=text, wing=wing, room=room, hall="facts")
        palace.save_drawer(d)
        index_drawer(backend, d.id, d.content, {"wing": wing, "room": room, "hall": "facts",
                                                "timestamp": d.timestamp, "pinned": False})
        return d

    searcher = Searcher(backend, palace, CFG)
    return palace, backend, searcher, add


def test_relevant_memories_are_recalled_with_where_and_when(mem):
    _, _, searcher, add = mem
    d = add("We switched the auth library from Passport to Lucia because Passport sessions leaked memory.")
    add("Team lunch is on Thursdays at the taco place.", room="social")
    note = rc.recall("why did we switch the auth library away from Passport?", "s1", searcher, CFG)
    assert note.startswith(rc.HEADER)
    lines = note.splitlines()[1:]
    assert len(lines) == 1 and "Passport to Lucia" in lines[0]
    assert lines[0].startswith(f"- (myapp/auth · {d.timestamp[:10]})") and f"[id {d.id[:13]}]" in lines[0]


def test_nothing_is_added_when_nothing_is_relevant(mem):
    _, _, searcher, add = mem
    add("We switched the auth library from Passport to Lucia.")
    assert rc.recall("please format this json file nicely", "s1", searcher, CFG) == ""


def test_short_messages_slash_commands_and_off_switch_add_nothing(mem):
    _, _, searcher, add = mem
    add("We switched the auth library from Passport to Lucia.")
    assert rc.recall("auth?", "s1", searcher, CFG) == ""
    assert rc.recall("/compact the auth library discussion", "s1", searcher, CFG) == ""
    assert rc.recall("why did we switch the auth library?", "s1", searcher, {**CFG, "recall": False}) == ""


def test_a_memory_is_shown_once_per_session(mem):
    _, _, searcher, add = mem
    add("We switched the auth library from Passport to Lucia.")
    question = "remind me why we switched the auth library"
    assert rc.recall(question, "session-a", searcher, CFG)
    assert rc.recall(question, "session-a", searcher, CFG) == ""   # already given to this session
    assert rc.recall(question, "session-b", searcher, CFG)          # a new session gets it again
    assert rc.recall(question, "session-a", searcher, CFG, remember=False)  # previews ignore it


def test_excluded_wings_and_the_limit(mem):
    _, _, searcher, add = mem
    for i in range(5):
        add(f"Auth library note {i}: we use Lucia for sessions and auth.")
    add("Federalist No. 51: auth library sessions ambition", wing="library", room="federalist")
    note = rc.recall("what auth library do we use for sessions?", "s1", searcher, CFG)
    assert note.count("\n- ") == 3 and "library/federalist" not in note


def test_corrections_show_current_first_and_label_the_outdated(mem):
    palace, backend, searcher, add = mem
    old = add("The app database is SQLite because it is simple and local.", room="db")
    new_id = correct_memory(palace, backend, old.id, "The app database is now PostgreSQL for concurrent writers.")["new"]["id"]
    note = rc.recall("which database does the app use, SQLite?", "s1", searcher, CFG)
    lines = note.splitlines()[1:]
    assert lines[0].startswith("- CURRENT ") and "PostgreSQL" in lines[0] and f"[id {new_id[:13]}]" in lines[0]
    assert lines[1].startswith(f"- OUTDATED (replaced by {new_id[:8]}) ")


def test_long_memories_are_trimmed():
    note = rc.format_note([{"id": "abc", "text": "word " * 500, "metadata": {"wing": "w"}}])
    assert len(note.splitlines()[1]) < rc.SNIPPET_CHARS + 60 and note.rstrip().endswith("[id abc]")


def test_hook_prints_claude_code_context_json(mem, monkeypatch, capsys):
    _, _, searcher, add = mem
    add("We switched the auth library from Passport to Lucia because sessions leaked memory.")
    monkeypatch.setattr(rc, "recall", lambda prompt, session_id="", cwd=None: rc.format_note(
        rc.select(searcher.search(prompt, n=12), CFG)))
    payload = {"session_id": "abc", "hook_event_name": "UserPromptSubmit",
               "prompt": "why did we move off Passport for auth?"}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    rc.main()
    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "Passport to Lucia" in out["hookSpecificOutput"]["additionalContext"]
    from engram import config
    log = (config.ENGRAM_DIR / "recall.log").read_text().splitlines()
    assert json.loads(log[-1])["shown"] == 1 and "prompt" not in log[-1]


def test_hook_never_breaks_a_prompt(engram_home, monkeypatch, capsys):
    def boom(*a, **k):
        raise RuntimeError("chromadb exploded")
    monkeypatch.setattr(rc, "recall", boom)
    monkeypatch.setattr("sys.stdin", io.StringIO('{"prompt": "anything at all here"}'))
    rc.main()
    assert capsys.readouterr().out == ""
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    rc.main()
    assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# Installing the hook
# ---------------------------------------------------------------------------

def test_merge_hook_settings_keeps_existing_settings_and_is_idempotent(tmp_path):
    from engram.cli import hook_settings, merge_hook_settings
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"model": "x", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "mine"}]}]}}))
    snippet = hook_settings({"engram_save_hook.sh": "/h/engram_save_hook.sh",
                             "engram_precompact_hook.sh": "/h/engram_precompact_hook.sh"},
                            recall_command="/py -m engram.recall", python="/py")
    assert merge_hook_settings(path, snippet) == 3
    data = json.loads(path.read_text())
    assert data["model"] == "x" and data["hooks"]["Stop"][0]["hooks"][0]["command"] == "mine"
    assert data["hooks"]["UserPromptSubmit"][0]["hooks"][0] == {
        "type": "command", "command": "/py -m engram.recall", "timeout": 30}
    assert json.loads((tmp_path / "settings.json.bak").read_text())["model"] == "x"
    assert merge_hook_settings(path, snippet) == 0  # second run changes nothing
    assert len(json.loads(path.read_text())["hooks"]["UserPromptSubmit"]) == 1


def test_merge_refuses_broken_settings(tmp_path):
    from engram.cli import hook_settings, merge_hook_settings
    path = tmp_path / "settings.json"
    path.write_text("{ not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        merge_hook_settings(path, hook_settings({"engram_save_hook.sh": "a", "engram_precompact_hook.sh": "b"}, None))
    assert path.read_text() == "{ not json"


def test_cli_install_hooks_apply_and_recall_preview(engram_home, tmp_path):
    from typer.testing import CliRunner

    from engram.cli import app
    settings = tmp_path / "claude" / "settings.json"
    res = CliRunner().invoke(app, ["install-hooks", "--dest", str(tmp_path / "hooks"), "--apply",
                                   "--settings", str(settings)])
    assert res.exit_code == 0, res.output
    hooks = json.loads(settings.read_text())["hooks"]
    assert set(hooks) == {"PostToolUse", "PreCompact", "UserPromptSubmit"}
    assert hooks["UserPromptSubmit"][0]["hooks"][0]["command"].endswith(" -m engram.recall")
    res = CliRunner().invoke(app, ["install-hooks", "--dest", str(tmp_path / "hooks"), "--no-recall"])
    assert "UserPromptSubmit" not in res.output
    res = CliRunner().invoke(app, ["recall", "something nobody ever saved anywhere"])
    assert res.exit_code == 0 and "Nothing relevant enough" in res.output


def test_reinstalling_replaces_older_engram_hooks(tmp_path):
    from engram.cli import hook_settings, merge_hook_settings
    path = tmp_path / "settings.json"
    old = {"hooks": {"PostToolUse": [
        {"matcher": "Write|Edit|MultiEdit", "hooks": [{"type": "command", "command": "/h/engram_save_hook.sh"}]},
        {"matcher": "Bash", "hooks": [{"type": "command", "command": "my-linter"}]}]}}
    path.write_text(json.dumps(old))
    new = hook_settings({"engram_save_hook.sh": "/h/engram_save_hook.sh",
                         "engram_precompact_hook.sh": "/h/engram_precompact_hook.sh"}, "/py -m engram.recall", python="/py")
    merge_hook_settings(path, new)
    post = json.loads(path.read_text())["hooks"]["PostToolUse"]
    commands = [h["command"] for g in post for h in g["hooks"]]
    assert commands == ["my-linter", "ENGRAM_PYTHON=/py /h/engram_save_hook.sh"]  # old entry replaced, yours kept


def test_project_wing(tmp_path, monkeypatch):
    repo = tmp_path / "code" / "My App"
    (repo / ".git").mkdir(parents=True)
    (repo / "src" / "api").mkdir(parents=True)
    assert rc.project_wing(str(repo / "src" / "api"), {}) == "my-app"       # git root's name
    assert rc.project_wing(str(tmp_path / "loose"), {}) == "loose"          # plain folder
    assert rc.project_wing(str(repo / "src"), {"projects": {str(repo): "billing"}}) == "billing"
    monkeypatch.setenv("HOME", str(tmp_path))
    assert rc.project_wing(str(tmp_path), {}) is None and rc.project_wing(None, {}) is None


def test_recall_prefers_the_current_project(mem, tmp_path):
    _, _, searcher, add = mem
    add("Auth decision: we use Lucia sessions for the login flow.", wing="billing")
    add("Auth decision: we use Lucia sessions for the login flow in the admin tool.", wing="admin")
    repo = tmp_path / "billing"
    (repo / ".git").mkdir(parents=True)
    note = rc.recall("which auth sessions library do we use for login?", "s1", searcher,
                     {**CFG, "recall_other_min_relevance": 0.99}, cwd=str(repo))
    assert "(billing/" in note and "(admin/" not in note
    anywhere = rc.recall("which auth sessions library do we use for login?", "s2", searcher, CFG)
    assert "(billing/" in anywhere and "(admin/" in anywhere  # no project: both qualify
