"""Keyword index + rank fusion, absolute dates in queries, and secret redaction."""

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from engram.backends import backend_from_config
from engram.backends import sqlitevec_backend as sv
from engram.chateau import Chateau, Drawer
from engram.config import DEFAULT_CONFIG
from engram.indexing import index_drawers
from engram.keyword_index import (
    KeywordIndex,
    KeywordIndexedBackend,
    _match_query,
    build_from_chateau,
)
from engram.redact import redact_secrets
from engram.searcher import Searcher, fuse_rankings
from engram.temporal import time_reference

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Keyword index
# ---------------------------------------------------------------------------

def test_match_query_drops_stopwords_and_quotes_terms():
    assert _match_query("What did I say about the Subaru in 2023?") == '"subaru" OR "2023"'
    assert _match_query("what is it") is None


def test_keyword_index_add_search_delete(tmp_path):
    idx = KeywordIndex(tmp_path / "kw.db")
    idx.add_many([
        ("a::0", "My new car is a blue Subaru Outback", {"drawer_id": "a", "wing": "w", "room": "cars"}),
        ("b::0", "We planted tomatoes in the garden", {"drawer_id": "b", "wing": "w", "room": "garden"}),
        ("c::0", "Subaru dealership hours", {"drawer_id": "c", "wing": "other", "room": "cars"}),
    ])
    hits = idx.search("which Subaru did I buy", n=5)
    assert {h["id"] for h in hits} == {"a::0", "c::0"}
    assert hits[0]["metadata"]["drawer_id"] in {"a", "c"} and hits[0]["score"] > 0
    assert [h["id"] for h in idx.search("Subaru", where={"wing": "w"})] == ["a::0"]
    assert idx.search("tomato garden")[0]["id"] == "b::0"  # stemming: tomatoes ~ tomato
    idx.add_many([("a::0", "Replaced text about bicycles", {"drawer_id": "a"})])  # re-add replaces
    assert idx.count() == 3 and not idx.search("Outback")
    idx.delete_where({"drawer_id": "c"})
    idx.delete("b::0")
    assert idx.count() == 1


@pytest.fixture
def sqlite_backend(tmp_path, monkeypatch):
    monkeypatch.setattr(sv, "_get_embedder", lambda: None)
    return sv.SqliteVecBackend(db_path=tmp_path / "vec.db")


def test_keyword_backend_mirrors_writes_and_passes_through(tmp_path, sqlite_backend):
    be = KeywordIndexedBackend(sqlite_backend, KeywordIndex(tmp_path / "kw.db"))
    index_drawers(be, [("d1", "The quarterly budget review is on Friday", {"wing": "w"})])
    assert be.count() == 1 and be.keywords.count() == 1
    assert be.keyword_search("budget review")[0]["metadata"]["drawer_id"] == "d1"
    from engram.indexing import unindex_drawer
    unindex_drawer(be, "d1")
    assert be.count() == 0 and be.keywords.count() == 0
    assert be._db_path == sqlite_backend._db_path  # other attributes pass through


def test_fuse_rankings_adds_keyword_only_hits():
    semantic = [{"id": "x", "text": "x", "metadata": {}, "final_score": 0.9},
                {"id": "y", "text": "y", "metadata": {}, "final_score": 0.8}]
    keyword = [{"id": "z::0", "text": "z", "metadata": {"drawer_id": "z", "room": "r"}, "score": 3.0},
               {"id": "y::1", "text": "y", "metadata": {"drawer_id": "y"}, "score": 2.0}]
    out = fuse_rankings(semantic, keyword)
    assert out[0]["id"] == "y"  # in both lists, so it beats the top of either one alone
    assert {r["id"] for r in out[1:]} == {"x", "z"}
    z = next(r for r in out if r["id"] == "z")
    assert z["semantic_score"] == 0.0 and z["metadata"]["room"] == "r" and z["fusion_score"] > 0


class NoMeaningBackend(KeywordIndexedBackend):
    """Meaning search finds nothing; only the keyword index can."""

    def search(self, query, n=10, where=None):
        return []


def test_searcher_finds_what_only_keywords_match(tmp_path, sqlite_backend):
    be = NoMeaningBackend(sqlite_backend, KeywordIndex(tmp_path / "kw.db"))
    index_drawers(be, [("d1", "Invoice INV-20931 was paid on Tuesday", {"wing": "w", "room": "bills"})])
    s = Searcher(be, Chateau(chateau_path=tmp_path / "c"), {"hybrid_weight": 0.0})
    assert s.search("INV-20931 invoice", no_decay=True) == []                         # off by default
    hits = s.search("INV-20931 invoice", no_decay=True, keyword_search=True)
    assert [h["id"] for h in hits] == ["d1"] and hits[0]["metadata"]["room"] == "bills"


def test_keyword_search_on_by_default_and_can_be_turned_off(engram_home, monkeypatch):
    monkeypatch.setattr(sv, "_get_embedder", lambda: None)
    assert DEFAULT_CONFIG["keyword_search"] is True
    from engram.config import load_config
    cfg = load_config()
    be = backend_from_config(cfg, fallback=True)
    assert hasattr(be, "keyword_search")
    assert (engram_home / "keyword_index.db").exists()
    assert not hasattr(backend_from_config({**cfg, "keyword_search": False}), "keyword_search")


