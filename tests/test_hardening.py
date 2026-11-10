"""Privacy and crash-safety guarantees: private files, no credential files in
memory, no pickle, one writer at a time, errors that don't leak paths."""

import json
import os
import pickle
import stat
import threading
import time

import pytest

from engram import config, fsio, locking
from engram.chateau import Chateau
from engram.convo_miner import _parse_claude_code, strip_harness_text
from engram.miner import Miner, is_secret_file

posix = pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")


class _NullBackend:
    def add(self, *a, **k): pass
    def add_many(self, *a, **k): pass
    def delete(self, *a, **k): pass
    def delete_where(self, *a, **k): pass


# -- private files -----------------------------------------------------------

@posix
def test_memory_folder_and_files_are_owner_only(engram_home):
    engram_home.mkdir(parents=True)
    os.chmod(engram_home, 0o755)
    config.load_config()
    assert stat.S_IMODE(engram_home.stat().st_mode) == 0o700
    target = engram_home / "note.json"
    fsio.atomic_write_text(target, "{}")
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_config_is_saved_whole_and_a_broken_one_is_reported(engram_home, capsys):
    config.save_config({"reranker": True})
    assert json.loads(config.CONFIG_PATH.read_text()) == {"reranker": True}
    assert not [p for p in engram_home.iterdir() if p.name.endswith(".tmp")]
    config.CONFIG_PATH.write_text("{ not json")
    config._warned.clear()
    assert config.load_config()["vector_backend"]  # defaults still load
    assert "could not be read" in capsys.readouterr().err


# -- the miner never ingests credential files ----------------------------------

@pytest.mark.parametrize("name", [".env", ".env.production", "prod.env", "id_rsa", "server.pem", "tls.key",
                                  ".npmrc", ".netrc", "credentials.json", "terraform.tfstate"])
def test_credential_files_are_recognised(tmp_path, name):
    assert is_secret_file(tmp_path / name)


@pytest.mark.parametrize("name", [".env.example", "environment.md", "keys.md", "notes.txt", "main.py"])
def test_ordinary_files_are_not(tmp_path, name):
    assert not is_secret_file(tmp_path / name)


def test_mining_skips_credential_files_and_links_out_of_the_project(tmp_path):
    project, outside = tmp_path / "proj", tmp_path / "outside"
    project.mkdir(), outside.mkdir()
    (project / "notes.md").write_text("We decided to ship the importer on Friday after the review.")
    (project / ".env").write_text("API_KEY=sk-live-0000000000000000000000000000")
    (project / "deploy.pem").write_text("-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----")
    (outside / "diary.md").write_text("Something private that lives outside the project folder.")
    try:
        (project / "linked.md").symlink_to(outside / "diary.md")
    except OSError:
        pass
    palace = Chateau(chateau_path=tmp_path / "chateau")
    Miner(palace, _NullBackend(), {}).mine(project, wing="proj")
    texts = [d.content for d in palace.iter_drawers()]
    assert len(texts) == 1 and "importer" in texts[0]
    # asked for by name: still refused
    assert Miner(palace, _NullBackend(), {}).mine(project / ".env", wing="proj") == []


def test_a_file_whose_512th_byte_splits_a_character_is_still_text(tmp_path):
    from engram.miner import _is_text_file
    f = tmp_path / "accents.txt"
    f.write_bytes(b"a" * 511 + "é".encode() + b" and more text")
    assert _is_text_file(f)
    (tmp_path / "blob.txt").write_bytes(b"\xff\xfe\x00\x01" * 200)
    assert not _is_text_file(tmp_path / "blob.txt")


# -- transcripts: what the app wrote is not a memory --------------------------

def test_app_boilerplate_is_removed_from_transcripts(tmp_path):
    assert strip_harness_text("<system-reminder>\nUse tools.\n</system-reminder>\nPlease use tabs, not spaces.") \
        == "Please use tabs, not spaces."
    assert strip_harness_text("<system-reminder>only this</system-reminder>") == ""
    assert strip_harness_text("This session is being continued from a previous conversation that ran out") == ""
    log = tmp_path / "session.jsonl"
    log.write_text("\n".join(json.dumps(r) for r in [
        {"type": "user", "uuid": "1", "message": {"role": "user", "content": "<system-reminder>x</system-reminder>"}},
        {"type": "user", "uuid": "2", "message": {"role": "user", "content": [
            {"type": "text", "text": "<system-reminder>ignore</system-reminder>I prefer small pull requests."}]}},
    ]))
    assert [m["text"] for m in _parse_claude_code(log)] == ["I prefer small pull requests."]


# -- FAISS side-car: JSON, and old pickles are read as data only ---------------

def test_legacy_pickle_is_loaded_as_data_and_code_is_refused(tmp_path):
    from engram.backends.faiss_backend import _load_legacy_pickle
    good = tmp_path / "metadata.pkl"
    good.write_bytes(pickle.dumps({"meta": {0: {"id": "a", "text": "t", "metadata": {"pinned": True}}},
                                   "id_map": {"a": 0}, "next": 1}))
    assert _load_legacy_pickle(good)["id_map"] == {"a": 0}

    class Evil:
        def __reduce__(self):
            return (os.system, ("echo pwned",))

    bad = tmp_path / "evil.pkl"
    bad.write_bytes(pickle.dumps({"meta": Evil()}))
    with pytest.raises(pickle.UnpicklingError):
        _load_legacy_pickle(bad)


# -- one writer at a time -------------------------------------------------------

@pytest.mark.skipif(locking.fcntl is None, reason="needs flock")
def test_store_lock_makes_writers_take_turns(tmp_path):
    a, b = locking.StoreLock(tmp_path / "lock"), locking.StoreLock(tmp_path / "lock")  # two "processes"
    order = []

    def second():
        with b:
            order.append("b")

    with a:
        t = threading.Thread(target=second)
        t.start()
        time.sleep(0.2)
        order.append("a")
    t.join(5)
    assert order == ["a", "b"]
    with a.shared(), b.shared():   # readers don't block each other
        pass
    a.close(), b.close()


@pytest.mark.skipif(locking.fcntl is None, reason="needs flock")
def test_a_stuck_lock_holder_does_not_hang_everyone_else(tmp_path, capsys):
    a, b = locking.StoreLock(tmp_path / "lock"), locking.StoreLock(tmp_path / "lock", timeout=0.2)
    with a:
        start = time.monotonic()
        with b:
            pass
        assert time.monotonic() - start < 2
    assert "continuing without it" in capsys.readouterr().err


# -- the MCP server keeps stack traces to itself --------------------------------

def test_mcp_internal_errors_do_not_send_a_traceback(engram_home, monkeypatch, capsys):
    import io

    from engram import mcp_server
    monkeypatch.setattr(mcp_server, "_handle_message", lambda *a: 1 / 0)
    monkeypatch.setattr("sys.stdin", io.StringIO('{"jsonrpc": "2.0", "id": 7, "method": "tools/list"}\n[1, 2]\n'))
    mcp_server.run_server()
    out, err = capsys.readouterr()
    replies = [json.loads(line) for line in out.splitlines() if line.strip()]
    assert [r["error"]["message"] for r in replies] == ["internal error (ZeroDivisionError)"] * 2
    assert "Traceback" not in out and "Traceback" in err
