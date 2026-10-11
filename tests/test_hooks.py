"""Claude Code hooks: run the real scripts with the payloads Claude Code sends."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from engram.chateau import Chateau
from engram.cli import app
from engram.convo_miner import ConvoMiner, _detect_format, _parse_claude, _parse_claude_code
from engram.miner import Miner

HOOKS = Path(__file__).resolve().parent.parent / "engram" / "hooks"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="hooks need bash")


@pytest.fixture
def hook_env(tmp_path):
    bin_dir = Path(sys.executable).parent
    if shutil.which("engram", path=str(bin_dir)) is None:
        pytest.skip("engram console script not installed next to this interpreter")
    home = tmp_path / "home"
    env = dict(os.environ)
    env.update(HOME=str(home), ENGRAM_VECTOR_BACKEND="sqlitevec",
               PATH=f"{bin_dir}{os.pathsep}{env.get('PATH', '')}")
    return env, home / ".engram"


def run_hook(name, payload, env):
    return subprocess.run(["bash", str(HOOKS / name)], input=json.dumps(payload),
                          capture_output=True, text=True, env=env, timeout=120)


def drawers(engram_dir, pattern):
    return sorted((engram_dir / "chateau").rglob(pattern))


TRANSCRIPT = [
    {"type": "user", "uuid": "u1", "timestamp": "2026-10-10T10:00:00Z",
     "message": {"role": "user", "content": "I prefer small pull requests over big ones"}},
    {"type": "assistant", "uuid": "a1", "timestamp": "2026-10-10T10:00:05Z",
     "message": {"role": "assistant", "content": [
         {"type": "thinking", "thinking": "private reasoning"},
         {"type": "text", "text": "Got it, I will keep each change small and focused."},
         {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]}},
    {"type": "user", "uuid": "u2", "isMeta": True,
     "message": {"role": "user", "content": "<command-name>/clear</command-name> meta entry"}},
    {"type": "user", "uuid": "u3",
     "message": {"role": "user", "content": [{"type": "tool_result", "content": "tool output text"}]}},
    {"type": "summary", "summary": "not a message"},
]


def write_transcript(path):
    path.write_text("\n".join(json.dumps(r) for r in TRANSCRIPT) + "\n")
    return path


# ---------------------------------------------------------------------------
# Save hook (PostToolUse)
# ---------------------------------------------------------------------------

def test_save_hook_mines_file_from_tool_input(hook_env, tmp_path):
    env, engram_dir = hook_env
    note = tmp_path / "note.md"
    note.write_text("Turns out the root cause was a stale cache key.")
    payload = {"hook_event_name": "PostToolUse", "tool_name": "Write",
               "tool_input": {"file_path": str(note), "content": "..."}}

    assert run_hook("engram_save_hook.sh", payload, env).returncode == 0
    note.write_text("Turns out the root cause was a stale cache key in redis.")
    assert run_hook("engram_save_hook.sh", payload, env).returncode == 0

    files = drawers(engram_dir, "file-*.json")
    assert len(files) == 1, "re-saving a file must replace its drawer"
    assert "in redis" in json.loads(files[0].read_text())["content"]
    diary = (engram_dir / "agents" / "claude-code_diary.jsonl").read_text().splitlines()
    assert len(diary) == 2


def test_save_hook_ignores_missing_or_bad_input(hook_env):
    env, engram_dir = hook_env
    for payload in ({}, {"tool_input": {"file_path": "/does/not/exist"}}, {"tool_input": None}):
        assert run_hook("engram_save_hook.sh", payload, env).returncode == 0
    r = subprocess.run(["bash", str(HOOKS / "engram_save_hook.sh")], input="not json",
                       capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0
    assert not (engram_dir / "chateau").exists() or not drawers(engram_dir, "*.json")


def test_save_hook_does_not_execute_file_names(hook_env, tmp_path):
    env, _ = hook_env
    evil = tmp_path / "x'); import os; os.system('touch PWNED'); ('.md"
    evil.write_text("Some note about the deploy pipeline and its stages.")
    run_hook("engram_save_hook.sh", {"tool_input": {"file_path": str(evil)}}, env)
    assert not (tmp_path / "PWNED").exists()
    assert not Path("PWNED").exists()


# ---------------------------------------------------------------------------
# Pre-compact hook
# ---------------------------------------------------------------------------

def test_precompact_hook_mines_transcript_once(hook_env, tmp_path):
    env, engram_dir = hook_env
    transcript = write_transcript(tmp_path / "session.jsonl")
    payload = {"hook_event_name": "PreCompact", "trigger": "auto",
               "transcript_path": str(transcript)}

    first = run_hook("engram_precompact_hook.sh", payload, env)
    run_hook("engram_precompact_hook.sh", payload, env)

    assert first.returncode == 0 and first.stdout == ""
    contents = sorted(json.loads(p.read_text())["content"]
                      for p in drawers(engram_dir, "msg-*.json"))
    assert contents == [
        "Got it, I will keep each change small and focused.",
        "I prefer small pull requests over big ones",
    ]
    assert all(p.parent.parent.name == "conversation" for p in drawers(engram_dir, "msg-*.json"))


def test_precompact_hook_ignores_missing_transcript(hook_env):
    env, _ = hook_env
    assert run_hook("engram_precompact_hook.sh", {"transcript_path": "/nope.jsonl"}, env).returncode == 0
    assert run_hook("engram_precompact_hook.sh", {}, env).returncode == 0


# ---------------------------------------------------------------------------
# Parsers and miners (in-process)
# ---------------------------------------------------------------------------

class _Backend:
    def add(self, id, text, metadata):
        pass

    def delete(self, id):
        pass

    def delete_where(self, where):
        pass

    def add_many(self, items):
        for id, text, metadata in items:
            self.add(id, text, metadata)


def test_claude_code_transcript_detection_and_parsing(tmp_path):
    transcript = write_transcript(tmp_path / "session.jsonl")
    assert _detect_format(transcript) == "claude_code"
    msgs = _parse_claude_code(transcript)
    assert [(m["role"], m["text"]) for m in msgs] == [
        ("user", "I prefer small pull requests over big ones"),
        ("assistant", "Got it, I will keep each change small and focused."),
    ]
    other = tmp_path / "other.jsonl"
    other.write_text('{"event": "something else"}\n')
    assert _detect_format(other) == "unknown"


def test_older_claude_export_uses_text_field(tmp_path):
    export = tmp_path / "conversations.json"
    export.write_text(json.dumps([{"chat_messages": [
        {"sender": "human", "text": "Old export message text here", "uuid": "m1"}]}]))
    assert _parse_claude(export)[0]["text"] == "Old export message text here"


def test_reimporting_conversation_adds_no_duplicates(tmp_path):
    palace = Chateau(chateau_path=tmp_path / "chateau")
    transcript = write_transcript(tmp_path / "session.jsonl")
    cm = ConvoMiner(palace, _Backend(), config={})
    cm.mine(transcript, wing="w", room="chat")
    cm.mine(transcript, wing="w", room="chat-renamed")
    assert len(list(palace.iter_drawers())) == 2


def test_remining_file_replaces_drawer_even_if_hall_changes(tmp_path):
    palace = Chateau(chateau_path=tmp_path / "chateau")
    note = tmp_path / "note.md"
    miner = Miner(palace, _Backend(), config={})
    note.write_text("Turns out the root cause was a stale cache key.")
    first = miner.mine(note, wing="w")[0]
    note.write_text("I prefer tabs over spaces, I'd rather not mix them.")
    second = miner.mine(note, wing="w")[0]
    assert first.id == second.id and first.hall != second.hall
    assert [d.content for d in palace.iter_drawers()] == [note.read_text()]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_mine_accepts_room(engram_home, tmp_path):
    note = tmp_path / "note.md"
    note.write_text("Deployed version two to production yesterday.")
    result = CliRunner().invoke(app, ["mine", str(note), "--wing", "w", "--room", "release"])
    assert result.exit_code == 0, result.output
    assert [r.name for r in Chateau().list_rooms("w")] == ["release"]


def test_install_hooks_copies_executable_scripts(tmp_path):
    dest = tmp_path / "hooks"
    result = CliRunner().invoke(app, ["install-hooks", "--dest", str(dest)])
    assert result.exit_code == 0, result.output
    for name in ("engram_save_hook.sh", "engram_precompact_hook.sh"):
        assert os.access(dest / name, os.X_OK)
    snippet = json.loads(result.output[result.output.index("{"):])
    assert snippet["hooks"]["PostToolUse"][0]["matcher"] == "Write|Edit|MultiEdit"
    assert snippet["hooks"]["PreCompact"][0]["hooks"][0]["command"] == str(dest / "engram_precompact_hook.sh")