def test_backend_from_config_builds_index_from_existing_drawers(engram_home, tmp_path, monkeypatch):
    monkeypatch.setattr(sv, "_get_embedder", lambda: None)
    palace = Chateau(chateau_path=tmp_path / "chateau")
    palace.save_drawer(Drawer(content="Remember the Kyoto trip planning notes", wing="w", room="travel", hall="facts"))
    cfg = {"vector_backend": "sqlitevec", "keyword_search": True,
           "chateau_path": str(tmp_path / "chateau"), "keyword_index_path": str(tmp_path / "kw.db")}
    be = backend_from_config(cfg)
    assert isinstance(be, KeywordIndexedBackend)
    assert be.keyword_search("Kyoto trip")[0]["metadata"]["room"] == "travel"
    assert build_from_chateau(be.keywords, tmp_path / "chateau") == 1  # rebuild is idempotent
    assert be.keywords.count() == 1


# ---------------------------------------------------------------------------
# Absolute dates
# ---------------------------------------------------------------------------

NOW = datetime(2023, 7, 20, tzinfo=timezone.utc)


@pytest.mark.parametrize("query, expected", [
    ("what happened in June?", (34, 16)),
    ("what did I do on May 8", (72, 2)),
    ("the party on 8 May 2023", (72, 2)),
    ("the 3rd of June", (46, 2)),
    ("in early March 2023", (126, 16)),
    ("what did I buy in December", (216, 16)),   # most recent December: 2022
    ("events in 2022", (383, 183)),
    ("Dec. 25", (206, 2)),
    ("I may go to the beach", None),             # "may" the verb
    ("may I ask something", None),
    ("they march on", None),
    ("september 31", None),                      # not a date
    ("plans for June 2030", None),               # in the future
])
def test_absolute_dates(query, expected):
    assert time_reference(query, NOW) == expected


def test_absolute_dates_need_a_reference_time():
    assert time_reference("what happened in June?") is None
    assert time_reference("two weeks ago") == (14, 5)  # relative phrases need none


# ---------------------------------------------------------------------------
# Secret redaction
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("secret, kind", [
    ("sk-ant-api03-" + "a" * 40, "api_key"),
    ("ghp_" + "b" * 36, "github_token"),
    ("AKIA" + "C" * 16, "aws_access_key"),
    ("xoxb-1234567890-abcdefghij", "slack_token"),
    ("AIza" + "d" * 35, "google_api_key"),
    ("123456789:" + "E" * 35, "telegram_bot_token"),
    ("eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0.SflKxwRJSMeKKF2QT4fw", "jwt"),
])
def test_redacts_known_secret_formats(secret, kind):
    assert redact_secrets(f"use {secret} please") == f"use [REDACTED:{kind}] please"


def test_redacts_assignments_and_private_keys_but_not_prose():
    assert redact_secrets("password: hunter2222") == "password: [REDACTED:password]"
    assert redact_secrets('api_key = "abc123def456"') == 'api_key = "[REDACTED:api_key]"'
    key = "-----BEGIN RSA PRIVATE KEY-----\nMIIE\n-----END RSA PRIVATE KEY-----"
    assert redact_secrets(f"key:\n{key}") == "key:\n[REDACTED:private_key]"
    prose = "I changed my password yesterday and the token system works."
    assert redact_secrets(prose) == prose


def test_chateau_redacts_only_when_enabled(tmp_path):
    secret = "ghp_" + "x" * 36
    on = Chateau(chateau_path=tmp_path / "on", redact=True)
    off = Chateau(chateau_path=tmp_path / "off")
    for palace in (on, off):
        palace.save_drawer(Drawer(content=f"token {secret}", wing="w", room="r", hall="facts"))
    assert [d.content for d in on.iter_drawers()] == ["token [REDACTED:github_token]"]
    assert [d.content for d in off.iter_drawers()] == [f"token {secret}"]


def test_redaction_reaches_the_search_index(tmp_path, sqlite_backend):
    from engram.convo_miner import ConvoMiner
    palace = Chateau(chateau_path=tmp_path / "c", redact=True)
    be = KeywordIndexedBackend(sqlite_backend, KeywordIndex(tmp_path / "kw.db"))
    ConvoMiner(palace, be, {"preference_summaries": False}).store_messages(
        [{"role": "user", "text": "here is my key sk-proj-" + "z" * 30, "timestamp": "", "id": "m1"}],
        "w", "r")
    stored = be.keywords.search("key", n=5)
    assert stored and "sk-proj" not in stored[0]["text"] and "[REDACTED:api_key]" in stored[0]["text"]


def test_redaction_off_by_default():
    assert DEFAULT_CONFIG["redact_secrets"] is False


# ---------------------------------------------------------------------------
# Benchmark runners accept --keywords
# ---------------------------------------------------------------------------

def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / "benchmarks" / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_runners_accept_keywords(tmp_path):
    lme = _load("lme", "longmemeval_bench.py").run_longmemeval(
        ROOT / "tests" / "fixtures" / "longmemeval_sample.json", backend="sqlitevec", keywords=True)
    assert lme["keywords"] is True and lme["recall_any@5"] == 1.0
    out = tmp_path / "loc.jsonl"
    loc = _load("loc", "locomo_bench.py").run_locomo(
        ROOT / "tests" / "fixtures" / "locomo_sample.json", backend="sqlitevec", keywords=True, out=out)
    assert loc["keywords"] is True and loc["questions"] == 5
    assert all("ranked" in json.loads(line) for line in out.read_text().splitlines())
